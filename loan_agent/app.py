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
import sys
import threading
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

# [타팀 피드백-1] Agent 2 작동 시간이 길어 프론트엔드 UX가 답답하다는 지적 반영.
#   심사(특히 Agent 2)가 수 초~수십 초 걸리므로, 대기 중 화면이 멈춘 것처럼 보이지 않도록
#   이 팁들을 몇 초 간격으로 돌려 유용한 정보를 제공한다(교육용 데모라 개념 설명 위주).
AGENT_TIPS = [
    "💡 DSR(총부채원리금상환비율)은 '연간 원리금상환액 ÷ 연소득'으로, 낮을수록 상환 여력이 큽니다(은행권 규제 상한 40%).",
    "💡 신용등급은 숫자가 낮을수록 우량합니다(1등급이 가장 우량).",
    "💡 판정은 LLM이 아니라 CSV 하드규칙 기반의 결정적 로직이 내립니다 — 재현성 있는 안전장치예요.",
    "💡 Agent 2는 CoT(단계적 추론)로 DSR 상환능력→신용등급→한도→상품선별 순서로 근거를 만듭니다.",
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


def _run_pipeline(customer_input: str, api_key: str = None) -> dict:
    """crewai Task의 callback은 crewai 내부 스레드(ThreadPoolExecutor)에서 실행되므로,
    거기서 Streamlit API(st.status 등)를 직접 부르면 ScriptRunContext가 없어 그 콜백이
    죽어버리고 crewai가 이를 Task Failure로 처리한다. 그래서 콜백은 스레드 안전한
    queue.Queue에만 값을 넣고, 실제 st.status 업데이트는 메인 스레드(여기)에서
    큐를 폴링하며 처리한다.
    api_key를 방문자별 키로 파이프라인에 그대로 전달한다."""
    stage_queue: "queue.Queue" = queue.Queue()
    outcome: dict = {}

    def on_stage(stage, output):
        stage_queue.put(stage)

    def worker():
        try:
            outcome["result"] = asyncio.run(
                core.run_service_with_stages(customer_input, on_stage=on_stage, api_key=api_key)
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


def _render_result(out: dict, screen: dict = None):
    # screen을 인자로 받으면(구조화 폼 기준 결정적 판정) 그것을 권위값으로 쓴다.
    #   → 화면 배지·적격상품이 LLM 재파싱이 아니라 '사용자가 확정한 구조화 입력'과 일치(A1 이중경로 해소).
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
                            [{"순위": i, "상품코드": c["상품코드"], "상품명": c["상품명"],
                              "은행": c["은행"], "금리범위": c["금리범위"],
                              "승인여유마진": c["승인여유마진"], "중도상환수수료(%)": c["중도상환수수료"],
                              "상환방식": c["상환방식"], "금리방식": c["금리방식"]}
                             for i, c in enumerate(screen["추천후보"], 1)],
                            width="stretch", hide_index=True,
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

        if out.get("심사결과"):
            with st.expander("Agent 2 CoT·SC 원문 근거 보기"):
                st.write(out["심사결과"])

    with st.container(border=True):
        st.markdown("<div class='card-eyebrow'>STEP 3</div>", unsafe_allow_html=True)
        st.subheader("Agent 3 — 최종 안내문")
        if out.get("안내문"):
            st.markdown(out["안내문"])
            st.download_button(
                "안내문 다운로드 (.txt)",
                data=out["안내문"],
                file_name="대출심사_안내문.txt",
                mime="text/plain",
            )
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
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    response = httpx.post(
        f"{API_BASE_URL}/api/v1/assessments",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, canonical))},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def _screen_from_assessment(assessment: dict) -> dict:
    """API의 안정된 영문 계약을 기존 화면 표시용 최소 구조로 바꾼다."""
    labels = {"ELIGIBLE": "승인가능", "CONDITIONAL": "상담필요", "INELIGIBLE": "어려움"}
    bands = {"COMFORTABLE": "여유", "MODERATE": "보통", "STRAINED": "부족"}
    return {
        "판정": labels[assessment["verdict"]],
        "상환능력": bands[assessment["repayment_band"]],
        "DSR": assessment["dsr"],
        "월상환액": assessment["monthly_payment"],
        "추천상품": None,
        "추천후보": [],
        "적격상품": [],
        "부적격사유": {},
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
    """이 세션에서 실제 파이프라인 실행에 쓸 키를 결정한다.
    우선순위: 방문자가 사이드바에 입력한 키(세션 메모리) > 서버 환경변수(.env/secrets).
    방문자 키는 session_state에만 두고 os.environ에 넣지 않는다
    (공유 프로세스에서 타 방문자에게 새지 않도록). 없으면 None."""
    visitor = (st.session_state.get("visitor_key") or "").strip()
    if visitor:
        return visitor
    return os.getenv("OPENAI_API_KEY") or None


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

        # 키가 없는 방문자도 '입력 → 실제 3-Agent 출력'을
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

    # ④-b AI 안내문까지 (키 필요) — 구조화 값을 표준 문장으로 만들어 파이프라인에 투입.
    if run_clicked and not missing:
        now = time.monotonic()
        last_ts = st.session_state.get("last_run_ts", 0.0)
        if run_count >= MAX_RUNS_PER_SESSION:
            st.warning(f"이번 세션 실행 한도({MAX_RUNS_PER_SESSION}회)에 도달했습니다. 새로고침 후 다시 시도해주세요.")
        elif now - last_ts < COOLDOWN_SEC:
            st.warning(f"연속 실행을 제한합니다. {COOLDOWN_SEC - int(now - last_ts)}초 후 다시 시도해주세요.")
        else:
            try:
                nl = _customer_to_nl(customer)
                st.session_state.last_result = _run_pipeline(nl, api_key=api_key)
                st.session_state.last_screen = _screen_from_assessment(_submit_assessment(customer))
                st.session_state.last_input = nl
                st.session_state.is_demo = False
                st.session_state.run_count = run_count + 1
                st.session_state.last_run_ts = now
            except Exception as e:
                st.error(f"⚠️ {_friendly_error_message(e)}")
                with st.expander("자세한 오류 내용 보기"):
                    st.code(str(e))

    if st.session_state.get("last_result"):
        # 사전 녹화 결과일 때 명확히 고지(실제 실행과 구분).
        if st.session_state.get("is_demo"):
            fx = _demo_fixtures()
            st.info(
                f"📽️ **사전 녹화된 데모 결과입니다 — 토큰이 전혀 소모되지 않았습니다.** "
                f"실제 3-Agent 파이프라인을 미리 1회 실행해 저장한 입력/출력이며, "
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
