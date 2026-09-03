"""대출 적합성 심사 — Streamlit 프론트엔드.
작성자 : 원광식

실행: streamlit run loan_agent/app.py  (프로젝트 루트에서 실행 권장)

심사 로직은 loan_agent/core.py, LLM 프롬프트는 loan_agent/llm.py에 있고 이 파일은
그 위에 UI만 얹는다. 로직을 이 파일에 다시 옮겨 적지 않는다.

디자인 토큰(색상·타이포·라운드·컴포넌트)은 static/apple.css에 있고 _load_css()가
한 번만 읽어 주입한다. 원래 별도 디자인 명세 파일을 참고했으나 저장소에 포함하지
않으므로 그 참조는 제거했다.
Streamlit 기본 크롬(햄버거 메뉴·헤더·"Made with Streamlit" 푸터)을 감추고
실제 제품 웹앱처럼 보이도록 히어로·카드·푸터 구조로 재구성했다.
"""
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import json
import os
import re
import sys
import time
import uuid

import httpx

# Streamlit Cloud는 `streamlit run loan_agent/app.py`로 실행하며, 이때 리포 루트가
#   sys.path에 포함되지 않아 `from loan_agent import core`가 ModuleNotFoundError로 실패한다
#   (로컬 `python -m streamlit`은 CWD를 자동 추가하므로 문제없다). 실행 방식과 무관하게 동작하도록
#   이 파일의 상위 폴더(=리포 루트)를 sys.path에 추가한다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

# .env 외에 st.secrets(.streamlit/secrets.toml)로도 키를 줄 수 있게 지원.
# secrets.toml이 아예 없으면 st.secrets 접근 시 예외가 나므로 조용히 무시한다.
try:
    if "OPENAI_API_KEY" in st.secrets and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    if "OPENAI_MODEL_NAME" in st.secrets and not os.getenv("OPENAI_MODEL_NAME"):
        os.environ["OPENAI_MODEL_NAME"] = st.secrets["OPENAI_MODEL_NAME"]
except Exception:
    pass

from loan_agent import core  # noqa: E402  (secrets 반영 이후에 import)

# Compose에서는 서비스 이름 app으로, 로컬에서는 같은 포트의 Uvicorn으로 접속한다. 화면이
# 판정을 직접 계산하지 않고 이 접속점만 알게 해야 UI → API → DB 경계가 실제 요청 경로가 된다.
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

TOKEN_INPUT_USD_PER_MILLION = Decimal("0.15")
TOKEN_OUTPUT_USD_PER_MILLION = Decimal("0.60")
TOKEN_PRICE_EFFECTIVE_DATE = "2026-08-28"
TOKEN_PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4o-mini"

st.set_page_config(
    page_title="대출 적합성 심사 | 데모", page_icon="🏦", layout="wide",
    # "expanded"로 두면 좁은 화면에서 사이드바가 본문을 덮은 채로 첫 화면이 뜬다.
    # "auto"는 넓은 화면에서 펼치고 좁은 화면에서 접으므로, apple.css가 데스크톱에만
    # 고정 규칙을 거는 것과 짝이 맞는다.
    initial_sidebar_state="auto",
)

# 서버 상한을 넘긴 응답이 도착할 시간. 상한 초과를 기록하고 503을 직렬화하는 데
# 드는 시간만 있으면 되므로 짧게 잡는다.
CLIENT_TIMEOUT_MARGIN_SEC = 10

BADGE_COLOR = {"승인가능": "#1f9d55", "상담필요": "#d97706", "어려움": "#dc2626"}

# 안내문 생성 대기 시간이 길어 화면이 답답해지는 문제를 반영한다.
#   안내문 생성이 수 초 걸리므로, 대기 중 화면이 멈춘 것처럼 보이지 않도록
#   이 팁들을 몇 초 간격으로 돌려 유용한 정보를 제공한다(교육용 데모라 개념 설명 위주).
WAIT_TIPS = [
    "💡 DSR(총부채원리금상환비율)은 '연간 원리금상환액 ÷ 연소득'으로, 낮을수록 상환 여력이 큽니다(은행권 규제 상한 40%).",
    "💡 신용등급은 숫자가 낮을수록 우량합니다(1등급이 가장 우량).",
    "💡 판정은 LLM이 아니라 CSV 하드규칙 기반의 결정적 로직이 내립니다 — 재현성 있는 안전장치예요.",
    "💡 담보를 제공하면 저신용 구간에서도 적격 상품이 생길 수 있습니다.",
    "💡 같은 이름의 상품이 여러 은행에 있어, 안내문은 상품코드·은행명을 함께 표기합니다.",
    "💡 안내문 마지막의 디스클레이머는 규제 통제를 위해 항상 강제 삽입됩니다.",
]



@lru_cache(maxsize=1)
def _load_css() -> str:
    """스타일시트를 한 번만 읽는다. 파일이 없으면 화면을 죽이지 않고 무스타일로 뜬다."""
    path = Path(__file__).resolve().parent / "static" / "apple.css"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _inject_apple_css():
    """화면 스타일을 주입한다.

    값은 코드가 아니라 `static/apple.css`에 있다. 색상·간격·타이포는 화면 로직과
    다른 이유로 바뀌므로 같은 파일에 두면 한쪽을 고칠 때마다 다른 쪽 diff를 읽어야
    한다. 읽기는 한 번만 하고 프로세스 수명 동안 재사용한다.
    """
    st.markdown(f"<style>{_load_css()}</style>", unsafe_allow_html=True)


def _parse_llm_json(raw: str):
    """LLM 파서 출력에서 JSON 부분만 뽑아 파싱(코드펜스 등 잡텍스트 방어)."""
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


def _friendly_error_message(e: Exception) -> str:
    """자주 나오는 OpenAI/네트워크 오류를 사람이 이해하기 쉬운 문장으로 바꾼다."""
    text = str(e)
    if "insufficient_quota" in text or "exceeded your current quota" in text:
        return "OpenAI API 사용 한도(크레딧)가 소진되었습니다. 결제 정보를 확인하거나 크레딧을 충전한 뒤 다시 시도해주세요."
    if "invalid_api_key" in text or "Incorrect API key" in text or "AuthenticationError" in text:
        return "API 키가 올바르지 않습니다. .env 파일의 OPENAI_API_KEY를 확인해주세요."
    if "rate_limit" in text.lower():
        return "요청이 너무 많아 일시적으로 제한되었습니다. 잠시 후 다시 시도해주세요."
    if "timeout" in text.lower() or "Connection" in text:
        return "네트워크 연결에 문제가 있어 응답을 받지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해주세요."
    return "파이프라인 실행 중 예상치 못한 오류가 발생했습니다."


PARSED_FIELD_LABELS = {
    "월소득": ("월 소득", "원"),
    "부채": ("부채", "원"),
    "신용등급": ("신용등급", "등급"),
    "희망금액": ("희망 대출금액", "원"),
    "직장유형": ("직장 형태", ""),
    "담보보유": ("담보 제공 여부", ""),
}

def _render_parsed_info(parsed: dict):
    """파싱 결과를 원본 JSON 대신 사람이 읽기 쉬운 표로 보여준다."""
    rows = []
    for key, (label, unit) in PARSED_FIELD_LABELS.items():
        if key not in parsed:
            continue
        value = parsed[key]
        if key == "담보보유":
            display = "예" if value else "아니오"
        elif unit == "원" and isinstance(value, (int, float)):
            display = f"{value:,.0f}{unit}"
        elif unit == "등급" and isinstance(value, (int, float)):
            display = f"{value}{unit}"
        else:
            display = str(value)
        rows.append({"항목": label, "값": display})
    st.table(rows)


def _render_ineligible_reasons(reasons: dict):
    """상품별 부적격 사유를 JSON이 아니라 읽기 쉬운 목록으로 보여준다."""
    if not reasons:
        st.write("모든 상품이 조건을 충족합니다.")
        return
    for product, reason_list in reasons.items():
        st.markdown(f"**{product}**")
        for r in reason_list:
            st.markdown(f"- {r}")


def _withheld_message(payload: dict) -> str:
    """안내문이 공개되지 않은 이유를 상태별로 알려준다."""
    status = payload.get("status")
    if status == "REVIEW_REQUIRED":
        failed = [k for k, v in (payload.get("eval_result") or {}).items() if v is False]
        detail = f" (미달 지표: {', '.join(failed)})" if failed else ""
        return f"생성된 안내문이 품질 검사를 통과하지 못해 공개하지 않았습니다{detail}. 다시 시도해보세요."
    if status == "FAILED":
        return "안내문 생성이 실패했습니다. 잠시 후 다시 시도해주세요."
    return "안내문이 아직 준비되지 않았습니다."


def _badge_html(verdict: str) -> str:
    color = BADGE_COLOR.get(verdict, "#6b7280")
    return f"<span class='apple-badge' style='background:{color};'>{verdict}</span>"


def _usage_value(usage, field: str):
    if isinstance(usage, dict):
        return usage.get(field)
    return getattr(usage, field, None)


def _usage_cost_usd(usage):
    input_tokens = _usage_value(usage, "prompt_tokens")
    output_tokens = _usage_value(usage, "completion_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    return (
        Decimal(str(input_tokens)) * TOKEN_INPUT_USD_PER_MILLION
        + Decimal(str(output_tokens)) * TOKEN_OUTPUT_USD_PER_MILLION
    ) / Decimal(1_000_000)


def _render_usage_cost(out: dict):
    usage = out.get("usage")
    cost = _usage_cost_usd(usage)
    if cost is None:
        return
    input_tokens = _usage_value(usage, "prompt_tokens")
    output_tokens = _usage_value(usage, "completion_tokens")
    st.caption(
        f"이번 안내문 실행 토큰: 입력 {input_tokens:,} · 출력 {output_tokens:,} · "
        f"추정 API 비용 ${cost:.6f}"
    )
    st.caption(
        f"단가 기준일 {TOKEN_PRICE_EFFECTIVE_DATE} · 입력 ${TOKEN_INPUT_USD_PER_MILLION}/1M · "
        f"출력 ${TOKEN_OUTPUT_USD_PER_MILLION}/1M · "
        f"[공식 모델 문서]({TOKEN_PRICE_SOURCE}) · 캐시 할인 미반영"
    )


def _render_result(out: dict, screen: dict = None):
    # screen을 인자로 받으면(구조화 폼 기준 결정적 판정) 그것을 권위값으로 쓴다.
    #   → 화면 배지·적격상품이 LLM 재파싱이 아니라 '사용자가 확정한 구조화 입력'과 일치(A1 이중경로 해소).
    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 1</div>", unsafe_allow_html=True)
        st.subheader("입력 해석 — 규칙 파서 · LLM 파서 대조")
        parsed = _parse_llm_json(out.get("파싱결과"))
        if parsed:
            _render_parsed_info(parsed)
        else:
            st.write(out.get("파싱결과") or "(파싱 결과 없음)")

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 2</div>", unsafe_allow_html=True)
        st.subheader("적합성 판정 — 결정적 규칙 (LLM 미개입)")
        if parsed is not None or screen is not None:
            if screen is None:
                screen = core.screen_loan(parsed)
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(_badge_html(screen["판정"]), unsafe_allow_html=True)
            with col2:
                # 화면 지표를 간이 DTI → 실제 DSR로 교체.
                #   월상환액 내역(기존/신규)과 가정값을 함께 보여 근거를 투명하게 노출한다.
                dsr_pct = f"{screen['DSR'] * 100:.1f}%" if screen["DSR"] is not None else "확인 불가"
                st.write(f"상환능력: **{screen['상환능력']}**  ·  DSR(연간 원리금상환액÷연소득): **{dsr_pct}**")
                _mp = screen["월상환액"]
                st.caption(
                    f"※ 월상환액(가정 연 {_mp['가정']['연금리']*100:.0f}%·{_mp['가정']['기간개월']}개월, 원리금균등): "
                    f"기존부채 {_mp['기존부채']:,}원 + 신규대출 {_mp['신규대출']:,}원 = 합계 {_mp['합계']:,}원. "
                    "판정 밴드: DSR ≤30% 여유 / ≤40% 보통(은행권 규제 상한) / >40% 부족."
                )

            if screen["판정"] == "상담필요":
                st.caption("ℹ️ 상환 여력이 넉넉하지 않아(DSR 보통 구간) 은행 상담을 통해 조건을 확인해보시는 것이 좋습니다.")

            if screen["추천상품"]:
                best = screen["추천상품"]
                st.success(
                    f"추천 상품: **{best['상품코드']} {best['상품명']}** ({best['은행']}) · "
                    f"금리 {best['금리범위']} · 한도 {best['최대한도']:,}원"
                )
                # 최저금리 단일 기준 대신 금리·승인여유·중도상환수수료를
                #   함께 반영한 상위 3개 랭킹을 비교표로 시현(§docs C-2).
                if len(screen.get("추천후보", [])) > 1:
                    with st.expander("대안 상품 비교 (상위 3위 · 금리+승인여유+중도상환 기준)"):
                        st.dataframe(
                            # 한 칸이 비어도 화면 전체가 죽지 않게 get으로 읽는다. 값이
                            # 없는 것과 페이지가 사라지는 것은 사용자에게 전혀 다른 일이다.
                            [{"순위": i, "상품코드": c.get("상품코드"), "상품명": c.get("상품명"),
                              "은행": c.get("은행"), "금리범위": c.get("금리범위"),
                              "승인여유마진": c.get("승인여유마진"), "중도상환수수료(%)": c.get("중도상환수수료"),
                              "상환방식": c.get("상환방식"), "금리방식": c.get("금리방식")}
                             for i, c in enumerate(screen["추천후보"], 1)],
                            width="stretch", hide_index=True,
                        )

            # 실제 심사 경로에서 오는 목록은 API가 저장한 상위 3건이다(ADR-025).
            # 그것을 「적격 상품 목록」이라 부르면 화면이 없는 사실을 말하게 된다.
            # 설계는 그대로 두고 화면이 범위를 정직하게 밝히는 쪽으로 닫는다.
            상위3 = screen.get("목록범위") == "상위3"
            if screen["판정"] != "어려움":
                if screen["적격상품"]:
                    st.write(
                        "추천 상위 3건 (상품코드·은행 포함):" if 상위3
                        else "적격 상품 목록 (상품코드·은행 포함):"
                    )
                    st.dataframe(screen["적격상품"], width="stretch", hide_index=True)
                else:
                    st.write("추천할 상품이 없습니다." if 상위3 else "적격 상품이 없습니다.")
            elif screen["적격상품"]:
                st.caption("규정만 보면 통과하는 상품이 있으나, 상환능력이 부족해 추천하지 않습니다.")

            with st.expander("부적격 사유 보기"):
                # 사유가 비어 있을 때 「모두 충족」이라고 쓰면 정보 없음과 해당 없음이
                # 한 문장으로 뭉개진다. 상위 3건만 저장하는 경로는 탈락 상품 자체를
                # 들고 있지 않으므로 그렇게 말한다.
                if 상위3 and not screen["부적격사유"]:
                    st.write("이 경로에서는 제공되지 않습니다 — API가 추천 상위 3건만 저장하므로 "
                             "탈락 상품과 그 사유가 남지 않습니다.")
                else:
                    _render_ineligible_reasons(screen["부적격사유"])
        else:
            st.warning("파싱 결과를 JSON으로 해석하지 못해, 결정적 심사 결과(배지·적격상품)를 계산할 수 없습니다.")

        if out.get("심사결과"):
            with st.expander("판정 근거 원문 보기"):
                st.write(out["심사결과"])

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 3</div>", unsafe_allow_html=True)
        st.subheader("고객 안내문 — LLM 생성 · 공개 전 검사 통과분")
        if out.get("안내문"):
            st.markdown(out["안내문"])
            st.download_button(
                "안내문 다운로드 (.txt)",
                data=out["안내문"],
                file_name="대출심사_안내문.txt",
                mime="text/plain",
            )
            _render_usage_cost(out)
        else:
            # 키 없이 결정적 심사만 돌린 경우 — 위 STEP 2가 판정을 이미 보여준다.
            st.info("LLM 안내문은 사이드바에 **OpenAI 키**를 입력하면 생성됩니다. "
                    "(현재는 키 없이 **결정적 심사 결과**만 표시)")


# 하이브리드 입력 — 자유서술을 파싱해 구조화 폼을 채우고, 폼을 진실의 원천으로 삼는다.
JOB_OPTIONS = ["제한없음", "정규직", "계약직"]


def _fill_form_from_text():
    """자유 서술을 규칙기반 파싱해 구조화 폼 필드를 채운다(키 불필요)."""
    p = core.rule_based_parse(st.session_state.get("customer_input", ""))
    st.session_state.f_income = int(p.get("월소득") or 0)
    st.session_state.f_debt = int(p.get("부채") or 0)
    g = p.get("신용등급", 99)
    st.session_state.f_grade = 0 if (not g or g >= 99) else int(g)   # 0 = 미입력
    st.session_state.f_amount = int(p.get("희망금액") or 0)
    job = p.get("직장유형", "제한없음")
    st.session_state.f_job = job if job in JOB_OPTIONS else "제한없음"
    st.session_state.f_collateral = bool(p.get("담보보유"))


def _form_customer() -> dict:
    """현재 폼 값 → 구조화 고객 dict. 신용등급 0(미입력)은 sentinel 99로."""
    g = int(st.session_state.get("f_grade", 0) or 0)
    return {
        "월소득": int(st.session_state.get("f_income", 0) or 0),
        "부채": int(st.session_state.get("f_debt", 0) or 0),
        "신용등급": g if g else 99,
        "희망금액": int(st.session_state.get("f_amount", 0) or 0),
        "직장유형": st.session_state.get("f_job", "제한없음"),
        "담보보유": bool(st.session_state.get("f_collateral", False)),
    }


def _customer_to_nl(c: dict) -> str:
    """구조화 고객 dict → LLM 파이프라인용 표준 자연어 문장(깨끗한 입력으로 파싱 일관성 확보)."""
    return (f"월소득 {c['월소득']}원, 부채 {c['부채']}원, 신용등급 {c['신용등급']}등급, "
            f"희망 대출금액 {c['희망금액']}원, 직장유형 {c['직장유형']}, "
            f"담보 {'보유' if c['담보보유'] else '미보유'}.")


def _submit_assessment(customer: dict) -> dict:
    """확정한 구조화 입력을 API에 보낸다. 멱등 키는 클릭마다 새 심사를 식별한다."""
    payload = {
        "monthly_income": customer["월소득"],
        "existing_debt": customer["부채"],
        "credit_grade": customer["신용등급"],
        "requested_amount": customer["희망금액"],
        "employment_type": customer["직장유형"],
        "collateral_owned": customer["담보보유"],
    }
    response = httpx.post(
        f"{API_BASE_URL}/api/v1/assessments",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def _screen_from_assessment(assessment: dict) -> dict:
    """API의 안정된 영문 계약을 기존 화면 표시용 최소 구조로 바꾼다."""
    labels = {"ELIGIBLE": "승인가능", "CONDITIONAL": "상담필요", "INELIGIBLE": "어려움"}
    bands = {"COMFORTABLE": "여유", "MODERATE": "보통", "STRAINED": "부족"}
    decision = assessment["decision"]
    candidates = [
        {
            "상품코드": row["product_code"],
            "상품명": row["product_name"],
            "은행": row["bank"],
            "금리범위": row["interest_rate_range"],
            "최대한도": row["maximum_limit"],
            "상환방식": row.get("repayment_method"),
            "금리방식": row.get("rate_type"),
            "중도상환수수료": row.get("early_repayment_fee"),
            "승인여유마진": row.get("approval_margin"),
        }
        for row in assessment["recommendations"]
        if row["eligible"]
    ]
    return {
        "판정": labels[decision["verdict"]],
        "상환능력": bands[decision["repayment_band"]],
        "DSR": decision["dsr"],
        "월상환액": decision["monthly_payment"],
        "추천상품": candidates[0] if candidates else None,
        "추천후보": candidates,
        "적격상품": candidates,
        # API는 추천 상위 3건만 저장한다(ADR-025). 탈락 상품과 사유는 이 경로에
        # 존재하지 않으므로 빈 dict가 「모두 충족」이 아니라 「데이터 없음」이라는
        # 것을 화면이 구분할 수 있도록 범위를 함께 넘긴다.
        "부적격사유": {},
        "목록범위": "상위3",
    }


def _fill_input(text: str):
    """예시 케이스 클릭 → 텍스트 채우고 곧바로 구조화 폼까지 자동 채움."""
    st.session_state.customer_input = text
    _fill_form_from_text()


def _reset_input():
    st.session_state.customer_input = ""
    for k in ("last_result", "last_input", "is_demo", "last_screen"):
        st.session_state.pop(k, None)


# 사전 녹화된 결과 로더(캐시) — 방문자가 키·토큰 없이 결과를 열람.
@st.cache_data(show_spinner=False)
def _demo_fixtures():
    return core.load_demo_fixtures()


def _load_demo(index: int):
    """데모 케이스의 사전 녹화 결과를 결과 슬롯에 실어, 파이프라인 실행 없이 렌더한다(토큰 0)."""
    fx = _demo_fixtures()
    cases = fx.get("cases", [])
    if 0 <= index < len(cases):
        case = cases[index]
        st.session_state.last_result = case["result"]
        st.session_state.last_input = case["input"]
        st.session_state.is_demo = True
        st.session_state.last_screen = None  # 데모는 픽스처 파싱에서 screen 재계산


# 방문자가 자기 키를 쓰더라도 무제한 호출로 지갑이 새지 않도록
#   하는 상한(§docs 개선계획 C-4). 공개 데모 기준의 보수적 기본값.
MAX_INPUT_CHARS = 2000        # 입력 길이 상한 → 토큰 폭증 차단
MAX_RUNS_PER_SESSION = 10     # 세션당 실제 실행(LLM) 횟수 상한
COOLDOWN_SEC = 5              # 연속 실행 최소 간격(쿨다운)


def _effective_api_key():
    """방문자가 입력한 키만 세션 메모리에서 꺼낸다.

    서버 키는 워커의 비동기 경로 전용이다. UI가 이를 헤더로 넘기면 키 출처에 따른
    실행 주체를 가른 ADR-024 §24-R을 우회하게 되므로 여기서 폴백하지 않는다.
    """
    visitor = (st.session_state.get("visitor_key") or "").strip()
    return visitor or None


def main():
    _inject_apple_css()

    # 문구는 실행 경로를 그대로 적는다. 「3개 Agent가 순차 협업」은 세 부분이 모두
    # 사실과 달랐다 — 코드에 정의된 Agent는 파서와 안내 둘이고(llm.py), 이 화면이
    # 실제로 도는 것은 안내 하나이며(폼 채우기는 core.rule_based_parse), 심사는
    # Agent가 아니라 결정적 함수다(core/decision.py). 3-Agent 파이프라인은 코드에서
    # 삭제됐고 test_assessments.py가 부활을 막고 있는데 화면만 그대로 광고하고 있었다.
    st.markdown("<div class='hero-title'>🏦 대출 상담 의사결정 지원</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='hero-lead'>상담 내용은 <b>규칙 기반 파서</b>가 항목으로 옮기고, "
        "적격 판정과 DSR은 <b>결정적 함수</b>가 계산합니다. "
        "LLM은 <b>확정된 결과를 설명하는 안내문</b>만 씁니다 — 판정·추천·DSR 값에는 닿지 않습니다.</div>",
        unsafe_allow_html=True,
    )

    if "customer_input" not in st.session_state:
        st.session_state.customer_input = ""

    with st.sidebar:
        # 공개 데모용 — 방문자가 자기 OpenAI 키로 직접 실행.
        #   키는 이 세션 메모리에만 보관되고 저장/전송되지 않는다.
        st.text_input(
            "OpenAI API 키 (직접 실행용)", key="visitor_key", type="password",
            placeholder="sk-... (선택 · 세션에만 보관)",
            help="입력한 키는 이 브라우저 세션에만 보관되며 서버에 저장되지 않습니다. "
                 "키 없이도 아래 '📽️ 토큰 없이 데모 보기'는 이용할 수 있습니다.",
        )
        st.divider()

        st.caption("예시 케이스 (클릭 시 입력창에 채워짐)")
        for tc in core.TEST_CASES:
            st.button(
                tc["name"], key=f"tc_{tc['name']}", width="stretch",
                on_click=_fill_input, args=(tc["input"],),
            )
        for tc in core.EDGE_CASES:
            st.button(
                tc["name"], key=f"ec_{tc['name']}", width="stretch",
                on_click=_fill_input, args=(tc["input"],),
            )

        # 키가 없는 방문자도 '입력 → 실제 출력'을
        #   토큰 소모 0으로 볼 수 있는 사전 녹화 결과 버튼.
        demo_cases = _demo_fixtures().get("cases", [])
        if demo_cases:
            st.divider()
            st.caption("📽️ 토큰 없이 데모 보기 (사전 녹화 결과 · 키 불필요)")
            for i, dc in enumerate(demo_cases):
                st.button(
                    f"▶ {dc['name']}", key=f"demo_{i}", width="stretch",
                    on_click=_load_demo, args=(i,),
                )

    # 실제 실행에 쓸 키(방문자 키 우선, 없으면 서버 키). 데모는 키와 무관.
    api_key = _effective_api_key()
    if not api_key:
        st.info(
            "🔑 직접 실행하려면 사이드바에 **본인 OpenAI 키**를 입력하세요(세션에만 보관). "
            "키가 없어도 사이드바의 **📽️ 토큰 없이 데모 보기**로 실제 결과를 볼 수 있습니다."
        )

    # 하이브리드 입력: ①자유서술 → ②'채우기'로 폼 자동채움 → ③부족분 보완 → ④폼으로 제출.
    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>1. 자유 서술 (선택)</div>", unsafe_allow_html=True)
        st.text_area(
            "고객 상담 내용", key="customer_input", height=90, label_visibility="collapsed",
            max_chars=MAX_INPUT_CHARS,  # [비용 보호] 입력 길이 상한 → 토큰 폭증 차단
            placeholder="예) 월급 350만원 받는 정규직이고 부채는 800만원 있어요. 신용등급 3등급이고 2000만원 대출받고 싶어요.",
        )
        st.button("📝 자연어에서 아래 항목 채우기", on_click=_fill_form_from_text)

        st.markdown("<div class='card-eyebrow' style='margin-top:14px;'>2. 항목 확인·보완 (제출 기준)</div>",
                    unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input("월 소득 (원)", min_value=0, step=100_000, key="f_income")
            st.number_input("희망 대출금액 (원)", min_value=0, step=1_000_000, key="f_amount")
        with c2:
            st.number_input("부채 (원)", min_value=0, step=100_000, key="f_debt")
            st.number_input("신용등급 (1~10, 0=미입력)", min_value=0, max_value=10, step=1, key="f_grade")
        with c3:
            st.selectbox("직장 형태", JOB_OPTIONS, key="f_job")
            st.checkbox("담보 제공 가능", key="f_collateral")

        customer = _form_customer()
        missing = core.missing_required_fields(customer)
        if missing:
            st.error("보완이 필요한 항목: " + ", ".join(f"**{m}**" for m in missing)
                     + " — 자유 서술로 채우거나 위 항목을 직접 입력하세요.")

        run_count = st.session_state.get("run_count", 0)
        quota_left = MAX_RUNS_PER_SESSION - run_count
        col_a, col_b = st.columns(2)
        with col_a:
            screen_clicked = st.button("결정적 심사 (키 불필요)", disabled=bool(missing))
        with col_b:
            run_clicked = st.button("AI 안내문까지 생성 (키 필요)", type="primary",
                                    disabled=(bool(missing) or api_key is None or quota_left <= 0))
        st.caption(f"이번 세션 AI 실행 {run_count}/{MAX_RUNS_PER_SESSION}회 · 남은 실행 {max(quota_left, 0)}회")

    # ④-a 결정적 심사만 (키·토큰 0) — 폼이 진실의 원천이므로 배지·판정이 폼과 정확히 일치(A1 해소).
    if screen_clicked and not missing:
        try:
            assessment = _submit_assessment(customer)
            st.session_state.last_result = {"파싱결과": json.dumps(customer, ensure_ascii=False),
                                            "심사결과": None, "안내문": None}
            st.session_state.last_screen = _screen_from_assessment(assessment)
            st.session_state.last_input = _customer_to_nl(customer)
            st.session_state.is_demo = False
        except httpx.HTTPError:
            st.error("심사 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.")

    # ④-b AI 안내문까지 (키 필요) — 심사가 만든 PENDING 행을 app이 동기 실행한다.
    if run_clicked and not missing:
        now = time.monotonic()
        last_ts = st.session_state.get("last_run_ts", 0.0)
        if run_count >= MAX_RUNS_PER_SESSION:
            st.warning(f"이번 세션 실행 한도({MAX_RUNS_PER_SESSION}회)에 도달했습니다. 새로고침 후 다시 시도해주세요.")
        elif now - last_ts < COOLDOWN_SEC:
            st.warning(f"연속 실행을 제한합니다. {COOLDOWN_SEC - int(now - last_ts)}초 후 다시 시도해주세요.")
        else:
            try:
                assessment = _submit_assessment(customer)
                run = httpx.post(
                    f"{API_BASE_URL}/api/v1/assessments/{assessment['assessment_id']}/explanation-runs",
                    headers={"X-OpenAI-API-Key": api_key},
                    # 서버 상한(ADR-022의 200초)보다 바깥 계층이 길어야 한다. 같게 두면
                    # 서버가 상한을 넘겨 503을 만드는 그 순간 클라이언트가 먼저 끊어,
                    # 정작 준비해 둔 503 안내가 화면에 도달하지 못한다.
                    timeout=core.EXPLANATION_RUN_TIMEOUT_SECONDS + CLIENT_TIMEOUT_MARGIN_SEC,
                )
                run.raise_for_status()
                payload = run.json()
                # Eval을 통과하지 못한 안내문은 저장되지 않으므로(ADR-007) 본문이
                # 비어 온다. 그대로 렌더하면 방문자는 토큰을 쓰고도 아무 설명 없는
                # 빈 화면을 본다 — 검증에서 걸렸다는 사실 자체를 알려야 한다.
                if not payload.get("explanation_text"):
                    st.warning(_withheld_message(payload))
                st.session_state.last_result = {
                    "파싱결과": json.dumps(customer, ensure_ascii=False),
                    "심사결과": None,
                    "안내문": payload.get("explanation_text"),
                    "usage": {
                        "prompt_tokens": payload.get("input_tokens"),
                        "completion_tokens": payload.get("output_tokens"),
                    },
                }
                st.session_state.last_screen = _screen_from_assessment(assessment)
                st.session_state.last_input = _customer_to_nl(customer)
                st.session_state.is_demo = False
                st.session_state.run_count = run_count + 1
                st.session_state.last_run_ts = now
            except Exception:
                st.error("⚠️ AI 안내문 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    if st.session_state.get("last_result"):
        # 사전 녹화 결과일 때 명확히 고지(실제 실행과 구분).
        if st.session_state.get("is_demo"):
            fx = _demo_fixtures()
            st.info(
                f"📽️ **사전 녹화된 데모 결과입니다 — 토큰이 전혀 소모되지 않았습니다.** "
                f"실제 파이프라인을 미리 1회 실행해 저장한 입력/출력이며, "
                f"직접 실행하려면 사이드바에 본인 OpenAI 키를 입력하세요. "
                f"(생성 모델: {fx.get('model', 'N/A')})"
            )
        st.caption(f"입력: {st.session_state.get('last_input', '')}")
        _render_result(st.session_state.last_result, screen=st.session_state.get("last_screen"))
        st.button("다시 입력하기", on_click=_reset_input)

    st.markdown(
        "<div class='app-footer'>대출 적합성 심사 · 교육용 데모</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
