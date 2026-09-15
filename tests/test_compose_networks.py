"""워커의 외부 통신 경로와 데이터 계층 격리를 compose 정의로 고정한다.

워커는 서버 키로 모델 제공자를 부르는데, 처음에는 DB만 보고 내부 전용 `backend`에만 연결돼 있었다.
내부 전용 네트워크에는 이름 해석과 외부 통신 경로가 없어 호출이 연결 단계에서 실패했고, 실행은
제공자 오류로 기록됐다. 그래서 워커에게 외부 통신이 되는 네트워크를 따로 주되, 그 네트워크에는
다른 서비스를 두지 않는다. 들어오는 경로용 `frontend`에 워커를 붙이면 워커가 화면까지 닿게 되고,
외부 통신 네트워크에 다른 서비스가 붙으면 그 서비스에도 이유 없는 외부 경로가 생긴다.
데이터 계층은 어느 경우에도 내부 전용 네트워크에만 둔다.

워커는 로컬 프로파일에만 있으므로 기본 파일을 판정한다. 운영은 기본 파일에 운영 파일을 얹어 뜨지만
네트워크 정의는 기본 파일에만 있다.
"""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as handle:
    COMPOSE = yaml.safe_load(handle)

SERVICES = COMPOSE["services"]
NETWORKS = COMPOSE.get("networks") or {}


def _joined(name):
    networks = SERVICES[name].get("networks") or []
    return set(networks if isinstance(networks, list) else networks.keys())


def _is_internal(network):
    return bool((NETWORKS.get(network) or {}).get("internal"))


def test_the_worker_can_reach_outside_through_a_non_internal_network():
    external = {n for n in _joined("worker") if not _is_internal(n)}

    assert external, "worker가 내부 전용 네트워크에만 있어 모델 제공자에 닿지 못한다"


def test_the_worker_keeps_its_database_network():
    assert "backend" in _joined("worker")


def test_the_workers_external_network_is_shared_with_no_other_service():
    for network in (n for n in _joined("worker") if not _is_internal(n)):
        others = sorted(name for name in SERVICES if name != "worker" and network in _joined(name))
        assert not others, f"{network}: 워커의 외부 통신 네트워크에 {others}도 연결돼 있다"


def test_the_worker_stays_out_of_production():
    assert SERVICES["worker"].get("profiles") == ["local"]


def test_the_database_is_on_internal_networks_only():
    joined = _joined("postgres")

    assert joined and all(_is_internal(n) for n in joined), f"postgres 네트워크: {sorted(joined)}"
