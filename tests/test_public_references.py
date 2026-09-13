"""공개 저장소의 문서·코드가 비공개 작업 기록의 번호를 가리키지 않는다는 것을 고정한다.

작업 기록(피드백 기록과 기술 공백 처리 목록)을 공개 저장소에서 내리면서, 그 기록의 항목 번호를
가리키던 문장도 그 자리에서 뜻이 통하게 고쳤다. 그런데 번호를 백틱으로 감싼 표기만 찾아서
「대장」 뒤에 번호를 평문으로 적은 표기와 목록 번호가 설계 결정 문서·명세 주석·테스트에 남았다.
외부 독자는 그 번호를 따라갈 곳이 없으므로, 표기 형태를 넓혀 추적 파일 전체를 검사한다.
같은 이유로 방어 질문 목록의 번호도 찾는다. 그 번호는 원문자(⑧·㉓)라 숫자 패턴에 걸리지 않아
데이터 모델 문서와 리스크 통제 대장에 남아 있었다.

리스크 통제 대장의 항목(A4·B5 같은 글자+숫자)은 공개 문서라 대상이 아니다. 하네스 파일은
작업 기록을 다루는 도구 자체라 번호 표기가 규칙 설명의 일부이므로 제외한다.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ("reference/", ".claude/", "tools/", "CLAUDE.md")
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()

PRIVATE_NUMBER = re.compile(
    r"대장 ?`?#\d"          # 피드백 기록 번호
    r"|`#\d+`"              # 백틱으로 감싼 기록 번호
    r"|T[123] ?#\d"         # 기술 공백 처리 목록 번호
    r"|P0-[a-z] ?#\d"       # 핵심 요구 목록 번호
    r"|wires up #\d"        # 명세 주석의 기록 번호
    r"|방어\s?질문\s?[①-⑳㉑-㉟㊱-㊿]"  # 방어 질문 목록의 원문자 번호
)


def _tracked_files():
    # 한글 경로를 이스케이프하지 않도록 quotepath를 끄고, 이름에 공백이 있어도 갈라지지 않게 NUL로 받는다.
    out = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p and not p.startswith(HARNESS) and p != SELF]


def test_tracked_files_are_listed_including_korean_names():
    files = _tracked_files()
    assert "docs/설계결정.md" in files


def test_public_files_do_not_point_at_private_work_record_numbers():
    hits = []
    for rel in _tracked_files():
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if PRIVATE_NUMBER.search(line):
                hits.append(f"{rel}:{lineno}")
    assert hits == []
