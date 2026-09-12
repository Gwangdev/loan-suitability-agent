"""포트폴리오 페이지의 디자인 토큰이 데모 화면과 어긋나지 않게 고정한다.

포트폴리오 페이지(site/index.html)는 Caddy가 앱과 따로 서빙하므로 데모 화면의 CSS 파일을
불러올 수 없고, 토큰 값을 복사해 쓴다. 같은 값이 두 곳에 있으면 한쪽만 고쳐 두 화면이 다른
체계로 읽히게 된다. 페이지에만 있는 값은 --site- 접두어를 붙이게 하고, 나머지는 데모 화면에
같은 이름·같은 값으로 있어야 한다.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CSS = os.path.join(ROOT, "loan_agent", "static", "apple.css")
SITE_HTML = os.path.join(ROOT, "site", "index.html")

_ROOT_BLOCK = re.compile(r":root\s*\{(.*?)\n\s*\}", re.S)
_TOKEN = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _tokens(path):
    text = open(path, encoding="utf-8").read()
    block = _ROOT_BLOCK.search(text)
    assert block, f":root 블록이 없다: {path}"
    body = _COMMENT.sub("", block.group(1))
    return {name: " ".join(value.split()) for name, value in _TOKEN.findall(body)}


def test_site_tokens_match_the_app_tokens():
    app = _tokens(APP_CSS)
    site = _tokens(SITE_HTML)

    shared = {name: value for name, value in site.items() if not name.startswith("--site-")}
    assert shared, "페이지가 공유 토큰을 하나도 쓰지 않는다 — 대조할 대상이 사라졌다"

    missing = sorted(name for name in shared if name not in app)
    drifted = sorted(f"{name}: site={shared[name]} app={app[name]}"
                     for name in shared if name in app and shared[name] != app[name])
    assert missing == [], "데모 화면에 없는 토큰 — 페이지 전용이면 --site- 접두어를 붙일 것"
    assert drifted == []
