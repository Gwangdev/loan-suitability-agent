"""LLM 에이전트 상세 출력 — 고객 원문과 전체 프롬프트가 로그로 나가지 않게 고정한다.

CrewAI는 에이전트나 크루의 verbose가 켜져 있으면 LLM을 부르기 전에 과업 설명을 표준 출력에
패널로 찍는다. 이 서비스의 과업 설명에는 고객의 자연어 원문(파싱)과 판정·상품 상세를 담은
전체 프롬프트(안내문)가 끼워져 들어가므로, 켜 두면 그대로 컨테이너 로그가 된다(금지 행위 ③).
파서 에이전트 하나만 켜져 있었고, 형제인 안내문 에이전트와 두 크루는 꺼져 있었다.

에이전트를 실제로 만들려면 CrewAI와 모델 설정이 필요하므로 호출 인자를 구문 트리로 본다.
켜는 호출이나 값이 코드에서 정해지지 않는 호출이 다시 들어오면 여기서 깨진다.
"""
import ast
import os

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loan_agent")


def _verbose_offenders():
    offenders = []
    for folder, _dirs, files in os.walk(PACKAGE):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    turned_off = isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                    if keyword.arg == "verbose" and not turned_off:
                        offenders.append(f"{os.path.relpath(path, PACKAGE)}:{node.lineno}")
    return offenders


def test_no_llm_call_is_built_with_verbose_on():
    assert _verbose_offenders() == []
