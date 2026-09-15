"""규칙 기반 파서 — 자연어를 구조화 후보로 바꾼다. API 키가 필요 없다.

이 파일이 바뀌는 이유는 하나다: 금액·등급 표기를 읽는 규칙이 바뀔 때. 이 파서의 결과는 권위값이
아니라 후보이며, LLM 파서와의 불일치를 사람이 확인해 확정한다(ADR-029).
"""
import re


def _to_won(raw: str, unit: str | None) -> int:
    """숫자 문자열과 단위를 원 단위 정수로 옮긴다.

    단위를 생략하는 관행("월급 700" = 700만원)이 있어 미기재 시 만원으로 본다. 그
    기본값을 콤마 찍힌 전체 금액에도 적용하면 3,000,000이 300억이 되므로, 콤마를
    원 단위 신호로 삼아 막았다. 그런데 콤마는 단위가 아니라 자릿수 구분자다.
    만원 단위로 "10,000"(=1억)을 적는 사람에게 그 규칙은 1만원을 돌려준다. 확대
    방향을 막으면서 축소 방향을 같은 폭만큼 열어 둔 셈이었고, 축소는 상환부담을
    낮게 보이게 하므로 승인 쪽으로 기우는 더 위험한 오차다.

    구분선을 콤마의 유무가 아니라 개수에 둔다. 콤마가 하나면 네 자리 이상 일곱 자리
    미만이고, 이 자리수는 만원 단위 표기에서 흔하다. 콤마가 둘 이상이면 백만 이상이며
    이를 만원으로 읽으면 100억을 넘어 이 서비스의 어떤 항목에도 맞지 않는다. 콤마
    없는 백만 이상도 같은 이유로 원이다.

    남는 구간은 콤마 하나짜리 여섯 자리다("월소득 500,000"). 원 단위 표기지만 만원으로
    읽혀 확대된다. 어떤 표기 규칙도 이 구간을 양쪽 모두 맞출 수 없어, 화면에서 사람이
    금액을 확인하는 단계로 넘긴다.
    """
    num = _to_number(raw)
    if unit:
        return round(num * 10000) if unit.startswith("만") else round(num)
    if raw.count(",") >= 2 or num >= 1_000_000:
        return round(num)
    return round(num * 10000)


def _to_number(raw: str):
    """금액 문자열을 수로 옮긴다 — 소수점이 있을 때만 float를 쓴다.

    "1.5억" 같은 표기 때문에 소수를 받아야 하지만, 정수까지 float로 옮기면 자리수가
    큰 금액이 정확히 되돌아오지 않는다. 정수 원 단위 입력을 전제로 둔 ADR-032가
    그 전제를 잃는다. 그래서 표기에 소수점이 있을 때만 float로 간다.
    """
    digits = raw.replace(",", "")
    return float(digits) if "." in digits else int(digits)


# 한글 수 단위는 곱해서 쌓인다 — "천만"은 천 × 만이고 "백만"은 백 × 만이다. 문자마다
# 배수를 두고 이어 곱하면 조합을 따로 나열하지 않아도 된다.
_UNIT_MULTIPLIER = {"십": 10, "백": 100, "천": 1_000, "만": 10_000, "억": 100_000_000}

# 금액 한 조각 = 숫자 + (수 단위) + (원). 단위 자리는 "천만"처럼 두 글자가 오고,
# 소수점은 "1.5억" 같은 표기 때문에 받는다.
_AMOUNT_PART = re.compile(r"\s*(\d[\d,]*(?:\.\d+)?)\s*([십백천]?[만억])?\s*(원)?")


def _read_amount(text: str, pos: int) -> tuple[int, int] | None:
    """pos에서 시작하는 금액 표현을 읽어 (원 단위 정수, 끝난 위치)를 돌려준다.

    "1억"이 1만원으로 읽히던 원인은 단위 목록에 만원·원만 있어 억이 통째로 버려지고
    단위 미기재로 떨어진 것이었다. 억만 목록에 더하면 "1억 5천만원"이 여전히 틀린다 —
    큰 단위와 작은 단위를 이어 쓰는 것이 한국어 금액 표기의 기본형이기 때문이다.
    그래서 단위 하나를 읽는 대신 조각을 이어 읽어 더한다.

    이어 읽기는 앞 조각이 단위를 가졌을 때만 계속한다. "월 300 부채 500"처럼 단위 없는
    숫자가 연달아 오는 것은 한 금액의 두 조각이 아니라 서로 다른 항목이고, 이어 붙이면
    소득에 부채가 합쳐진다. 그리고 "원"을 만나면 표기가 끝난 것이므로 거기서 멈춘다.
    """
    # 정수만 나오면 total도 정수로 남는다 — float로 시작하면 큰 금액에서 정밀도를
    # 잃는다. 곱셈 결과가 소수인 경우(1.15억)는 아래 round가 받는다.
    total = 0
    saw_unit = False
    matched = False
    while pos < len(text):
        m = _AMOUNT_PART.match(text, pos)
        if not m:
            break
        raw, unit, won = m.group(1), m.group(2), m.group(3)
        pos = m.end()
        if unit:
            multiplier = 1
            for ch in unit:
                multiplier *= _UNIT_MULTIPLIER[ch]
            total += _to_number(raw) * multiplier
            saw_unit = True
            matched = True
            if won:
                break
            continue
        if saw_unit:
            # 단위를 가진 조각 뒤의 단위 없는 숫자는 이 금액의 일부가 아니다.
            pos = m.start()
            break
        total = _to_won(raw, "원" if won else None)
        matched = True
        break
    if not matched:
        # 0원도 읽어 낸 값이다. 못 읽은 것과 구분하지 않으면 "부채 0원"에서
        # 실패로 떨어져, 뒤쪽의 무관한 숫자가 부채로 붙는다.
        return None
    # 1.15억은 부동소수점에서 114999999.99999999로 떨어진다. 버림하면 1원이 모자란
    # 값이 나가므로 반올림한다. 정수만 더해진 total은 round가 그대로 돌려준다.
    return round(total), pos


def parse_korean_amount(text: str, keywords: list, gap: int = 6):
    """키워드<->숫자가 서로 가까이 있으면(양방향 ±gap자 이내) 금액 표기를 원 단위 정수로 추출.
    '월급 700만원'처럼 키워드가 먼저 오는 경우와 '3000만원 대출받고'처럼 숫자가 먼저 오는 경우를 모두 잡는다."""
    for kw in keywords:
        # 방향 1: 키워드 -> 숫자 (예: '월급 700만원', '부채 3000만원')
        # 숫자가 실제로 시작하는 자리를 lookahead로 잡아 거기서부터 금액 표기를 읽는다.
        m = re.search(rf"{kw}[^\d]{{0,{gap}}}(?=\d)", text)
        if m:
            read = _read_amount(text, m.end())
            if read:
                return read[0]
        # 방향 2: 숫자 -> 키워드 (예: '3000만원 대출받고', '1억 5천만원 빌리고')
        # 숫자의 시작 자리마다 금액을 읽어 보고, 그 뒤 gap 안에 키워드가 오면 채택한다.
        # 숫자 도중(콤마·소수점 뒤)에서 다시 읽지 않도록 앞 문자를 배제한다.
        for d in re.finditer(r"(?<![\d,.])\d", text):
            read = _read_amount(text, d.start())
            if not read:
                continue
            value, end = read
            if re.match(rf"[^\d]{{0,{gap}}}{kw}", text[end:]):
                return value
    return None


def rule_based_parse(text: str) -> dict:
    """규칙 기반 파서 — Agent 1(LLM) 산출 검증 및 오프라인 테스트용."""
    월소득 = parse_korean_amount(text, ["월급", "월소득", "소득", "월"]) or 0
    # 부채만 None을 그대로 남긴다. 다른 금액은 0이 곧 미입력이지만 부채는 0이 정상
    # 입력이라, 못 읽은 것을 0으로 채우면 "빚이 없다"와 구분되지 않는다. 실제로
    # "부채 오천만원"처럼 파서가 못 읽는 표기에서 판정이 상담필요→승인가능으로
    # 뒤집혔다. 축소는 상환부담을 낮게 보이게 하므로 승인 쪽으로 기운다.
    부채 = parse_korean_amount(text, ["부채", "빚", "대출.?있"])
    if re.search(r"부채\D{0,6}(없|0)", text):
        부채 = 0
    희망금액 = parse_korean_amount(text, ["희망", "대출받", "빌리", "받고"]) or 0
    g = re.search(r"신용\s*등급\s*(\d+)|(\d+)\s*등급", text)
    신용등급 = int(next(x for x in (g.group(1), g.group(2)) if x)) if g else 99
    직장유형 = "정규직" if "정규직" in text else ("계약직" if "계약직" in text else "제한없음")
    담보긍정 = re.search(r"담보\D{0,6}(있|보유|제공)", text)
    담보부정 = re.search(r"담보\D{0,6}(없|불가)", text)
    담보보유 = bool(담보긍정) and not bool(담보부정)
    return {"월소득": 월소득, "부채": 부채, "신용등급": 신용등급,
            "희망금액": 희망금액, "직장유형": 직장유형, "담보보유": 담보보유}
