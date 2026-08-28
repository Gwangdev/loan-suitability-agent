"""LLM 3-Agent 출력 품질 평가 하네스 (API 키·토큰 불필요).

사전 녹화된 3-Agent 출력(demo_fixtures.json)을 결정적 정답(screen_loan)과
대조해 정량 채점한다. LLM을 재호출하지 않으므로 비용 0·완전 재현 가능하며, CI에서도 돌릴 수 있다.
"안내문이 판정과 어긋나지 않는가 / CSV 밖 수치를 지어내지 않는가 / 디스클레이머를 지키는가"처럼
프롬프트 설계의 안전 목표를 지표로 만들어, 프롬프트를 바꿨을 때 품질이 오르내리는지 측정한다.

지표(각 케이스 0/1):
  1. 파싱정확도   — Agent1 파싱 JSON이 규칙기반 정답과 핵심 필드 일치
  2. 판정정합성   — 안내문의 톤/결론이 결정적 판정과 어긋나지 않음
  3. 디스클레이머 — 안내문에 필수 디스클레이머 포함
  4. 추천정합성   — 안내문이 결정적 추천상품(코드)과 일치, '어려움'이면 상품 미추천
  5. 수치근거     — 안내문의 금리·한도·수수료가 CSV/입력에 근거(환각 0)
  6. 조건부표현   — '승인합니다' 같은 확정 표현 없이 조건부 표현 사용
"""
import json
import re

from loan_agent import core

# 확정(단정) 표현 금지 목록 — 조건부 표현을 써야 한다.
FORBIDDEN_DEFINITIVE = ["승인합니다", "대출해드립니다", "대출해 드립니다", "보장합니다", "확정합니다"]

# 채점 지표 순서(리포트 컬럼)
METRICS = ["파싱정확도", "판정정합성", "디스클레이머", "추천정합성", "수치근거", "조건부표현"]

_PRODUCT_CODES = {p["상품코드"] for p in core.PRODUCTS}
EVAL_CASES_PATH = core.BASE_DIR / "loan_agent" / "eval_cases.json"


def _load_supplemental_cases() -> list:
    """경계·적대 입력의 고정 Eval 출력을 읽는다(키·토큰 불필요)."""
    if not EVAL_CASES_PATH.exists():
        return []
    return json.loads(EVAL_CASES_PATH.read_text(encoding="utf-8")).get("cases", [])


def _extract_json(raw: str):
    """Agent 출력에서 JSON 객체만 뽑아 파싱(코드펜스 등 잡텍스트 방어)."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _pcts(text: str) -> set:
    """텍스트에서 퍼센트 값을 float 집합으로."""
    return {float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)}


def _wons(text: str) -> set:
    """텍스트에서 '1,000,000원' 형태 금액을 int 집합으로(콤마 제거)."""
    return {int(x.replace(",", "")) for x in re.findall(r"([\d,]{4,})\s*원", text)}


def score_case(case: dict) -> dict:
    """단일 케이스의 사전 녹화 출력을 결정적 정답과 대조해 지표별 0/1을 매긴다."""
    inp = case.get("input", "")
    expected = case.get("expected")
    result = case.get("result", {}) or {}
    안내 = result.get("안내문") or ""
    파싱_llm = _extract_json(result.get("파싱결과") or "")

    # 결정적 정답
    # 한글 수사처럼 규칙 파서가 아직 해석하지 못하는 표현은 케이스에 독립적으로
    # 검토한 구조화 정답을 함께 저장한다. 그 밖의 케이스는 기존 규칙 파서를 정답으로 쓴다.
    parsed_gt = case.get("expected_parse") or core.rule_based_parse(inp)
    screen = core.screen_loan(parsed_gt)
    판정 = screen["판정"]
    rec = screen["추천상품"]

    checks = {}
    detail = {}

    # 1. 파싱정확도 — 핵심 필드 일치
    fields = ["월소득", "부채", "신용등급", "희망금액", "직장유형"]
    if not isinstance(파싱_llm, dict):
        checks["파싱정확도"] = False
        detail["파싱정확도"] = "Agent1 출력 JSON 파싱 실패"
    else:
        mismatched = [f for f in fields if 파싱_llm.get(f) != parsed_gt.get(f)]
        checks["파싱정확도"] = not mismatched
        if mismatched:
            detail["파싱정확도"] = f"불일치 필드: {mismatched}"

    # 2. 판정정합성 — 안내문의 결론이 결정적 판정과 어긋나지 않음
    #   주의: '어려운' 같은 단어는 설명 문맥(일부 상품 한도 초과 등)에도 쓰이므로 톤 판별에서 제외하고,
    #   '거절/불가능'처럼 명확히 승인을 부정하는 표현(HARD_REJECT)만 모순으로 본다.
    missing = core.missing_required_fields(parsed_gt)
    HARD_REJECT = ["거절", "불가능", "승인 불가", "승인이 불가"]
    hard = any(h in 안내 for h in HARD_REJECT)
    if missing:
        ok = "승인" not in 안내 and any(label in 안내 for label in missing)
    elif 판정 == "승인가능":
        ok = ("승인" in 안내) and not hard
    elif 판정 == "상담필요":
        ok = any(k in 안내 for k in ["상담", "보완", "확인"]) and not hard
    else:  # 어려움 — 솔직한 부정 결론이 있어야 함
        ok = any(k in 안내 for k in ["어려", "승인이 어렵"])
    checks["판정정합성"] = ok
    if not ok:
        detail["판정정합성"] = (
            f"필수정보 누락={missing} 인데 안내문 결론이 불일치"
            if missing else f"판정={판정} 인데 안내문 결론이 불일치"
        )

    # 3. 디스클레이머 — 공백 정규화 후 부분일치
    def _norm(s):
        return re.sub(r"\s+", " ", s).strip()
    checks["디스클레이머"] = _norm(core.DISCLAIMER) in _norm(안내)
    if not checks["디스클레이머"]:
        detail["디스클레이머"] = "필수 디스클레이머 누락"

    # 4. 추천정합성
    if missing:
        cited = [c for c in _PRODUCT_CODES if c in 안내]
        checks["추천정합성"] = not cited
        if cited:
            detail["추천정합성"] = f"필수정보 누락인데 상품코드 언급: {cited}"
    elif rec is not None:
        code = rec["상품코드"]
        checks["추천정합성"] = code in 안내
        if not checks["추천정합성"]:
            detail["추천정합성"] = f"추천상품 코드 {code} 미언급"
    else:  # 어려움 → 상품 추천 금지
        cited = [c for c in _PRODUCT_CODES if c in 안내]
        checks["추천정합성"] = not cited
        if cited:
            detail["추천정합성"] = f"'어려움'인데 상품코드 언급: {cited}"

    # 5. 수치근거(환각 0) — 안내문의 %·금액이 CSV/입력에 근거
    allowed_pct, allowed_won = set(), set()
    allowed_won.update(v for v in [parsed_gt.get("월소득"), parsed_gt.get("부채"),
                                   parsed_gt.get("희망금액")] if v)
    if rec is not None:
        lo, hi = rec["금리범위"].replace("%", "").split("~")
        allowed_pct.update({float(lo), float(hi)})
        allowed_pct.add(rec.get("중도상환수수료"))
        allowed_won.add(rec["최대한도"])
    if screen.get("DSR") is not None:
        allowed_pct.add(round(screen["DSR"] * 100, 1))
    allowed_pct.discard(None)
    bad_pct = {p for p in _pcts(안내) if p not in allowed_pct}
    bad_won = {w for w in _wons(안내) if w not in allowed_won}
    checks["수치근거"] = not bad_pct and not bad_won
    if bad_pct or bad_won:
        detail["수치근거"] = f"근거없는 수치 %={sorted(bad_pct)} 금액={sorted(bad_won)}"

    # 6. 조건부표현 — 확정 단정 표현 금지
    hit = [w for w in FORBIDDEN_DEFINITIVE if w in 안내]
    checks["조건부표현"] = not hit
    if hit:
        detail["조건부표현"] = f"확정 표현 사용: {hit}"

    passed = sum(1 for m in METRICS if checks.get(m))
    return {
        "name": case.get("name", "?"),
        "expected": expected,
        "판정": 판정,
        "checks": checks,
        "detail": detail,
        "score": passed,
        "max": len(METRICS),
    }


def run_eval(fixtures: dict = None) -> dict:
    """전체 케이스를 채점해 집계 리포트를 반환한다."""
    if fixtures is None:
        fixtures = core.load_demo_fixtures()
        fixtures = {**fixtures, "cases": fixtures.get("cases", []) + _load_supplemental_cases()}
    cases = fixtures.get("cases", [])
    scored = [score_case(c) for c in cases]
    n = len(scored)
    per_metric = {m: sum(1 for s in scored if s["checks"].get(m)) for m in METRICS}
    total = sum(s["score"] for s in scored)
    total_max = n * len(METRICS)
    return {
        "cases": scored,
        "n": n,
        "per_metric": per_metric,
        "total": total,
        "total_max": total_max,
        "pass_rate": round(total / total_max, 3) if total_max else 0.0,
        "model": fixtures.get("model"),
        "generated_at": fixtures.get("generated_at"),
    }


def run_eval_selftest(fixtures: dict = None) -> bool:
    """평가 하네스를 실행해 표로 출력한다(키 불필요). 전 지표 통과 시 True."""
    report = run_eval(fixtures)
    print("=" * 72)
    print("LLM 3-Agent 출력 품질 평가 (사전 녹화 출력 채점 · API 비용 0)")
    print(f"모델: {report['model']}  생성: {report['generated_at']}")
    print("=" * 72)
    header = "케이스".ljust(16) + "".join(m[:6].rjust(8) for m in METRICS) + "   점수"
    print(header)
    print("-" * 72)
    for s in report["cases"]:
        row = s["name"][:15].ljust(16)
        row += "".join(("✅" if s["checks"].get(m) else "❌").rjust(8) for m in METRICS)
        row += f"   {s['score']}/{s['max']}"
        print(row)
        for m, msg in s["detail"].items():
            print(f"      └ {m}: {msg}")
    print("-" * 72)
    print("지표별 통과:", ", ".join(f"{m} {report['per_metric'][m]}/{report['n']}" for m in METRICS))
    print(f"총점: {report['total']}/{report['total_max']}  (통과율 {report['pass_rate']*100:.1f}%)")
    print("=" * 72)
    return report["total"] == report["total_max"]


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_eval_selftest() else 1)
