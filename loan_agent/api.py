"""대출 적합성 심사 — FastAPI 서비스 계층.
작성자 : 원광식

[디벨롭: FastAPI 서비스화] 비즈니스 로직(core.py)을 UI-무관하게 분리해 둔 설계를
`core → REST API → 클라이언트` 구조로 승격한다. Streamlit 앱과 미래의 어떤 프론트도
이 API를 호출하는 얇은 클라이언트가 될 수 있다(§docs 기술노트_FastAPI서비스화.md).

엔드포인트
  GET  /health    상태 확인(키 불필요)
  GET  /products  대출상품 목록(키 불필요)
  POST /parse     자연어 → 구조화 필드(규칙 기반, 키 불필요)
  POST /screen    구조화 고객정보 → 결정적 심사 판정(키 불필요 · 핵심)
  POST /advise    자연어 → 3-Agent 파이프라인 전체 실행(OPENAI_API_KEY 필요)

실행: uvicorn loan_agent.api:app --reload
문서: 서버 실행 후 http://127.0.0.1:8000/docs (OpenAPI 자동 생성)
"""
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from loan_agent import core

app = FastAPI(
    title="대출 적합성 심사 API",
    version="1.0.0",
    description=(
        "3-Agent 대출 심사 파이프라인의 서비스 계층. 판정은 결정적 로직(`/screen`)이 내리고, "
        "LLM 파이프라인(`/advise`)은 파싱·근거설명·안내문만 담당한다. 교육용 데모."
    ),
)


# ---------------------------------------------------------------------------
# 요청 스키마 (Pydantic — 자동 검증 + /docs 문서화)
# ---------------------------------------------------------------------------
class CustomerIn(BaseModel):
    """구조화 고객정보(원 단위 금액). /screen 입력."""
    월소득: int = Field(..., ge=0, description="월 소득(원)", examples=[7000000])
    부채: int = Field(0, ge=0, description="기존 부채 잔액(원)", examples=[0])
    신용등급: int = Field(..., ge=1, le=10, description="신용등급(1=우량)", examples=[1])
    희망금액: int = Field(..., ge=0, description="희망 대출금액(원)", examples=[30000000])
    직장유형: str = Field("제한없음", description="정규직/계약직/제한없음", examples=["정규직"])
    담보보유: bool = Field(False, description="담보 제공 가능 여부")


class TextIn(BaseModel):
    """자연어 상담 입력. /parse, /advise 공용."""
    text: str = Field(..., min_length=1, max_length=2000,
                      description="고객 상담 자연어(최대 2000자 — 비용 폭증 방지)",
                      examples=["월급 700만원 받는 정규직이고 부채는 없습니다. 신용등급 1등급이고 3000만원 대출받고 싶어요."])


# ---------------------------------------------------------------------------
# 키 불필요 엔드포인트 (결정적 · 오프라인 · CI 테스트 대상)
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health():
    """상태 확인. LLM 키 없이도 결정적 심사가 가능한지 함께 알려준다."""
    return {"status": "ok", "model": core.get_model_name(), "llm_ready": core.has_api_key()}


@app.get("/products", tags=["data"])
def products():
    """대출상품 목록(진실의 원천 CSV)."""
    return {"count": len(core.PRODUCTS), "products": core.PRODUCTS}


@app.post("/parse", tags=["screening"])
def parse(payload: TextIn):
    """자연어를 규칙 기반으로 구조화하고, 부족한 필수 필드를 함께 반환한다(키 불필요)."""
    parsed = core.rule_based_parse(payload.text)
    return {"parsed": parsed, "missing_required": core.missing_required_fields(parsed)}


@app.post("/screen", tags=["screening"])
def screen(customer: CustomerIn):
    """구조화 고객정보를 CSV 하드규칙으로 심사해 결정적 판정을 반환한다(키 불필요 · 핵심).
    같은 입력엔 항상 같은 결과 — 재현성 있는 안전장치."""
    return core.screen_loan(customer.model_dump())


# ---------------------------------------------------------------------------
# 키 필요 엔드포인트 (LLM 3-Agent 파이프라인)
# ---------------------------------------------------------------------------
@app.post("/advise", tags=["screening"])
async def advise(payload: TextIn):
    """자연어 입력으로 3-Agent 파이프라인(파싱→심사→안내)을 실행한다.

    - 필수 정보(월소득·신용등급·희망금액)가 없으면 파이프라인을 돌리기 전에 422로 거른다
      (정보 부족을 '거절'로 오판하거나 비용을 낭비하지 않도록).
    - OPENAI_API_KEY가 없으면 503으로 명확히 안내한다.
    """
    # 값비싼 LLM 호출 전에 규칙 기반으로 필수 필드부터 검증(app.py와 동일한 게이트).
    missing = core.missing_required_fields(core.rule_based_parse(payload.text))
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "필수 정보가 부족합니다.", "missing_required": missing},
        )
    if not core.has_api_key():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY가 설정되지 않아 LLM 파이프라인을 실행할 수 없습니다. "
                   "결정적 심사는 /screen 을 사용하세요.",
        )
    try:
        result = await core.run_service(payload.text)
    except ValueError as e:  # 키 관련 등 명확한 설정 오류
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 — 외부(LLM/네트워크) 오류
        raise HTTPException(status_code=502, detail=f"파이프라인 실행 오류: {e}")
    return result
