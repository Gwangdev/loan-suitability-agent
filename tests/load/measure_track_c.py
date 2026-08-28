"""Reproducible PostgreSQL index and token-cost measurements."""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text


INPUT_USD_PER_MILLION = Decimal("0.15")
OUTPUT_USD_PER_MILLION = Decimal("0.60")
PRICE_EFFECTIVE_DATE = "2026-08-28"
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4o-mini"
MEASUREMENT_NAMESPACE = uuid.UUID("b6f5fd1f-648b-4c4c-a18a-45d276fc85f5")
ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str):
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _synthetic_rows(count: int) -> list[dict]:
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    statuses = ("SCREENED", "COMPLETED", "EXPLANATION_FAILED", "REVIEW_REQUIRED")
    return [
        {
            "id": uuid.uuid5(MEASUREMENT_NAMESPACE, f"case-{index}"),
            "idempotency_key": f"track-c-index-{index}",
            "request_hash": f"request-hash-{index}",
            "status": statuses[index % len(statuses)],
            "monthly_income": 3_000_000 + index,
            "existing_debt": index % 5_000_000,
            "credit_grade": index % 10 + 1,
            "requested_amount": 5_000_000 + index,
            "employment_type": "정규직" if index % 2 else "계약직",
            "collateral_owned": index % 3 == 0,
            "created_at": base_time + timedelta(seconds=index // 2),
            "updated_at": base_time + timedelta(seconds=index // 2),
        }
        for index in range(count)
    ]


def _prepare_index_database(database_url: str, count: int) -> None:
    from alembic import command

    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001_integrity")
    rows = _synthetic_rows(count)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO assessment_case "
                    "(id, idempotency_key, request_hash, status, "
                    "monthly_income, existing_debt, credit_grade, requested_amount, "
                    "employment_type, collateral_owned, created_at, updated_at) "
                    "VALUES (:id, :idempotency_key, :request_hash, :status, "
                    ":monthly_income, :existing_debt, :credit_grade, :requested_amount, "
                    ":employment_type, :collateral_owned, :created_at, :updated_at)"
                ),
                rows,
            )
            connection.execute(text("ANALYZE assessment_case"))
    finally:
        engine.dispose()


def _plan(database_url: str, connection=None) -> dict:
    engine = create_engine(database_url)
    try:
        active_connection = connection or engine.connect()
        try:
            raw = active_connection.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    "SELECT id, created_at FROM assessment_case "
                    "WHERE status = 'SCREENED' "
                    "ORDER BY created_at DESC, id DESC LIMIT 100"
                )
            ).scalar_one()
        finally:
            if connection is None:
                active_connection.close()
    finally:
        engine.dispose()

    document = json.loads(raw) if isinstance(raw, str) else raw
    explain = document[0]
    root = explain["Plan"]
    nodes = []

    def visit(node: dict) -> None:
        nodes.append(
            {
                "node_type": node.get("Node Type"),
                "index": node.get("Index Name"),
                "relation": node.get("Relation Name"),
                "actual_rows": node.get("Actual Rows"),
                "actual_total_ms": node.get("Actual Total Time"),
                "index_condition": node.get("Index Cond"),
                "filter": node.get("Filter"),
                "rows_removed_by_filter": node.get("Rows Removed by Filter"),
                "heap_fetches": node.get("Heap Fetches"),
            }
        )
        for child in node.get("Plans", []):
            visit(child)

    visit(root)
    return {
        "planning_ms": explain.get("Planning Time"),
        "execution_ms": explain.get("Execution Time"),
        "nodes": nodes,
    }


def _plan_without_index(database_url: str, index_name: str) -> dict:
    allowed_indexes = {
        "ix_assessment_case_cursor",
        "ix_assessment_case_status_cursor",
    }
    if index_name not in allowed_indexes:
        raise ValueError(f"unexpected index name: {index_name}")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f"DROP INDEX {index_name}"))
                return _plan(database_url, connection=connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def measure_indexes(database_url: str, count: int) -> None:
    from alembic import command

    config = _alembic_config(database_url)
    _prepare_index_database(database_url, count)
    try:
        before = _plan(database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                connection.execute(text("ANALYZE assessment_case"))
        finally:
            engine.dispose()
        after = _plan(database_url)
        after_without_cursor = _plan_without_index(
            database_url, "ix_assessment_case_cursor"
        )
        after_without_status = _plan_without_index(
            database_url, "ix_assessment_case_status_cursor"
        )
        print(
            json.dumps(
                {
                    "database_url": database_url,
                    "rows": count,
                    "query": (
                        "WHERE status = 'SCREENED' "
                        "ORDER BY created_at DESC, id DESC LIMIT 100"
                    ),
                    "before_0002": before,
                    "after_0002": after,
                    "after_0002_without_cursor_index": after_without_cursor,
                    "after_0002_without_status_index": after_without_status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        command.upgrade(config, "head")


def _usage_snapshots() -> list[dict[str, int]]:
    fixture = json.loads((ROOT / "loan_agent" / "demo_fixtures.json").read_text())
    snapshots = []
    for case in fixture.get("cases", []):
        usage = case.get("result", {}).get("usage", "")
        values = {
            key: int(value)
            for key, value in re.findall(
                r"\b(prompt_tokens|completion_tokens|successful_requests)=(\d+)",
                usage,
            )
        }
        if set(values) != {"prompt_tokens", "completion_tokens", "successful_requests"}:
            raise ValueError(f"usage snapshot is incomplete for {case.get('name')}")
        snapshots.append(values)
    return snapshots


def _snapshot_deltas(snapshots: list[dict[str, int]]) -> list[dict[str, int]]:
    previous = {key: 0 for key in snapshots[0]}
    deltas = []
    for snapshot in snapshots:
        delta = {key: snapshot[key] - previous[key] for key in snapshot}
        if any(value < 0 for value in delta.values()):
            raise ValueError("usage snapshots are not monotonic")
        deltas.append(delta)
        previous = snapshot
    return deltas


def _cost(input_tokens: Decimal, output_tokens: Decimal) -> Decimal:
    return (
        input_tokens * INPUT_USD_PER_MILLION
        + output_tokens * OUTPUT_USD_PER_MILLION
    ) / Decimal(1_000_000)


def _database_token_summary(database_url: str) -> dict:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT count(*) AS runs, "
                    "count(*) FILTER (WHERE input_tokens IS NOT NULL "
                    "AND output_tokens IS NOT NULL) AS complete_runs, "
                    "avg(input_tokens) FILTER (WHERE input_tokens IS NOT NULL) "
                    "AS avg_input_tokens, "
                    "avg(output_tokens) FILTER (WHERE output_tokens IS NOT NULL) "
                    "AS avg_output_tokens FROM explanation_run"
                )
            ).mappings().one()
    finally:
        engine.dispose()
    return {
        "runs": row["runs"],
        "complete_token_runs": row["complete_runs"],
        "average_input_tokens": (
            float(row["avg_input_tokens"])
            if row["avg_input_tokens"] is not None
            else None
        ),
        "average_output_tokens": (
            float(row["avg_output_tokens"])
            if row["avg_output_tokens"] is not None
            else None
        ),
    }


def measure_cost(database_url: str, monthly_requests: int) -> None:
    snapshots = _usage_snapshots()
    deltas = _snapshot_deltas(snapshots)
    average_input = Decimal(sum(row["prompt_tokens"] for row in deltas)) / len(deltas)
    average_output = Decimal(sum(row["completion_tokens"] for row in deltas)) / len(deltas)
    per_request = _cost(average_input, average_output)
    print(
        json.dumps(
            {
                "model": "gpt-4o-mini",
                "price_effective_date": PRICE_EFFECTIVE_DATE,
                "price_source": PRICE_SOURCE,
                "input_usd_per_million": str(INPUT_USD_PER_MILLION),
                "output_usd_per_million": str(OUTPUT_USD_PER_MILLION),
                "pricing_note": "standard input price used; cached-input discount is not modeled",
                "database_observation": _database_token_summary(database_url),
                "recorded_fixture_observation": {
                    "fixture_generated_at": "2026-07-27T14:42:17",
                    "cases": len(deltas),
                    "method": "differences between cumulative usage_metrics snapshots",
                    "average_input_tokens": float(average_input),
                    "average_output_tokens": float(average_output),
                    "per_request_cost_usd": str(per_request.quantize(Decimal("0.00000001"))),
                    "monthly_requests": monthly_requests,
                    "monthly_cost_usd": str(
                        (per_request * monthly_requests).quantize(Decimal("0.0001"))
                    ),
                    "deltas": deltas,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("indexes")
    index_parser.add_argument(
        "--db-url",
        default=os.getenv(
            "DATABASE_URL", "postgresql+psycopg2:///loan_suitability_measurement"
        ),
    )
    index_parser.add_argument("--rows", type=int, default=10_000)

    cost_parser = subparsers.add_parser("cost")
    cost_parser.add_argument(
        "--db-url",
        default=os.getenv(
            "DATABASE_URL", "postgresql+psycopg2:///loan_suitability_test"
        ),
    )
    cost_parser.add_argument("--monthly-requests", type=int, default=10_000)

    args = parser.parse_args()
    if args.command == "indexes":
        measure_indexes(args.db_url, args.rows)
    else:
        measure_cost(args.db_url, args.monthly_requests)


if __name__ == "__main__":
    main()
