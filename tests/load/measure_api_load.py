"""Measure the deterministic assessment endpoint under concurrent load."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from statistics import mean

import httpx


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


PAYLOAD = {
    "monthly_income": 7_000_000,
    "existing_debt": 0,
    "credit_grade": 1,
    "requested_amount": 30_000_000,
    "employment_type": "정규직",
    "collateral_owned": False,
}


@dataclass
class WorkerResult:
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0
    statuses: Counter = field(default_factory=Counter)


def _worker(url: str, deadline: float) -> WorkerResult:
    result = WorkerResult()
    timeout = httpx.Timeout(15.0, connect=5.0, write=5.0, pool=5.0)
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
    with httpx.Client(timeout=timeout, limits=limits) as client:
        while time.perf_counter() < deadline:
            started = time.perf_counter()
            try:
                response = client.post(
                    url,
                    json=PAYLOAD,
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
                result.statuses[str(response.status_code)] += 1
                if response.status_code < 200 or response.status_code >= 300:
                    result.errors += 1
            except Exception as exc:
                result.statuses[type(exc).__name__] += 1
                result.errors += 1
            result.latencies_ms.append((time.perf_counter() - started) * 1000)
    return result


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _pool_configuration() -> dict:
    from loan_agent.db import engine as db_engine

    pool = db_engine.get_engine().pool
    return {
        "pool_size": pool.size(),
        "max_overflow": pool._max_overflow,
        "pool_timeout_seconds": pool._timeout,
        "pool_recycle_seconds": pool._recycle,
        "pool_pre_ping": True,
        "db_statement_timeout_ms": 5_000,
    }


def measure(url: str, concurrency: int, duration: int) -> dict:
    start = time.perf_counter()
    deadline = start + duration
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_worker, url, deadline) for _ in range(concurrency)]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - start

    latencies = [latency for result in results for latency in result.latencies_ms]
    statuses = Counter()
    errors = 0
    for result in results:
        statuses.update(result.statuses)
        errors += result.errors
    total = len(latencies)
    return {
        "concurrency": concurrency,
        "requested_duration_seconds": duration,
        "wall_clock_seconds": round(elapsed, 3),
        "total_requests": total,
        "successful_requests": total - errors,
        "error_requests": errors,
        "error_rate": errors / total if total else None,
        "throughput_requests_per_second": total / elapsed if elapsed else None,
        "latency_ms": {
            "mean": mean(latencies) if latencies else None,
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "p99": _percentile(latencies, 99),
            "max": max(latencies) if latencies else None,
        },
        "statuses": dict(statuses),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/assessments")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[10, 50, 100])
    args = parser.parse_args()

    results = []
    for concurrency in args.concurrency:
        results.append(measure(args.url, concurrency, args.duration))
    print(
        json.dumps(
            {
                "target": args.url,
                "method": "POST",
                "payload_shape": "fixed valid structured payload",
                "idempotency_key": "new UUIDv4 for every request",
                "hardware": {
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                    "logical_cpus": os.cpu_count(),
                },
                "pool_configuration": _pool_configuration(),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
