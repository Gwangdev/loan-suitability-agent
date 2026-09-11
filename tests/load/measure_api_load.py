"""Measure the deterministic assessment endpoint under concurrent load."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


def _git_commit() -> str | None:
    """측정한 코드가 무엇이었는지 결과 파일이 스스로 말하게 한다.

    수치만 남기면 이후 코드가 바뀌었을 때 그 수치가 어느 시점의 것인지 알 수 없어,
    문서가 인용하는 근거가 조용히 낡는다. 작업 트리에 커밋되지 않은 변경이 있으면
    해시만으로는 재현되지 않으므로 그 사실도 함께 적는다.

    추적 중인 파일은 어디서 바뀌었든 미커밋 변경으로 본다. 이 측정 스크립트나 의존성
    목록처럼 패키지 폴더 밖의 파일도 수치를 바꾸기 때문이다. 문서만 고쳐도 표시가 붙지만,
    재현되지 않는 결과를 재현된다고 적는 쪽보다 낫다. 추적되지 않은 파일은 코드가 있는
    자리만 본다 — 전체를 보면 지금 쓰고 있는 결과 파일 자체가 걸려 항상 표시가 붙는다.
    """
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        commit = git("rev-parse", "HEAD")
        changed = git("status", "--porcelain", "--untracked-files=no")
        new_code = git("ls-files", "--others", "--exclude-standard", "--", "loan_agent", "alembic", "tests/load")
    except (OSError, subprocess.CalledProcessError):
        return None
    new_code = "\n".join(p for p in new_code.splitlines() if not p.startswith("tests/load/results/"))
    return f"{commit}-dirty" if (changed or new_code) else commit


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
                "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_commit": _git_commit(),
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
