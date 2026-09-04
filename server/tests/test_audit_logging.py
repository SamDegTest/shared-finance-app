import importlib.util
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import AuditActionType, AuditLog, Base, Household, User
from app.services.audit_service import audit_service
from app.utils.privacy import anonymize_ip_address, sanitize_audit_details


@pytest.fixture(name="db_session")
def fixture_db_session() -> Any:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_ip_anonymization_ipv4_and_ipv6() -> None:
    """AC 2: Verifica il mascheramento privacy-compliant degli indirizzi IP."""
    # IPv4 standard -> mascheramento ultimo ottetto (/24)
    assert anonymize_ip_address("192.168.1.145") == "192.168.1.0"
    assert anonymize_ip_address("10.0.5.99") == "10.0.5.0"
    assert anonymize_ip_address("127.0.0.1") == "127.0.0.0"

    # IPv6 standard -> mascheramento ultimi 80 bit (/48)
    v6 = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
    assert anonymize_ip_address(v6) == "2001:db8:85a3::"

    # X-Forwarded-For con IP multipli
    assert anonymize_ip_address("192.168.1.50, 10.0.0.1") == "192.168.1.0"

    # Casi limite
    assert anonymize_ip_address(None) is None
    assert anonymize_ip_address("") is None
    assert anonymize_ip_address("invalid_ip_format") == "0.0.0.0"


def test_sanitize_audit_details_strips_sensitive_pii() -> None:
    """AC 4: Verifica che sanitize_audit_details rimuova tutte le PII."""
    raw_details = {
        "http_method": "POST",
        "elapsed_ms": 12.5,
        "status_code": 200,
        "user_email": "mario.rossi@example.com",
        "credit_card_number": "5500 0000 0000 0004",
        "fiscal_code": "RSSMRA85M01H501Z",
        "receipt_raw_text": "CONAD 45.50 EUR SCONTRINO",
        "password_hash": "secret123",
        "nested": {
            "safe_metric": 42,
            "client_name": "Mario Rossi",
            "auth_token": "bearer xyz",
        },
    }

    sanitized = sanitize_audit_details(raw_details)
    assert sanitized is not None

    # Campi tecnici conservati
    assert sanitized["http_method"] == "POST"
    assert sanitized["elapsed_ms"] == 12.5
    assert sanitized["status_code"] == 200
    assert sanitized["nested"]["safe_metric"] == 42

    # Campi PII rimossi
    assert "user_email" not in sanitized
    assert "credit_card_number" not in sanitized
    assert "fiscal_code" not in sanitized
    assert "receipt_raw_text" not in sanitized
    assert "password_hash" not in sanitized
    assert "client_name" not in sanitized["nested"]
    assert "auth_token" not in sanitized["nested"]


@pytest.mark.asyncio
async def test_audit_service_log_event_and_persistence(
    db_session: Session,
) -> None:
    """AC 1 & AC 2: Creazione e tracciamento record audit log su database."""
    user_id = uuid.uuid4()
    household_id = uuid.uuid4()

    user = User(
        id=user_id,
        email="test_audit@example.com",
        hashed_password="hash",
        full_name="Audit Tester",
    )
    db_session.add(user)
    db_session.flush()

    household = Household(
        id=household_id,
        name="Casa Audit",
        currency="EUR",
        created_by_id=user_id,
    )
    db_session.add(household)
    db_session.commit()

    # Creazione record AuditLog
    log_record = AuditLog(
        user_id=user_id,
        household_id=household_id,
        action=AuditActionType.READ_RECEIPT,
        resource_type="receipt",
        resource_id="rec_12345",
        ip_address_masked="192.168.1.0",
        status="SUCCESS",
        details={"elapsed_ms": 15.2, "status_code": 200},
    )
    db_session.add(log_record)
    db_session.commit()
    db_session.refresh(log_record)

    # Verifica query da DB
    stmt = select(AuditLog).where(AuditLog.id == log_record.id)
    saved = db_session.scalar(stmt)

    assert saved is not None
    assert saved.user_id == user_id
    assert saved.household_id == household_id
    assert saved.action == "READ_RECEIPT"
    assert saved.resource_type == "receipt"
    assert saved.resource_id == "rec_12345"
    assert saved.ip_address_masked == "192.168.1.0"
    assert saved.status == "SUCCESS"
    assert saved.details == {"elapsed_ms": 15.2, "status_code": 200}
    assert saved.created_at is not None


def test_middleware_intercepts_request_and_enqueues_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC 3: Verifica intercettazione non-bloccante da middleware."""
    enqueued_logs: list[dict[str, Any]] = []

    def mock_enqueue(**kwargs: Any) -> None:
        enqueued_logs.append(kwargs)

    monkeypatch.setattr(audit_service, "enqueue_audit_log", mock_enqueue)

    client = TestClient(app)

    # Invia richiesta a un endpoint delle households
    start = time.perf_counter()
    client.get(
        "/api/v1/households/00000000-0000-0000-0000-000000000001",
        headers={"x-forwarded-for": "192.168.5.88"},
    )
    elapsed = time.perf_counter() - start

    # La richiesta HTTP non è bloccata (tempi rapidi < 100ms)
    assert elapsed < 0.1
    # Verifica che il middleware abbia registrato l'evento
    assert len(enqueued_logs) == 1
    log = enqueued_logs[0]

    assert log["action"] == AuditActionType.READ_HOUSEHOLD
    assert log["resource_type"] == "household"
    assert log["resource_id"] == "00000000-0000-0000-0000-000000000001"
    assert log["ip_address"] == "192.168.5.88"
    assert log["status"] in ("SUCCESS", "FAILED")
    assert log["details"]["http_method"] == "GET"


def test_alembic_migration_0002_metadata() -> None:
    """AC 1: Verifica identificatori e dipendenze della migrazione Alembic 0002."""
    migration_path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0002_create_audit_logs.py"
    )
    assert migration_path.exists(), f"File non trovato: {migration_path}"

    spec = importlib.util.spec_from_file_location("migration_0002", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "0002_create_audit_logs"
    assert module.down_revision == "0001_initial_schema"
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
