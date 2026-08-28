"""이미지를 열어 보지 않고 배치를 판정한다.

이미지 배치를 판단하는 데 필요한 건 픽셀이 아니라 둘뿐이다. 가로세로 비율(파일
헤더로 충분)과 이미지의 **종류**(작성자가 안다). 이 둘만 있으면 렌더 폭을 배정하고,
그 폭에서 원본 글자가 읽히는지, 쪽이 넘치는지까지 전부 계산으로 끝난다. 렌더 검수
때 PNG를 눈으로 열어 보는 루프를 없애는 게 목적이다.

토큰이 실제로 줄어든다. 다만 "파일명을 미리 적어서"가 아니라 **"판정에 픽셀이 필요
없어서"**다. 배치·판독성·쪽 넘침 셋 다 헤더 정보만으로 계산되고, 렌더 후에는 gate.py
E7이 좌표로 다시 확인한다.

**캡션은 이렇게 뺄 수 없다.** "그림 6은 Materialized View 조회 결과다" 같은 문장은
실제로 그 화면을 본 뒤에만 쓸 수 있다. 그 경계가 이 도구의 적용 범위다.

사용
----
    python3 tools/image_plan.py plan.json
    python3 tools/image_plan.py plan.json --axis formal-full

plan.json 형식 (경로는 이 파일이 아니라 plan.json 기준의 상대 경로다):

    {
      "axis": "formal",
      "pages": [
        {"no": 4, "title": "Q1 — 전폭 1장", "full": true, "text_h": 60,
         "rows": [[["images/img03.png", "terminal"]]]},
        {"no": 7, "title": "Q4 — 2x2 벡터", "full": true, "text_h": 55,
         "rows": [[["charts/c1.svg", "vector"], ["charts/c2.svg", "vector"]],
                  [["charts/c3.svg", "vector"], ["charts/c4.svg", "vector"]]]}
      ]
    }

`full`은 그 쪽이 `.row.full`(주석열 없이 판면 전폭)을 쓴다는 뜻이다. 본문열 폭으로
계산하면 실제 렌더보다 빡빡한 값이 나와 계획과 렌더가 어긋난다. 마크업과 같은 폭으로
맞춘다. `text_h`는 그 쪽 본문 서술이 차지할 세로 높이(mm) 추정치다.

종료코드: 판독 실패나 쪽 넘침이 있으면 1, 없으면 0
"""
import json
import os
import re
import struct
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "reference", "report.css")

KIND = {
    # 터미널·EXPLAIN 덤프는 글자가 조밀하고 대비가 낮으므로 가장 깐깐하게 본다.
    "terminal": {"min_w_mm": 100, "readable_ratio": 18.6},
    # DB 그리드는 셀 텍스트가 터미널보다 커서 같은 축소비에도 아직 읽힌다.
    "grid": {"min_w_mm": 70, "readable_ratio": 24.0},
    # 래스터 차트는 선과 라벨 위주라 글자 밀도가 낮으므로 축소에 더 강하다.
    "chart": {"min_w_mm": 50, "readable_ratio": 32.0},
    # 벡터는 픽셀이 없어 축소가 판독성을 못 깎는다. 최소 폭만 남긴 건 너무 작으면
    # 요소끼리 겹치기 때문이다.
    "vector": {"min_w_mm": 30, "readable_ratio": float("inf")},
}


def _mm(text, name, scope):
    """report.css의 한 규칙 블록에서 mm 토큰 하나를 읽는다.

    반드시 그 블록의 닫는 중괄호까지만 본다 — 범위를 안 자르면 값이 없는 블록에서
    파일 뒤쪽의 다른 축 값을 주워 온다(.l-classic에 --body-w가 없다고 .l-formal의
    127.3mm를 읽어 오는 식이다).
    """
    i = text.find(scope)
    if i < 0:
        return None
    end = text.find("}", i)
    block = text[i:end if end > 0 else len(text)]
    m = re.search(re.escape("--" + name) + r":\s*([\d.]+)mm", block)
    return float(m.group(1)) if m else None


def axis_geometry(axis):
    """조판 축 이름 → (본문열 폭, 전폭, 세로 가용 공간, 단 간격) mm."""
    css = open(CSS, encoding="utf-8").read()
    scope = {"classic": ".l-classic", "modern": ".l-modern",
             "formal": ".l-formal {", "formal-g2": ".l-formal .sheet.g2",
             "formal-g3": ".l-formal .sheet.g3"}.get(axis)
    if scope is None:
        sys.exit(f"모르는 조판 축: {axis} (classic·modern·formal·formal-g2·formal-g3)")
    # g2/g3가 좌우 여백만 재정의하므로 상하 여백은 .l-formal 블록에서 읽어야 한다.
    base = ".l-formal {" if axis.startswith("formal") else scope
    # classic·modern은 단 폭을 자기 블록에 두지 않기 때문에 .report 공통 스케일로 되돌린다.
    body_w = _mm(css, "body-w", scope) or _mm(css, "body-w", ".report {")
    gap = _mm(css, "gap", scope) or _mm(css, "gap", ".report {")
    aside_w = _mm(css, "aside-w", scope) or _mm(css, "aside-w", ".report {")
    mt, mb = _mm(css, "mt", base), _mm(css, "mb", base)
    return body_w, body_w + gap + aside_w, 297.0 - mt - mb, gap


def png_size(path):
    """PNG IHDR 청크에서 픽셀 크기만 읽는다. 전체 디코드를 하지 않는다."""
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG가 아니다: {os.path.basename(path)}")
    return struct.unpack(">II", head[16:24])


def svg_size(path):
    """SVG의 viewBox에서 종횡비 판단용 치수를 읽는다.

    벡터는 픽셀 해상도가 없다 — viewBox 단위를 가상 px로 취급해도 readable_ratio가
    inf이므로 결과에 영향을 주지 않는다. 종횡비 계산에만 쓴다.
    """
    text = open(path, encoding="utf-8").read()
    m = re.search(r'viewBox="\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)', text)
    if not m:
        raise ValueError(f"viewBox가 없다: {os.path.basename(path)}")
    return float(m.group(1)), float(m.group(2))


def read_size(path):
    return svg_size(path) if path.lower().endswith(".svg") else png_size(path)


def plan_row(images, col_mm, gap, base_dir):
    """한 행에 N장을 균등폭으로 배치했을 때의 판독 결과."""
    n = len(images)
    if n == 0:
        return []
    each_w = (col_mm - gap * (n - 1)) / n
    out = []
    for name, kind in images:
        if kind not in KIND:
            sys.exit(f"모르는 이미지 종류: {kind} ({' · '.join(KIND)})")
        w_px, h_px = read_size(os.path.join(base_dir, name))
        rule = KIND[kind]
        ratio = w_px / each_w
        out.append({
            "name": os.path.basename(name), "kind": kind,
            "render_w": each_w, "render_h": each_w / (w_px / h_px),
            "ratio": ratio, "limit": rule["readable_ratio"],
            "readable": each_w >= rule["min_w_mm"] and ratio <= rule["readable_ratio"],
        })
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    plan_path = args[0]
    base_dir = os.path.dirname(os.path.abspath(plan_path))
    doc = json.load(open(plan_path, encoding="utf-8"))
    axis = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--axis=")),
                doc.get("axis", "formal"))
    body_w, full_w, page_h, gap = axis_geometry(axis)

    print(f"조판 축 {axis} — 본문열 {body_w:.1f}mm · 전폭 {full_w:.1f}mm · "
          f"세로 가용 {page_h:.0f}mm")
    print(f"{'쪽':<4} {'슬롯':<26} {'종류':<9} {'렌더폭':>7} {'렌더높이':>8} "
          f"{'축소비':>7} {'허용':>6}  판정")
    print("-" * 88)

    bad = 0
    for page in doc["pages"]:
        col_mm = full_w if page.get("full") else body_w
        total_h = 0.0
        for row in page["rows"]:
            cells = plan_row(row, col_mm, gap, base_dir)
            total_h += max((c["render_h"] for c in cells), default=0) + 4  # 캡션·행간
            for c in cells:
                if not c["readable"]:
                    bad += 1
                limit = "-" if c["limit"] == float("inf") else f"{c['limit']:5.1f}x"
                print(f"{page['no']:<4} {c['name'][:26]:<26} {c['kind']:<9} "
                      f"{c['render_w']:6.0f}mm {c['render_h']:7.0f}mm "
                      f"{c['ratio']:6.1f}x {limit:>6}  "
                      f"{'OK' if c['readable'] else '✗ 판독 실패'}")
        text_h = page.get("text_h", 0)
        over = total_h + text_h > page_h
        if over:
            bad += 1
        print(f"     └ {page.get('title', '')}: 이미지 {total_h:.0f}mm + 본문추정 "
              f"{text_h:.0f}mm / 가용 {page_h:.0f}mm"
              f"{'  ✗ 쪽 넘침' if over else '  OK'}\n")

    if bad:
        print(f"경고 {bad}건 — 렌더 전에 슬롯을 다시 짠다")
        return 1
    print("전 슬롯 판독·배치 이상 없음 — 렌더로 넘어간다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
