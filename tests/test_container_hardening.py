"""운영 구성의 모든 컨테이너가 비루트 사용자와 읽기 전용 루트 파일시스템으로 뜨는지 고정한다.

비루트와 읽기 전용은 한 세트다. 비루트만 걸면 그 사용자가 쓸 수 있는 경로에 실행 파일을 떨굴 수
있고, 읽기 전용만 걸면 루트 권한으로 볼륨과 커널 표면에 닿는다. 기록은 두 가지를 모두 적용했다고
적었지만, 인터넷에 열린 유일한 컨테이너인 caddy에는 둘 다 없었고 migrate에는 읽기 전용이 없었다.

운영은 기본 파일에 운영 파일을 얹어 뜬다. 게이트는 파일을 하나씩 보므로 운영 파일에 재시작
정책만 적힌 ui·app·postgres도 누락으로 잡는데, 합치면 기본 파일의 설정이 살아 있다. 그래서 이
테스트는 운영과 같은 순서로 두 파일을 합친 결과를 판정한다. 로컬 프로파일의 워커도 같은 기준을
받는다 — 운영에 뜨지 않는다는 사실이 로컬 컨테이너를 루트로 돌려도 된다는 뜻은 아니다.
"""
import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_USERS = {"0", "root"}


def _load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return yaml.safe_load(handle)["services"]


def _production_services():
    services = {name: dict(spec) for name, spec in _load("docker-compose.yml").items()}
    for name, spec in _load("docker-compose.prod.yml").items():
        services.setdefault(name, {}).update(spec)
    return services


SERVICES = _production_services()


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_production_container_runs_as_a_non_root_user(name):
    user = str(SERVICES[name].get("user") or "")

    assert user, f"{name}: user가 없다 — 이미지 기본 사용자(대개 root)로 뜬다"
    assert user.split(":")[0] not in _ROOT_USERS, f"{name}: root로 뜬다"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_production_container_has_a_read_only_root_filesystem(name):
    assert SERVICES[name].get("read_only") is True, f"{name}: 루트 파일시스템이 쓰기 가능하다"
