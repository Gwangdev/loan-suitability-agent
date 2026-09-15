"""한 번 실행하고 끝나는 서비스가 이미지의 상태 확인을 물려받지 않게 고정한다.

ui·app·migrate는 같은 이미지를 쓰고, 이미지의 HEALTHCHECK는 Streamlit 화면(:8501)을 본다. migrate는
스키마를 올리고 1초 남짓에 끝나므로 그 검사가 한 번도 돌지 않는데, 멈춘 컨테이너에는 Docker가 붙인
`unhealthy`가 남는다. 동작에는 영향이 없지만 `docker inspect`로 운영 상태를 읽는 사람과 도구에게 거짓
신호가 된다. 그래서 끝나는 서비스는 compose에서 이미지의 검사를 끈다. 이 서비스를 기다리는 쪽은
상태 확인이 아니라 종료 코드(`service_completed_successfully`)로 판정하므로 끄는 것이 판정을 바꾸지 않는다.

끝나는 서비스를 이름으로 적지 않고 「다른 서비스가 완료를 기다리는 서비스」로 찾는다. 새 일회성
서비스가 생겨도 같은 기준을 받는다. 운영은 기본 파일에 운영 파일을 얹어 뜨므로 합친 결과를 본다.
"""
import os

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return yaml.safe_load(handle)["services"]


def _production_services():
    services = {name: dict(spec) for name, spec in _load("docker-compose.yml").items()}
    for name, spec in _load("docker-compose.prod.yml").items():
        services.setdefault(name, {}).update(spec)
    return services


SERVICES = _production_services()


def _awaited_to_complete():
    awaited = set()
    for spec in SERVICES.values():
        depends_on = spec.get("depends_on") or {}
        if isinstance(depends_on, dict):
            awaited |= {name for name, cond in depends_on.items()
                        if (cond or {}).get("condition") == "service_completed_successfully"}
    return sorted(awaited)


def test_there_is_at_least_one_one_shot_service_to_check():
    assert _awaited_to_complete(), "완료를 기다리는 서비스가 없다 — 판정 기준이 더는 맞지 않는다"


@pytest.mark.parametrize("name", _awaited_to_complete())
def test_a_one_shot_service_does_not_inherit_the_image_healthcheck(name):
    assert SERVICES[name].get("healthcheck") == {"disable": True}, (
        f"{name}: 이미지의 상태 확인을 물려받아, 끝난 뒤 unhealthy로 보인다"
    )
