"""배포 의존성 잠금 파일이 요구 범위·해시·감사 예외와 어긋나지 않게 고정한다.

`requirements.txt`는 범위만 적으므로 빌드할 때마다 그 시점의 최신 버전이 풀렸다. 운영 재빌드
한 번에 crewai가 1.15.18에서 1.15.21로 바뀌었고, 로컬·CI·운영이 서로 다른 버전으로 테스트되고
배포됐다. 그래서 이미지와 CI는 해시가 붙은 `requirements.lock`으로만 설치한다.

잠금은 사람이 고치는 파일이 아니라 생성하는 파일이라, 요구 범위를 바꾸고 다시 만들지 않으면
조용히 어긋난다. 네트워크 없이 확인할 수 있는 것만 본다 — 모든 요구 항목이 잠금에 범위 안의
버전으로 고정돼 있는지, 고정된 모든 패키지에 해시가 있는지. 해시가 빠진 항목이 하나라도 있으면
`pip install --require-hashes`가 설치를 거부하므로 배포가 빌드 단계에서 멈춘다.

감사 예외 목록은 게이트와 CI가 함께 읽는다. 사유 없는 항목은 둘 다 적용하지 않으므로, 커밋된
목록의 모든 항목에 사유가 있는지도 여기서 본다.
"""
import pathlib
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
REQUIREMENTS = ROOT / "requirements.txt"
AUDIT_IGNORE = ROOT / ".pip-audit-ignore"

_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)")
_IGNORE_ENTRY = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]+)\s+#\s*(?P<reason>\S.*)$")


def _lock_blocks():
    """잠금 파일을 패키지 하나당 한 덩어리(고정 줄 + 이어지는 해시 줄)로 나눈다."""
    blocks = []
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if match:
            blocks.append({"name": canonicalize_name(match["name"]),
                           "version": Version(match["version"]), "hashes": 0})
        elif blocks and "--hash=" in line:
            blocks[-1]["hashes"] += 1
    return blocks


def _requirements():
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            yield Requirement(line)


def test_every_requirement_is_pinned_in_the_lock_within_its_range():
    pinned = {}
    for block in _lock_blocks():
        pinned.setdefault(block["name"], []).append(block["version"])

    outside = []
    for requirement in _requirements():
        versions = pinned.get(canonicalize_name(requirement.name), [])
        if not any(requirement.specifier.contains(v, prereleases=True) for v in versions):
            outside.append(f"{requirement} → {[str(v) for v in versions] or '잠금에 없음'}")

    assert outside == [], "requirements.txt를 바꾼 뒤 잠금을 다시 만들지 않았다"


def test_every_pinned_package_in_the_lock_carries_a_hash():
    blocks = _lock_blocks()

    assert blocks, "잠금 파일에 고정된 패키지가 없다"
    assert [f"{b['name']}=={b['version']}" for b in blocks if b["hashes"] == 0] == []


def test_every_audit_ignore_entry_states_its_reason():
    entries = [line.strip() for line in AUDIT_IGNORE.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]

    assert entries, "예외가 없으면 목록 파일을 지운다 — 빈 목록은 읽는 쪽이 존재 이유를 오해한다"
    assert [line for line in entries if not _IGNORE_ENTRY.match(line)] == []
