"""모듈 별칭을 같은 함수 안의 지역 변수가 가리지 않는지 본다.

`core.py`를 여러 모듈로 나누면서 화면 코드의 참조를 `demo_cases.TEST_CASES` 형태로 바꿨는데, 같은
함수가 아래쪽에서 `demo_cases`를 지역 변수로 다시 묶고 있었다. 파이썬은 함수 안에 대입이 하나라도
있으면 그 이름을 통째로 지역으로 보므로, 위쪽의 모듈 참조가 실행 시점에 `UnboundLocalError`가 됐다.
임포트만으로는 드러나지 않고 화면을 그릴 때 터져 운영에서 처음 보였다.

테스트는 화면을 띄우지 않고 구문 트리로 본다 — 이 종류의 결함은 실행 경로를 타지 않아도 구조만으로
판정할 수 있고, Streamlit 렌더링을 테스트에서 재현하는 것보다 훨씬 싸다.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted(ROOT.glob("loan_agent/**/*.py"))


def _module_aliases(tree: ast.Module) -> set:
    aliases = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            aliases |= {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return aliases


def _assigned_names(function: ast.AST) -> set:
    assigned = set()
    for node in ast.walk(function):
        if isinstance(node, ast.FunctionDef) and node is not function:
            continue
        for target in getattr(node, "targets", []) or ([node.target] if hasattr(node, "target") else []):
            if isinstance(target, ast.Name) and isinstance(getattr(target, "ctx", None), ast.Store):
                assigned.add(target.id)
    return assigned


def _attribute_reads(function: ast.AST) -> set:
    return {
        node.value.id
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_function_shadows_a_module_alias_it_also_reads(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = _module_aliases(tree)
    for function in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        shadowed = aliases & _assigned_names(function) & _attribute_reads(function)
        assert not shadowed, (
            f"{path.name}:{function.lineno} {function.name}()가 모듈 별칭 {sorted(shadowed)}을 "
            "지역 변수로 다시 묶으면서 같은 함수에서 모듈로도 읽는다 — 실행 시점에 UnboundLocalError가 된다"
        )
