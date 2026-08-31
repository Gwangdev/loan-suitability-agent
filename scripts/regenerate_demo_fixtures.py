"""토큰 없이 열람하는 데모 결과를 다시 굽는다.

방문자가 키 없이 「입력 → 실제 출력」을 볼 수 있게 하려면 실제 실행 결과를 한 번
저장해 두어야 한다. 그 파일이 `loan_agent/demo_fixtures.json`이고, 파이프라인이
바뀌면 내용이 낡으므로 이 스크립트로 다시 굽는다.

**오너 키가 필요하다.** 저장소에 키를 두지 않으므로 실행자가 환경변수로 넘긴다.

    OPENAI_API_KEY=sk-... python3.11 scripts/regenerate_demo_fixtures.py

`--dry-run`으로 LLM을 부르지 않고 결정적 부분만 확인할 수 있다.

세 필드의 출처가 서로 다르다.

| 필드 | 출처 | 키 필요 |
|---|---|---|
| `파싱결과` | `llm.parse_with_llm` | 필요 |
| `심사결과` | `core.screen_loan` — **결정적 함수** | 불필요 |
| `안내문` | `llm.generate_guidance` | 필요 |

`심사결과`가 예전에는 Agent 2의 서술이었다. 그 에이전트를 없앴으므로(ADR-030) 이제
결정적 판정을 사람이 읽을 형태로 옮긴다. 데모 화면의 「판정 근거 원문 보기」가 이
값을 보여주는데, **거기 LLM 문장이 아니라 규칙의 산출물이 있는 것이 사실에 맞고**
이 서비스가 주장하는 경계를 화면에서 그대로 보여준다.
"""
import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loan_agent import core  # noqa: E402

FIXTURE_PATH = ROOT / "loan_agent" / "demo_fixtures.json"


def render_decision(screen: dict) -> str:
    """결정적 판정을 사람이 읽는 문장으로 옮긴다. 여기서 새로 계산하는 값은 없다."""
    lines = [
        f"최종 판정: {screen['판정']}",
        "",
        f"상환능력: {screen['상환능력']}  (DSR {screen['DSR']:.3f})"
        if screen.get("DSR") is not None
        else f"상환능력: {screen['상환능력']}  (DSR 산출 불가 — 연소득 0)",
        "",
        "월상환액 추정",
        f"  기존부채 {screen['월상환액']['기존부채']:,}원"
        f" + 신규대출 {screen['월상환액']['신규대출']:,}원"
        f" = 합계 {screen['월상환액']['합계']:,}원",
        "",
        f"적격 상품 {len(screen['적격상품'])}건",
    ]
    for p in screen["적격상품"][:5]:
        lines.append(f"  · {p['상품코드']} {p['상품명']} ({p['은행']})")

    if screen.get("부적격사유"):
        lines += ["", "부적격 사유"]
        for code, reasons in list(screen["부적격사유"].items())[:5]:
            lines.append(f"  · {code}: {', '.join(reasons)}")

    lines += [
        "",
        "이 판정은 CSV 하드규칙 기반 결정적 함수(screen_loan)가 산출했다.",
        "같은 입력은 언제나 같은 결과를 낸다. LLM은 이 값을 만들지도 바꾸지도 않는다.",
    ]
    return "\n".join(lines)


def build_case(case: dict, api_key: str | None) -> dict:
    from loan_agent import decision

    text = case["input"]
    rule = core.rule_based_parse(text)

    llm_parsed = None
    if api_key:
        from loan_agent import llm
        llm_parsed = llm.parse_with_llm(text, api_key)

    # 실제 흐름을 그대로 재현한다. parsing-preview가 두 후보를 내놓고 사람이 확정한 뒤에야
    # 심사가 돈다(ADR-029). 녹화본은 그 확정 이후를 담아야 하므로, 불일치한 필드는 규칙
    # 파서 값을 쓴다 — 사람이 화면에서 고르는 자리를 녹화가 대신하는 것이다.
    #
    # 이 처리가 필요하다는 것 자체가 경계 검증의 증거다. 실제로 「계약직 소액」 케이스에서
    # LLM이 "부채 200만원"을 200,000으로, "500만원"을 500,000으로 읽었다 — 10배 오차이고,
    # 두 파서를 나란히 세우지 않았다면 그대로 녹화되어 데모에 실렸을 값이다.
    mismatched = []
    parsed = dict(rule)
    if llm_parsed:
        for field in ("월소득", "부채", "신용등급", "희망금액", "직장유형", "담보보유"):
            if llm_parsed.get(field) != rule.get(field):
                mismatched.append(field)

    screen = core.screen_loan(parsed)
    decided = decision.decide(
        monthly_income=parsed["월소득"],
        existing_debt=parsed.get("부채", 0),
        credit_grade=parsed["신용등급"],
        requested_amount=parsed["희망금액"],
        employment_type=parsed.get("직장유형", "제한없음"),
        collateral_owned=bool(parsed.get("담보보유", False)),
    )

    guidance, usage = "", None
    if api_key:
        from loan_agent import llm
        result = asyncio.run(
            llm.generate_guidance(
                {
                    # 워커와 같은 규칙 — 사용자용 문장에는 한글 어휘를 넣는다(ADR-012).
                    "verdict": decision.VERDICT_LABEL.get(decided["verdict"], decided["verdict"]),
                    "repayment_band": decision.BAND_LABEL.get(
                        decided["repayment_band"], decided["repayment_band"]),
                    "dsr": decided["dsr"],
                    "recommendations": [r["reason_codes"] for r in decided["recommendations"]],
                },
                api_key=api_key,
            )
        )
        guidance = result.get("text") or ""
        if core.DISCLAIMER not in guidance:
            guidance = f"{guidance}\n\n{core.DISCLAIMER}"
        raw = result.get("usage")
        # 사용량은 객체로 오므로 dict로 굳혀 저장한다. 문자열로 굳히면 읽는 쪽이
        # 다시 파싱해야 하고, 그 파싱이 조용히 실패하면 비용 표시가 사라진다.
        if raw is not None:
            usage = {
                "prompt_tokens": getattr(raw, "prompt_tokens", None),
                "completion_tokens": getattr(raw, "completion_tokens", None),
                "total_tokens": getattr(raw, "total_tokens", None),
            }

    return {
        "name": case["name"],
        "input": text,
        "expected": case["expected"],
        "parse_check": {
            "llm_candidate": llm_parsed,
            "rule_candidate": rule,
            "mismatched_fields": mismatched,
            "confirmed": "rule" if mismatched else "agreed",
        },
        "result": {
            "파싱결과": json.dumps(parsed, ensure_ascii=False),
            "심사결과": render_decision(screen),
            "안내문": guidance,
            "usage": usage,
        },
    }


def _model_name() -> str:
    """모델명은 LLM 계층이 안다. core에는 LLM을 아는 코드가 없다."""
    from loan_agent import llm
    return llm.get_model_name()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM을 부르지 않는다. 결정적 부분만 만들어 형상을 확인한다.")
    args = ap.parse_args()

    api_key = None if args.dry_run else os.getenv("OPENAI_API_KEY")
    if not args.dry_run and not api_key:
        print("OPENAI_API_KEY가 없다. 오너 키로 실행하거나 --dry-run을 쓴다.", file=sys.stderr)
        return 1

    cases = list(core.TEST_CASES) + list(core.EDGE_CASES)
    built = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['name']}", file=sys.stderr)
        built.append(build_case(case, api_key))

    payload = {
        "generated_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "model": _model_name() if api_key else "dry-run",
        "note": "사전 녹화된 데모 결과. 방문자는 토큰 소모 없이 이 결과를 열람한다. "
                "판정은 결정적 함수가 냈고 LLM은 파싱 후보와 안내문만 만들었다.",
        "cases": built,
    }

    if args.dry_run:
        print(json.dumps(payload["cases"][0], ensure_ascii=False, indent=2))
        print("\n--dry-run이라 파일을 쓰지 않았다.", file=sys.stderr)
        return 0

    FIXTURE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"기록: {FIXTURE_PATH.relative_to(ROOT)} ({len(built)}건)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
