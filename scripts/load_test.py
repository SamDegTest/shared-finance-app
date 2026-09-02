#!/usr/bin/env python3
"""Script di test di carico concorrente (Load Test) per shared-finance-app.

Uso:
  python scripts/load_test.py --url http://localhost:8000 --concurrency 30 --requests 150
"""

import argparse
import asyncio
import time
import uuid

import httpx


async def run_load_test(
    base_url: str, concurrency: int, total_requests: int
) -> None:
    print("================================================================")
    print(f"🚀 Avvio Load Test su: {base_url}")
    print(
        f"👥 Concorrenza: {concurrency} worker | 📊 Richieste totali: {total_requests}"
    )
    print("================================================================")

    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []
    status_counts: dict[int, int] = {}
    household_id = uuid.uuid4()

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        # Pre-check di raggiungibilità del server
        try:
            check_res = await client.get("/api/v1/health")
            if check_res.status_code != 200:
                print(
                    f"⚠️ Attenzione: /api/v1/health ha risposto con status {check_res.status_code}"
                )
        except (httpx.HTTPError, OSError):
            print(f"❌ ERRORE: Impossibile connettersi al server su {base_url}!")
            print("👉 Assicurati di aver avviato il server con:")
            print(
                "   cd server; .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000\n"
            )
            return

        async def make_request(idx: int) -> None:
            async with semaphore:
                start_t = time.perf_counter()
                try:
                    if idx % 2 == 0:
                        resp = await client.get("/api/v1/health")
                    else:
                        resp = await client.post(
                            f"/api/v1/households/{household_id}/receipts/upload-url?file_extension=jpg"
                        )
                    code = resp.status_code
                except httpx.ConnectError:
                    code = 0  # Server non raggiungibile
                except (httpx.HTTPError, OSError):
                    code = 500

                elapsed = (time.perf_counter() - start_t) * 1000
                latencies_ms.append(elapsed)
                status_counts[code] = status_counts.get(code, 0) + 1

        overall_start = time.perf_counter()
        tasks = [make_request(i) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        total_time_s = time.perf_counter() - overall_start

    # Report & Statistiche
    latencies_sorted = sorted(latencies_ms)
    p50 = latencies_sorted[int(len(latencies_sorted) * 0.50)]
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
    p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)]
    avg = sum(latencies_ms) / len(latencies_ms)
    rps = total_requests / total_time_s
    success_count = status_counts.get(200, 0)
    error_count = total_requests - success_count

    print("\n📈 RISULTATI TEST DI CARICO:")
    print("----------------------------------------------------------------")
    print(f"⏱️ Tempo totale:         {total_time_s:.2f} s")
    print(f"⚡ Throughput:           {rps:.2f} req/s")
    print(
        f"✅ Richieste 200 OK:     {success_count}/{total_requests} ({(success_count/total_requests)*100:.1f}%)"
    )
    print(f"❌ Errori:               {error_count}")
    print("----------------------------------------------------------------")
    print(f"📊 Latenza Media:        {avg:.2f} ms")
    print(f"📊 Latenza P50 (Mediana):{p50:.2f} ms")
    print(f"📊 Latenza P95:          {p95:.2f} ms")
    print(f"📊 Latenza P99:          {p99:.2f} ms")
    print(
        f"📊 Latenza Min / Max:    {min(latencies_ms):.2f} ms / {max(latencies_ms):.2f} ms"
    )
    print("================================================================")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Test CLI per shared-finance-app"
    )
    parser.add_argument(
        "--url", default="http://localhost:8000", help="Base URL del backend"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=30,
        help="Numero di worker concorrenti",
    )
    parser.add_argument(
        "--requests", type=int, default=100, help="Numero totale di richieste"
    )
    args = parser.parse_args()

    asyncio.run(run_load_test(args.url, args.concurrency, args.requests))


if __name__ == "__main__":
    main()
