import asyncio
import time
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import app
from app.services.audit_service import audit_service


@pytest.mark.asyncio
async def test_concurrent_load_and_latency_sla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simula 50 richieste concorrenti per verificare latenza e stabilità."""
    # Disabilita I/O di rete verso database esterno nel test di latenza pura HTTP
    monkeypatch.setattr(
        audit_service,
        "record_audit_log_async",
        AsyncMock(),
    )

    concurrency = 50
    household_id = uuid.uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        latencies_ms: list[float] = []

        async def send_request(req_id: int) -> int:
            start_t = time.perf_counter()
            # Alterna tra health check e generazione presigned upload URL
            if req_id % 2 == 0:
                res = await client.get("/api/v1/health")
            else:
                res = await client.post(
                    f"/api/v1/households/{household_id}/receipts/upload-url?file_extension=jpg"
                )
            elapsed = (time.perf_counter() - start_t) * 1000
            latencies_ms.append(elapsed)
            return res.status_code

        start_total = time.perf_counter()
        tasks = [send_request(i) for i in range(concurrency)]
        status_codes = await asyncio.gather(*tasks)
        total_time_s = time.perf_counter() - start_total

        # 1. Zero Error Rate (Tutte le richieste devono rispondere 200)
        assert len(status_codes) == concurrency
        assert all(code == 200 for code in status_codes), (
            f"Errori rilevati: {status_codes}"
        )

        # 2. Calcolo metriche di latenza
        latencies_sorted = sorted(latencies_ms)
        p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
        rps = concurrency / total_time_s

        # 3. Verifica SLA: P95 latenza < 150ms
        assert p95 < 150.0, f"Latenza P95 ({p95:.2f}ms) superiore all'SLA di 150ms!"
        assert rps > 50.0, f"Throughput ({rps:.2f} req/s) inferiore al target minimo!"
