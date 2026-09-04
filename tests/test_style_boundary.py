"""스타일 값이 파이썬으로 새지 않는지 검사한다.

`CLAUDE.md`가 「스타일은 파일이지 코드가 아니다」를 불변 규칙으로 두고 있고, `#38`에서
217줄짜리 CSS 문자열을 화면 코드에서 떼어낸 적이 있다. 그런데 판정 배지 색은 그때
살아남아 파이썬 사전으로 남아 있었다 — 큰 덩어리는 눈에 띄지만 한 줄짜리 색 사전은
안 띈다.

값을 보는 대신 **경계를 본다.** 화면 코드에 색 리터럴과 인라인 style 속성이 없으면
표현이 CSS 한 곳에 모여 있다는 뜻이다.
"""
import re
from pathlib import Path

import pytest

UI_SOURCE = Path(__file__).resolve().parent.parent / "loan_agent" / "app.py"
STYLESHEET = Path(__file__).resolve().parent.parent / "loan_agent" / "static" / "apple.css"

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")
INLINE_STYLE = re.compile(r"""style\s*=\s*['"]""")


def test_ui_code_carries_no_color_literals():
    """색은 CSS가 정한다. 파이썬에 색이 있으면 두 곳을 함께 고쳐야 한다."""
    found = HEX_COLOR.findall(UI_SOURCE.read_text(encoding="utf-8"))

    assert not found, f"화면 코드에 색 리터럴이 있다: {found}"


def test_ui_code_carries_no_inline_style_attributes():
    """인라인 style은 CSS를 우회하므로 토큰을 바꿔도 그 자리만 안 바뀐다."""
    source = UI_SOURCE.read_text(encoding="utf-8")

    assert not INLINE_STYLE.search(source), "화면 코드에 인라인 style 속성이 있다"


@pytest.mark.parametrize("verdict", ["승인가능", "상담필요", "어려움"])
def test_every_verdict_has_a_badge_class_backed_by_css(verdict):
    """판정마다 배지 클래스가 있고 그 클래스가 CSS에 실재한다.

    파이썬이 클래스 이름만 들고 CSS에 대응 규칙이 없으면 배지가 회색으로 나가는데,
    화면은 아무 오류도 내지 않으므로 눈으로 보기 전까지 드러나지 않는다.
    """
    from loan_agent import app

    modifier = app.BADGE_MODIFIER.get(verdict)
    assert modifier, f"{verdict}에 배지 클래스가 없다"

    markup = app._badge_html(verdict)
    assert f"apple-badge--{modifier}" in markup

    assert f".apple-badge--{modifier}" in STYLESHEET.read_text(encoding="utf-8"), (
        f"CSS에 .apple-badge--{modifier} 규칙이 없다"
    )


def test_unknown_verdict_falls_back_without_inventing_a_colour():
    """모르는 판정에 색을 지어내면 화면이 판정을 아는 척한다."""
    from loan_agent import app

    markup = app._badge_html("알 수 없음")

    assert "apple-badge--" not in markup
    assert "apple-badge" in markup


def test_stylesheet_defines_the_token_scales_the_rules_reference():
    """규칙이 참조하는 토큰이 실제로 정의돼 있는지 본다.

    오타 난 `var(--space-9)`는 조용히 무시돼 여백이 0이 된다. CSS는 알 수 없는 변수를
    오류로 만들지 않으므로, 참조와 정의를 대조하는 자리가 없으면 드러나지 않는다.
    """
    css = STYLESHEET.read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.MULTILINE))
    referenced = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))

    missing = referenced - defined
    assert not missing, f"정의되지 않은 토큰을 참조한다: {sorted(missing)}"
