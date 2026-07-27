"""대출 적합성 심사 3-Agent 파이프라인 — Streamlit 프론트엔드.
작성자 : 원광식

실행: streamlit run loan_agent/app.py  (프로젝트 루트에서 실행 권장)

모든 심사 로직·프롬프트는 loan_agent/core.py 한 곳에 있고, 이 파일은 그 위에
UI만 얹는다. 로직을 이 파일에 다시 옮겨 적지 않는다.

# [포트폴리오 정리] 원래 별도 디자인 명세 파일을 참고했으나 저장소에는 포함하지
#   않으므로 그 참조를 제거했다. 디자인 토큰은 아래 _inject_apple_css()에 인라인으로
#   모두 정의되어 있어 이 파일만으로 자기완결적이다.
Apple 스타일 디자인 토큰(색상·타이포·라운드·컴포넌트)을 아래 CSS에 직접 정의하고,
Streamlit 기본 크롬(햄버거 메뉴·헤더·"Made with Streamlit" 푸터)을 감추고
실제 제품 웹앱처럼 보이도록 히어로·카드·푸터 구조로 재구성했다.
"""
import asyncio
import json
import os
import queue
import re
import threading
import time

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

st.set_page_config(
    page_title="대출 적합성 심사 | 데모", page_icon="🏦", layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Apple 스타일 디자인 토큰 (인라인 정의) — 색상/타이포/라운드/버튼 그래머
# ---------------------------------------------------------------------------
BADGE_COLOR = {"승인가능": "#1f9d55", "상담필요": "#d97706", "어려움": "#dc2626"}
STAGE_LABEL = {
    "parse": "1/3 정보 파싱 중 (Agent 1)",
    "review": "2/3 심사 판단 중 (Agent 2)",
    "advise": "3/3 안내문 작성 중 (Agent 3)",
}
STAGE_NEXT = {"parse": "review", "review": "advise", "advise": None}

EXAMPLE_KEYWORDS = [
    "월급",
    "부채",
    "신용등급",
    "희망 대출금액",
    "정규직 / 계약직",
    "담보 제공 여부",
]

# [타팀 피드백-1] Agent 2 작동 시간이 길어 프론트엔드 UX가 답답하다는 지적 반영.
#   심사(특히 Agent 2)가 수 초~수십 초 걸리므로, 대기 중 화면이 멈춘 것처럼 보이지 않도록
#   이 팁들을 몇 초 간격으로 돌려 유용한 정보를 제공한다(교육용 데모라 개념 설명 위주).
AGENT_TIPS = [
    "💡 DTI(부채상환비율)는 '기존 부채 ÷ 연소득'으로, 낮을수록 상환 여력이 큽니다.",
    "💡 신용등급은 숫자가 낮을수록 우량합니다(1등급이 가장 우량).",
    "💡 판정은 LLM이 아니라 CSV 하드규칙 기반의 결정적 로직이 내립니다 — 재현성 있는 안전장치예요.",
    "💡 Agent 2는 CoT(단계적 추론)로 부채비율→신용등급→한도→상품선별 순서로 근거를 만듭니다.",
    "💡 담보를 제공하면 저신용 구간에서도 적격 상품이 생길 수 있습니다.",
    "💡 같은 이름의 상품이 여러 은행에 있어, 안내문은 상품코드·은행명을 함께 표기합니다.",
    "💡 안내문 마지막의 디스클레이머는 규제 통제를 위해 항상 강제 삽입됩니다.",
]


def _inject_apple_css():
    st.markdown(
        """
<style>
:root {
  --color-primary: #0066cc;
  --color-primary-focus: #0071e3;
  --color-ink: #1d1d1f;
  --color-ink-muted-80: #333333;
  --color-ink-muted-48: #7a7a7a;
  --color-canvas: #ffffff;
  --color-parchment: #f5f5f7;
  --color-pearl: #fafafc;
  --color-hairline: #e0e0e0;
  --color-divider-soft: #f0f0f0;
  --font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", system-ui, sans-serif;
  --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", system-ui, sans-serif;
  --radius-sm: 8px;
  --radius-md: 11px;
  --radius-lg: 18px;
  --radius-pill: 9999px;
}

/* --- Streamlit 기본 크롬 제거: 실제 제품처럼 보이게 --- */
html, body { margin: 0 !important; padding: 0 !important; }
[data-testid="stAppHeader"],
[data-testid="stToolbar"],
[data-testid="stAppToolbar"],
[data-testid="stMainMenu"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
[data-testid="stDecoration"],
#MainMenu, footer {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  min-height: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
}
[data-testid="stAppViewContainer"] {
  padding-top: 0 !important;
}

/* --- 캔버스 & 컨테이너 --- */
html, body, #root,
[data-testid="stAppViewContainer"],
[data-testid="stApp"],
[data-testid="stMain"],
.stApp {
  background: var(--color-parchment) !important;
}
[data-testid="stMainBlockContainer"] {
  max-width: 900px;
  margin: 0 auto;
  padding-top: 2.5rem;
  padding-bottom: 4rem;
}
[data-testid="stAppViewContainer"], [data-testid="stSidebar"], .stMarkdown, p, span, li, label, div {
  font-family: var(--font-body);
}

/* --- 사이드바: 항상 펼쳐진 상태로 고정(접기 버튼 숨김 + 강제 표시) --- */
[data-testid="stSidebar"] {
  background: var(--color-pearl);
  border-right: 1px solid var(--color-hairline);
  min-width: 260px !important;
  width: 260px !important;
  transform: none !important;
  visibility: visible !important;
  margin-left: 0 !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }
[data-testid="stSidebar"] [data-testid="stMainBlockContainer"] { max-width: none; padding-top: 2rem; }

/* --- 타이포 --- */
h1, h2, h3 {
  font-family: var(--font-display) !important;
  font-weight: 600 !important;
  letter-spacing: -0.028em !important;
  color: var(--color-ink) !important;
}
.hero-title {
  font-family: var(--font-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  font-size: 2.4rem;
  color: var(--color-ink);
  margin-bottom: 4px;
}
.hero-lead {
  font-family: var(--font-body);
  font-weight: 400;
  font-size: 1.05rem;
  color: var(--color-ink-muted-48);
  margin-bottom: 20px;
}
[data-testid="stCaptionContainer"] {
  color: var(--color-ink-muted-48) !important;
  letter-spacing: -0.01em;
}

/* --- 공지 바(디스클레이머) --- */
.notice-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--color-canvas);
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-md);
  padding: 10px 16px;
  margin-bottom: 28px;
  font-size: 12.5px;
  color: var(--color-ink-muted-80);
  letter-spacing: -0.12px;
}

/* --- 버튼 그래머 --- */
[data-testid="stBaseButton-primary"] {
  background: var(--color-primary) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: var(--radius-pill) !important;
  padding: 11px 26px !important;
  font-weight: 400 !important;
  transition: transform .15s ease, background .15s ease;
}
[data-testid="stBaseButton-primary"]:hover { background: var(--color-primary-focus) !important; }
[data-testid="stBaseButton-primary"]:active { transform: scale(0.95); }
[data-testid="stBaseButton-primary"]:disabled {
  background: var(--color-hairline) !important;
  color: var(--color-ink-muted-48) !important;
}
[data-testid="stBaseButton-secondary"] {
  background: transparent !important;
  color: var(--color-ink-muted-48) !important;
  border: 1px solid var(--color-divider-soft) !important;
  border-radius: var(--radius-pill) !important;
  font-weight: 400 !important;
  font-size: 13px !important;
  padding: 6px 14px !important;
  transition: transform .15s ease, color .15s ease, border-color .15s ease;
}
[data-testid="stBaseButton-secondary"]:hover {
  color: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
}
[data-testid="stBaseButton-secondary"]:active { transform: scale(0.95); }

/* --- 입력창 --- */
[data-testid="stTextArea"] textarea {
  border-radius: var(--radius-md) !important;
  border: 1px solid var(--color-hairline) !important;
  font-family: var(--font-body) !important;
  font-size: 16px !important;
  color: var(--color-ink) !important;
  background: var(--color-pearl) !important;
}
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--color-primary) !important;
  box-shadow: 0 0 0 1px var(--color-primary) !important;
}

/* --- 카드 (입력 카드 + 결과 카드 공통) --- */
[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: var(--radius-lg) !important;
  border-color: var(--color-hairline) !important;
  background: var(--color-canvas);
}
.card-eyebrow {
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-primary);
  margin-bottom: 2px;
}

/* --- 예시 키워드 칩 --- */
.apple-chip-row { margin: 2px 0 0 0; line-height: 1.9; }
.apple-chip {
  display: inline-block;
  background: transparent;
  color: var(--color-ink-muted-48);
  border: 1px solid var(--color-divider-soft);
  border-radius: var(--radius-pill);
  padding: 5px 12px;
  margin: 4px 8px 4px 0;
  font-size: 12.5px;
  font-family: var(--font-body);
}

/* --- 판정 배지 --- */
.apple-badge {
  display: inline-block;
  color: #ffffff;
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  font-weight: 600;
  font-size: 15px;
  letter-spacing: -0.01em;
}

/* --- 푸터 --- */
.app-footer {
  margin-top: 56px;
  padding: 24px 4px 8px 4px;
  border-top: 1px solid var(--color-hairline);
  font-size: 11px;
  line-height: 1.5;
  color: var(--color-ink-muted-48);
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _parse_llm_json(raw: str):
    """Agent 1 출력에서 JSON 부분만 뽑아 파싱(코드펜스 등 잡텍스트 방어)."""
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
    """Agent 1 파싱 결과를 원본 JSON 대신 사람이 읽기 쉬운 표로 보여준다."""
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


def _badge_html(verdict: str) -> str:
    color = BADGE_COLOR.get(verdict, "#6b7280")
    return f"<span class='apple-badge' style='background:{color};'>{verdict}</span>"


def _run_pipeline(customer_input: str) -> dict:
    """crewai Task의 callback은 crewai 내부 스레드(ThreadPoolExecutor)에서 실행되므로,
    거기서 Streamlit API(st.status 등)를 직접 부르면 ScriptRunContext가 없어 그 콜백이
    죽어버리고 crewai가 이를 Task Failure로 처리한다. 그래서 콜백은 스레드 안전한
    queue.Queue에만 값을 넣고, 실제 st.status 업데이트는 메인 스레드(여기)에서
    큐를 폴링하며 처리한다."""
    stage_queue: "queue.Queue" = queue.Queue()
    outcome: dict = {}

    def on_stage(stage, output):
        stage_queue.put(stage)

    def worker():
        try:
            outcome["result"] = asyncio.run(
                core.run_service_with_stages(customer_input, on_stage=on_stage)
            )
        except Exception as e:  # noqa: BLE001 - 메인 스레드로 예외를 그대로 전달
            outcome["error"] = e

    status = st.status(STAGE_LABEL["parse"], expanded=True)
    # [타팀 피드백-1] 대기 중 로테이션 팁을 표시할 자리 — Agent 2 대기 체감을 줄인다.
    tip_slot = status.empty()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # [타팀 피드백-1] 팁 로테이션 상태(약 4초마다 다음 팁으로 교체). 기존 큐 폴링 루프에 얹어
    #   추가 스레드·비용 없이 대기 화면에 유용한 정보를 흘려보낸다.
    tip_idx = 0
    next_tip_at = 0.0
    TIP_INTERVAL = 4.0

    while thread.is_alive() or not stage_queue.empty():
        now = time.monotonic()
        if now >= next_tip_at:
            tip_slot.caption(AGENT_TIPS[tip_idx % len(AGENT_TIPS)])
            tip_idx += 1
            next_tip_at = now + TIP_INTERVAL
        try:
            stage = stage_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        status.write(f"완료: {STAGE_LABEL.get(stage, stage)}")
        nxt = STAGE_NEXT.get(stage)
        if nxt:
            status.update(label=STAGE_LABEL[nxt])
    thread.join()
    tip_slot.empty()  # 완료되면 팁 자리를 비운다

    if "error" in outcome:
        status.update(label="오류 발생", state="error")
        raise outcome["error"]

    status.update(label="심사 완료", state="complete", expanded=False)
    return outcome["result"]


def _render_result(out: dict):
    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 1</div>", unsafe_allow_html=True)
        st.subheader("Agent 1 — 파싱 결과")
        parsed = _parse_llm_json(out.get("파싱결과"))
        if parsed:
            _render_parsed_info(parsed)
        else:
            st.write(out.get("파싱결과") or "(파싱 결과 없음)")

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 2</div>", unsafe_allow_html=True)
        st.subheader("Agent 2 — 심사 결과")
        if parsed is not None:
            screen = core.screen_loan(parsed)
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(_badge_html(screen["판정"]), unsafe_allow_html=True)
            with col2:
                dti_pct = f"{screen['DTI'] * 100:.1f}%" if screen["DTI"] is not None else "확인 불가"
                st.write(f"상환능력: **{screen['상환능력']}**  ·  부채/소득 비율: **{dti_pct}**")
                st.caption(
                    "※ 간이 지표(기존 부채 ÷ 연소득)이며, 실제 DSR(연간 원리금상환액 ÷ 연소득)과는 다르고 "
                    "이번 희망 대출금액의 상환 부담은 반영되지 않습니다."
                )

            if screen["판정"] == "상담필요":
                st.caption("ℹ️ 상환 여력이 넉넉하지 않아(부채비율 보통 구간) 은행 상담을 통해 조건을 확인해보시는 것이 좋습니다.")

            if screen["추천상품"]:
                best = screen["추천상품"]
                st.success(
                    f"추천 상품: **{best['상품코드']} {best['상품명']}** ({best['은행']}) · "
                    f"금리 {best['금리범위']} · 한도 {best['최대한도']:,}원"
                )

            if screen["판정"] != "어려움":
                if screen["적격상품"]:
                    st.write("적격 상품 목록 (상품코드·은행 포함):")
                    st.dataframe(screen["적격상품"], width="stretch", hide_index=True)
                else:
                    st.write("적격 상품이 없습니다.")
            elif screen["적격상품"]:
                st.caption("규정만 보면 통과하는 상품이 있으나, 상환능력이 부족해 추천하지 않습니다.")

            with st.expander("부적격 사유 보기"):
                _render_ineligible_reasons(screen["부적격사유"])
        else:
            st.warning("Agent 1의 출력을 JSON으로 해석하지 못해, 결정적 심사 결과(배지·적격상품)를 계산할 수 없습니다.")

        with st.expander("Agent 2 CoT·SC 원문 근거 보기", expanded=parsed is None):
            st.write(out.get("심사결과") or "(없음)")

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 3</div>", unsafe_allow_html=True)
        st.subheader("Agent 3 — 최종 안내문")
        st.markdown(out.get("안내문") or "(없음)")
        if out.get("안내문"):
            st.download_button(
                "안내문 다운로드 (.txt)",
                data=out["안내문"],
                file_name="대출심사_안내문.txt",
                mime="text/plain",
            )


def _fill_input(text: str):
    st.session_state.customer_input = text


def _reset_input():
    st.session_state.customer_input = ""
    st.session_state.pop("last_result", None)
    st.session_state.pop("last_input", None)


def main():
    _inject_apple_css()

    st.markdown("<div class='hero-title'>🏦 대출 적합성 심사 에이전트</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='hero-lead'>고객 상담 내용을 입력하면 3개 Agent(파싱 → 심사 → 안내)가 "
        "순차 협업해 결과를 안내합니다.</div>",
        unsafe_allow_html=True,
    )

    if "customer_input" not in st.session_state:
        st.session_state.customer_input = ""

    with st.sidebar:
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

    if not core.has_api_key():
        st.error(
            "⚠️ OPENAI_API_KEY를 찾을 수 없습니다. 프로젝트 루트의 `.env` 파일에 "
            "`OPENAI_API_KEY`를 설정하거나, `.streamlit/secrets.toml`에 등록한 뒤 앱을 다시 실행하세요. "
            "키가 없으면 심사 실행 버튼이 비활성화됩니다."
        )

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>고객 상담 입력</div>", unsafe_allow_html=True)
        st.text_area(
            "고객 상담 내용", key="customer_input", height=110, label_visibility="collapsed",
            placeholder="예) 월급 350만원 받는 정규직이고 부채는 800만원 있어요. 신용등급 3등급이고 2000만원 대출받고 싶어요.",
        )
        chips_html = "".join(f"<span class='apple-chip'>{kw}</span>" for kw in EXAMPLE_KEYWORDS)
        st.markdown(
            "<div style='font-size:12px;color:var(--color-ink-muted-48);margin-top:2px;'>"
            "💡 이런 내용을 포함해서 입력해보세요</div>"
            f"<div class='apple-chip-row'>{chips_html}</div>",
            unsafe_allow_html=True,
        )
        run_clicked = st.button("심사 시작", type="primary", disabled=not core.has_api_key())

    if run_clicked:
        text = st.session_state.customer_input.strip()
        # [타팀 피드백-2] 필수 정보 누락 시 에러처리: Agent를 돌리기 전에 규칙 기반 파서(API 키 불필요)로
        #   미리 확인해, 정보 부족을 '어려움'으로 오판하거나 헛되이 시간·비용을 쓰지 않게 한다.
        missing = core.missing_required_fields(core.rule_based_parse(text)) if text else None
        if not text:
            st.warning("고객 상담 내용을 먼저 입력해주세요.")
        elif missing:
            st.warning(
                "다음 필수 정보가 확인되지 않아 심사를 진행할 수 없습니다: "
                + ", ".join(f"**{m}**" for m in missing)
                + ".\n\n예) `월급 350만원 받는 정규직이고 부채는 800만원, 신용등급 3등급, 2000만원 대출받고 싶어요.` "
                "처럼 월 소득·신용등급·희망 대출금액을 포함해 다시 입력해주세요."
            )
        else:
            try:
                st.session_state.last_result = _run_pipeline(text)
                st.session_state.last_input = text
            except Exception as e:
                st.error(f"⚠️ {_friendly_error_message(e)}")
                with st.expander("자세한 오류 내용 보기"):
                    st.code(str(e))

    if st.session_state.get("last_result"):
        st.caption(f"입력: {st.session_state.get('last_input', '')}")
        _render_result(st.session_state.last_result)
        st.button("다시 입력하기", on_click=_reset_input)

    st.markdown(
        "<div class='app-footer'>대출 적합성 심사 · 교육용 데모</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
