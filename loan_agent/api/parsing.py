"""POST /api/v1/parsing-preview — 자연어를 구조화 후보로 바꾼다. 저장하지 않는다.

이 경로는 규칙 기반 파서만 쓴다. LLM 파싱은 후보를 만들 뿐이고 권위값이 아니므로,
상담원이 폼에서 확인·수정한 값이 심사에 들어간다. 여기서 나온 것도 같은 성격의
후보이며 판정에 바로 쓰이지 않는다.

DB 세션을 열지 않는다. 저장하지 않는 경로가 커넥션을 잡으면 풀만 축낸다.
자연어 원문도 남기지 않는다 — 응답으로 돌려주고 끝이다(ADR-002).
"""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from loan_agent import core

router = APIRouter(tags=["parsing"])


class ParsingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=10_000)


@router.post("/api/v1/parsing-preview")
def parsing_preview(payload: ParsingPreviewRequest):
    candidate = core.rule_based_parse(payload.text)
    return {"candidate": candidate, "missing_fields": core.missing_required_fields(candidate)}
