"""LLM을 부르는 유일한 자리.

이 파일이 따로 있는 이유는 크기가 아니라 경계다. 이 서비스의 관통 논리는 「판정은 코드,
설명은 LLM」이고, 그 경계가 주석이 아니라 **파일 경계**로 드러나야 한다. `core`에는 LLM을
부르는 코드가 한 줄도 없다 — 적합성 판정(`screen_loan`)이 LLM에 닿지 않는다는 주장이
디렉터리 구조에서 확인된다.

LLM이 관여하는 곳은 둘뿐이다. **입구**에서 자연어를 구조화 후보로 바꾸고(규칙 파서와
대조해 불일치를 사람에게 올린다 — ADR-029), **출구**에서 이미 확정된 판정을 고객이 읽을
문장으로 푼다(판정·수치를 데이터로 받으므로 생성할 대상이 없다 — ADR-030). 그 사이의
판정은 여기 없다.

Agent·Task를 캐시하지 않는다. 방문자마다 키가 다르므로 공유하면 남의 키로 도는 경로가
생긴다. 키는 인자로만 흐르고 `os.environ`에 쓰지 않는다(금지 자동화 행위 7).
"""
import json
import os
import re

from loan_agent.core import DISCLAIMER


# ---------------------------------------------------------------------------
# LLM 경로 — 입구(파싱)와 출구(안내문) 두 곳뿐이다. 가운데 판정은 screen_loan이
# 결정적으로 내리며 LLM이 닿지 않는다. Agent·Task는 호출 시점에 만들고 캐시하지
# 않는다 — 방문자마다 키가 다르므로 공유하면 남의 키로 도는 경로가 생긴다.
# ---------------------------------------------------------------------------
def get_llm(api_key: str = None):
    """LLM 인스턴스를 생성한다.
    api_key를 명시적으로 받으면 그 키를 쓰고(공개 배포에서 방문자별 키),
    없으면 환경변수(OPENAI_API_KEY)로 폴백한다. 방문자 키를 os.environ에 저장하지 않고
    이렇게 인자로만 넘기는 이유: Streamlit Cloud처럼 여러 방문자가 한 프로세스를 공유할 때
    한 사람의 키가 os.environ을 통해 다른 사람 요청에 새는 것을 막기 위함이다."""
    # 키 검증을 crewai import보다 먼저 — 키가 없으면 무거운 의존성 없이도 즉시 명확한 오류.
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "OPENAI_API_KEY를 찾을 수 없습니다. .env에 설정하거나(로컬), "
            "앱 사이드바에 본인 키를 입력하세요(공개 데모). 키 없이도 '무토큰 데모'는 이용 가능합니다."
        )
    from crewai import LLM

    model_name = os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")
    return LLM(model=model_name, api_key=key, temperature=0.2), model_name


def build_parser_agent(llm):
    """Agent 1 — 정보 파싱가."""
    from crewai import Agent

    return Agent(
        role="정보 파싱가",
        goal="고객 자연어 입력에서 월소득·부채·신용등급·희망금액·직장유형·담보보유 6개 필드를 정확히 추출해 원 단위 JSON으로 구조화한다.",
        backstory=(
            "당신은 고객의 자연어를 구조화 데이터로 바꾸는 전문가입니다. "
            "금액은 모두 원 단위 정수로 환산합니다(예: 700만원 -> 7000000). "
            "명시되지 않은 값은 추측하지 말고 0 또는 '제한없음'으로 둡니다. "
            "담보보유는 고객이 담보(예: 집, 부동산)를 제공할 수 있다고 명시한 경우에만 true, "
            "언급이 없거나 없다고 하면 false로 둡니다. "
            "입력에 없는 정보를 지어내지 않습니다."
        ),
        llm=llm, allow_delegation=False, verbose=True,
    )


def parse_with_llm(customer_input: str, api_key: str) -> dict:
    """Agent 1 프롬프트로 자연어를 한 번만 JSON 후보로 파싱한다.

    이 결과는 규칙 파서와 나란히 비교할 후보일 뿐 심사에 쓰지 않는다. 호출자는
    불일치를 사용자에게 보여 주고, 확정된 폼 값만 결정적 심사에 보낸다.
    """
    from crewai import Crew, Process, Task

    llm, _ = get_llm(api_key=api_key)
    parser = build_parser_agent(llm)
    task = Task(
        description=(
            "다음 고객 입력을 JSON 후보로 파싱하라:\n\"{customer_input}\"\n\n"
            "월소득·부채·신용등급·희망금액·직장유형·담보보유 여섯 필드를 추출한다."
        ),
        expected_output=(
            '오직 JSON만 출력: {"월소득": 정수, "부채": 정수, "신용등급": 정수, '
            '"희망금액": 정수, "직장유형": "문자열", "담보보유": true 또는 false}'
        ),
        agent=parser,
    )
    crew = Crew(agents=[parser], tasks=[task], process=Process.sequential, verbose=False)
    raw = str(crew.kickoff(inputs={"customer_input": customer_input}))
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise ValueError("LLM 파서가 JSON 후보를 반환하지 않았습니다.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM 파서 결과가 객체가 아닙니다.")
    return parsed


async def generate_guidance(decision_context: dict, *, api_key: str | None = None) -> dict:
    """확정된 심사 데이터를 주입해 안내문만 한 번 생성한다.

    판정·DSR·추천상품은 이미 결정적 경로가 확정한 값이다. 도구를 제공하지 않아
    모델이 그 값을 다시 계산하거나 상품을 조회하는 경로를 만들지 않는다.
    """
    from crewai import Agent, Crew, Process, Task

    llm, model_name = get_llm(api_key=api_key)
    advisor = Agent(
        role="결과 안내가",
        goal="주어진 확정 심사 결과를 고객 눈높이의 조건부 안내문으로 설명한다.",
        backstory=(
            "당신은 교육용 대출 상담 안내문을 작성합니다. 제공된 판정·DSR·추천상품 데이터만 "
            "사실로 사용하고, 새 판정·상품·금리·한도를 만들거나 바꾸지 않습니다. "
            "확정 승인 표현을 쓰지 말고 조건부로 안내하며, 마지막에 필수 디스클레이머를 포함합니다."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description=(
            "다음은 결정적 심사 경로가 확정한 데이터다. 이 값을 바꾸지 말고 고객용 안내문만 작성하라.\n"
            "{decision_context}\n\n"
            "추천상품이 있으면 상품코드·상품명·은행·금리범위·한도를 그대로 설명하고, 없으면 상품을 "
            "추천하지 말고 개선 방향과 상담 안내를 쓴다. 마지막에 다음 문장을 반드시 그대로 붙인다: "
            f"{DISCLAIMER}"
        ),
        expected_output="조건부 표현의 고객용 안내문 한 편. 판정·DSR·추천 데이터와 모순되는 내용을 만들지 않는다.",
        agent=advisor,
    )
    crew = Crew(agents=[advisor], tasks=[task], process=Process.sequential, verbose=False)
    result = await crew.kickoff_async(
        inputs={"decision_context": json.dumps(decision_context, ensure_ascii=False)}
    )
    return {
        "text": str(result),
        "model_name": model_name,
        "usage": getattr(crew, "usage_metrics", None),
    }


def get_model_name() -> str:
    """현재 .env에 설정된 모델명(키 유무와 무관하게 조회만, 오류 없음)."""
    return os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


__all__ = ['get_llm', 'build_parser_agent', 'parse_with_llm', 'generate_guidance', 'get_model_name', 'has_api_key']
