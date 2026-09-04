import logging
import re
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.models.audit_log import AuditActionType
from app.services.audit_service import audit_service

logger = logging.getLogger("shared-finance-app.middleware")

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _map_expense_action(method: str) -> str:
    if method == "POST":
        return AuditActionType.CREATE_EXPENSE
    if method in ("PUT", "PATCH"):
        return AuditActionType.UPDATE_EXPENSE
    if method == "DELETE":
        return AuditActionType.DELETE_EXPENSE
    return AuditActionType.READ_EXPENSE


def _map_household_action(method: str) -> str:
    if method == "POST":
        return "CREATE_HOUSEHOLD"
    if method in ("PUT", "PATCH"):
        return AuditActionType.UPDATE_HOUSEHOLD
    return AuditActionType.READ_HOUSEHOLD


def _resolve_audit_action_and_resource(
    method: str, path: str
) -> tuple[str, str, str | None, uuid.UUID | None]:
    """Mappa metodo e path HTTP a tipo di azione, risorsa e household_id."""
    clean_path = path.lower()
    uuids = UUID_PATTERN.findall(path)
    resource_id = uuids[-1] if uuids else None

    household_id: uuid.UUID | None = None
    if uuids:
        try:
            household_id = uuid.UUID(uuids[0])
        except Exception:
            household_id = None

    if "/receipts/ingest" in clean_path or "/storage/upload" in clean_path:
        action: str = AuditActionType.UPLOAD_RECEIPT
        resource_type = "receipt"
    elif "/receipts" in clean_path or "/storage/download" in clean_path:
        action = AuditActionType.READ_RECEIPT
        resource_type = "receipt"
    elif "/expenses" in clean_path:
        action = _map_expense_action(method)
        resource_type = "expense"
    elif "/settlements" in clean_path or "/balances" in clean_path:
        action = AuditActionType.READ_SETTLEMENT
        resource_type = "settlement"
    elif "/households" in clean_path:
        action = _map_household_action(method)
        resource_type = "household"
    elif "/export" in clean_path:
        action = AuditActionType.EXPORT_FINANCIAL_REPORT
        resource_type = "financial_report"
    else:
        action = f"{method}_{clean_path.strip('/').replace('/', '_')[:32].upper()}"
        resource_type = "system"

    return action, resource_type, resource_id, household_id


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware asincrono non-bloccante per audit logging GDPR (Art. 30/32)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Non tracciare le richieste statiche o health check per performance
        path = request.url.path
        if path.startswith(("/docs", "/openapi.json", "/redoc", "/api/v1/health")):
            return await call_next(request)

        start_time = time.perf_counter()
        ip_header = request.headers.get("x-forwarded-for")
        client_ip = (
            ip_header.split(",")[0].strip()
            if ip_header
            else (request.client.host if request.client else None)
        )

        user_id_val = getattr(request.state, "user_id", None)
        user_uuid: uuid.UUID | None = None
        if user_id_val:
            try:
                user_uuid = (
                    uuid.UUID(str(user_id_val))
                    if not isinstance(user_id_val, uuid.UUID)
                    else user_id_val
                )
            except Exception:
                user_uuid = None

        method = request.method
        action, resource_type, res_id, household_uuid = (
            _resolve_audit_action_and_resource(method, path)
        )

        response: Response
        status_str = "SUCCESS"
        try:
            response = await call_next(request)
            if response.status_code >= 400:
                status_str = "FAILED"
            status_code = response.status_code
        except Exception:
            status_str = "FAILED"
            status_code = 500
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            details: dict[str, Any] = {
                "http_method": method,
                "path": path,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
            }

            # Accoda in modo non-bloccante (0 ms di overhead sulla risposta)
            audit_service.enqueue_audit_log(
                action=action,
                resource_type=resource_type,
                resource_id=res_id,
                user_id=user_uuid,
                household_id=household_uuid,
                ip_address=client_ip,
                status=status_str,
                details=details,
            )

        return response
