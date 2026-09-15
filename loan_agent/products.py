"""상품 데이터 — CSV를 읽어 구조화한다.

이 파일이 바뀌는 이유는 하나다: 상품표의 컬럼이나 값 해석 방식이 바뀔 때. 심사 규칙이나 파서가
바뀌는 것과는 무관하다.
"""
import re
from pathlib import Path

from loan_agent.core import BASE_DIR

# 데이터 파일명을 한글('대출상품.csv') → 영문('loan_products.csv')으로 변경.
#   저장소를 공개했을 때 파일명 인코딩 문제를 피하고 국제적으로 통용되도록 함.
#   (CSV의 컬럼/내용은 한글 그대로 유지 — 도메인 데이터이므로.)
CSV_PATH = BASE_DIR / "loan_products.csv"


def _pct(s: str) -> float:
    """'4.5%' -> 4.5"""
    return float(str(s).replace("%", "").strip())


def _grade(s: str) -> int:
    """'3등급이상' -> 3 / '3등급' -> 3 (숫자가 낮을수록 우량)"""
    m = re.search(r"(\d+)", str(s))
    return int(m.group(1)) if m else 99


def load_products(csv_path: Path = CSV_PATH) -> list:
    """대출상품.csv를 파싱해 구조화 리스트로 반환. pandas 없이 동작."""
    products = []
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header = [h.strip() for h in lines[0].split(",")]
    for line in lines[1:]:
        cols = [c.strip() for c in line.split(",")]
        row = dict(zip(header, cols))
        products.append({
            "상품코드": row["상품코드"],
            "상품명": row["상품명"],
            "은행": row["은행"],
            "최저금리": _pct(row["최저금리"]),
            "최고금리": _pct(row["최고금리"]),
            "최대한도": int(row["최대한도"]),          # 원
            "필요신용등급": _grade(row["필요신용등급"]),  # 이 값 이하(우량)면 충족
            "담보필요": row["담보필요"] == "필요",
            "직장조건": row["직장조건"],                # '정규직' | '제한없음'
            # 금융감독원 「금융상품 한눈에」 공시가 실제로 노출하는 필드를 합성값으로 추가한다
            #   (상환방식·금리방식·중도상환수수료). 최저금리 단일 기준을 넘어선 다기준 상품 랭킹을
            #   시연하기 위한 데이터다.
            #   기존 CSV에 이 컬럼이 없을 수도 있으므로 .get으로 안전하게 읽고 기본값을 둔다.
            "상환방식": row.get("상환방식", "원리금균등"),   # '원리금균등' | '만기일시'
            "금리방식": row.get("금리방식", "변동"),         # '고정' | '변동'
            "중도상환수수료": _pct(row.get("중도상환수수료", "0%")),  # % (낮을수록 유리)
        })
    return products


PRODUCTS = load_products()
