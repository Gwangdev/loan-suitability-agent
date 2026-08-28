#!/usr/bin/env python3
"""게이트 자기 테스트.

임시 저장소를 만들어 gate.py가 잡아야 할 것을 잡고, 잡으면 안 되는 것을 통과시키는지
확인한다. 게이트를 고칠 때마다 실행한다.

    python3 tools/test_gate.py

[피드백1~8] 이 파일의 케이스는 실제로 게이트를 깨뜨린 적이 있는 입력에서 나왔다.
            추측으로 만든 케이스는 넣지 않는다. 새 버그를 고칠 때마다 여기에 한 줄 추가한다.
            예외는 축 A·K10처럼 외부 표준에서 온 검사다. 깨진 적이 없으므로 대신
            **반증 케이스를 함께 넣는다** — 잡는지보다 정상 입력을 통과시키는지가 더 중요하다.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

GATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate.py")
results = []


def run(path, extra=()):
    r = subprocess.run([sys.executable, GATE, path, *extra],
                       capture_output=True, text=True, timeout=300)
    out = r.stdout
    codes = {ln.split("]")[0].split("[")[-1] for ln in out.splitlines() if "[" in ln and "]" in ln}
    blocked = "■" in out
    return codes, blocked, out


def case(name, build, expect_codes=(), forbid_codes=(), expect_block=None, extra=()):
    d = tempfile.mkdtemp(prefix="gate-t-")
    try:
        build(d)
        codes, blocked, out = run(d, extra)
        bad = []
        for c in expect_codes:
            if c not in codes:
                bad.append(f"{c} 미검출")
        for c in forbid_codes:
            if c in codes:
                bad.append(f"{c} 오탐")
        if expect_block is not None and blocked != expect_block:
            bad.append(f"BLOCK={blocked}, 기대={expect_block}")
        results.append((name, bad, out))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def w(d, rel, text=""):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(text)


def git(d, *cmds):
    subprocess.run("git init -q", cwd=d, shell=True)
    subprocess.run("git config user.email t@e.st && git config user.name t", cwd=d, shell=True)
    for c in cmds:
        subprocess.run(c, cwd=d, shell=True, capture_output=True)


# ── 오탐 방지 (통과해야 하는 것) ─────────────────────────────────────────
def b_gitignore(d):
    """[피드백1] .gitignore가 정상 작동하는 저장소를 BLOCK하면 안 된다."""
    w(d, ".gitignore", "__pycache__/\n.venv/\n.env\nbuild/\n")
    w(d, "src/m.py", "def f():\n    return 1\n")
    for junk in ("__pycache__/x.pyc", ".venv/lib/y.py", "build/z.txt", ".env"):
        w(d, junk, "x")
    git(d, "git add -A", "git commit -qm init")


def b_license(d):
    """[피드백2] 파일마다 반복되는 라이선스 헤더는 템플릿 복제가 아니다."""
    for i in range(4):
        w(d, f"A{i}.java", "// Copyright 2026 Example Corp. All rights reserved.\nclass A%d {}\n" % i)
    w(d, ".gitignore", "*.class\n")


def b_symlink(d):
    os.makedirs(os.path.join(d, "a"))
    try:
        os.symlink("../a", os.path.join(d, "a", "loop"))
    except OSError:
        pass
    w(d, ".gitignore", "")


def b_binary(d):
    io.open(os.path.join(d, "blob.py"), "wb").write(os.urandom(3000))
    w(d, ".gitignore", "")


def b_empty(d):
    pass


# ── 검출 (잡아야 하는 것) ────────────────────────────────────────────────
def b_artifacts(d):
    w(d, ".superpowers/state/server.pid", "1")
    w(d, "보고서_생성_프롬프트.md", "x" * 100)
    git(d, "git add -A", "git commit -qm init")


def b_dupcomment(d):
    c = "    # 참조 무결성을 보존하기 위해 존재 여부를 선행 검사한다\n"
    w(d, "a.py", "def a():\n" + c + "    pass\n")
    w(d, "b.py", "def b():\n" + c + "    pass\n")
    w(d, ".gitignore", "")


def b_docstring_singlequote(d):
    """[피드백3] ''' 한 줄 docstring도 커버리지에 세어야 한다."""
    src = "".join("def f%d():\n    '''설명'''\n    return %d\n\n" % (i, i) for i in range(12))
    w(d, "m.py", src)
    w(d, ".gitignore", "")


def b_style_commit(d):
    w(d, "a.py", "x = 1\n")
    w(d, ".gitignore", "")
    git(d, "git add -A", "git commit -qm 'docs: 문서 문체를 학술체로 통일'")


def b_report_no_limits(d):
    body = "본 프로젝트는 데이터 전송 객체(Data Transfer Object, DTO)를 사용하여 목적을 달성하였다. " * 20
    w(d, "project_보고서.md", "# 보고서\n" + body)
    w(d, ".gitignore", "")


def b_report_brief_ok(d):
    """판단·근거·구성이 있는 보고서 브리프는 추가 경고 없이 통과해야 한다."""
    import json
    brief = {
        "version": 1,
        "profile": "technical-project",
        "profile_reason": "코드와 실행 검증이 주된 근거",
        "audience": "백엔드 실습 평가자",
        "decision": "요구사항을 충족하고 재현 가능한가",
        "claims": [{
            "statement": "주문 생성과 재고 차감은 같은 트랜잭션에서 처리된다.",
            "evidence": ["src/OrderService.java:42", "tests/OrderServiceTest.java:81"],
            "status": "verified",
        }],
        "counterevidence": [],
        "outline": ["결론과 핵심 결과", "설계 결정", "검증", "한계"],
        "visuals": [{
            "message": "정상·오류 시나리오의 검증 범위",
            "evidence": ["logs/test-result.txt"],
        }],
    }
    w(d, "prompts/report-brief.json", json.dumps(brief, ensure_ascii=False))
    w(d, ".gitignore", "")


def b_report_brief_missing_judgment(d):
    """독자·의사결정·근거가 빠진 브리프는 보고서 작성 전에 차단해야 한다."""
    import json
    brief = {
        "version": 1,
        "profile": "business-strategy",
        "claims": [{"statement": "시장이 성장한다.", "evidence": [], "status": "verified"}],
        "outline": ["시장 분석"],
    }
    w(d, "prompts/report-brief.json", json.dumps(brief, ensure_ascii=False))
    w(d, ".gitignore", "")


def b_report_brief_decorative_visual(d):
    """메시지나 근거가 없는 장식용 차트는 브리프 단계에서 차단해야 한다."""
    import json
    brief = {
        "version": 1,
        "profile": "brief",
        "profile_reason": "사용자 지정",
        "audience": "사업부 책임자",
        "decision": "이번 분기에 시범 사업을 시작할 것인가",
        "claims": [{
            "statement": "두 고객군에서 반복 수요가 확인되었다.",
            "evidence": ["research/interviews.md:31"],
            "status": "verified",
        }],
        "counterevidence": [],
        "outline": ["결론", "판단 근거", "실행 제안"],
        "visuals": [{"message": "", "evidence": []}],
    }
    w(d, "prompts/report-brief.json", json.dumps(brief, ensure_ascii=False))
    w(d, ".gitignore", "")


def b_report_brief_non_object(d):
    """JSON 루트가 객체가 아니면 검사 예외가 아니라 R0 BLOCK이어야 한다."""
    w(d, "prompts/report-brief.json", "[1, 2, 3]")
    w(d, ".gitignore", "")


def b_report_brief_wrong_types(d):
    """비어 있지 않아도 계약과 다른 타입이면 통과시키지 않는다."""
    import json
    brief = {
        "version": 1,
        "profile": "brief",
        "profile_reason": "사용자 지정",
        "audience": 3,
        "decision": ["결정"],
        "claims": [{"statement": 7, "evidence": "file:1", "status": "verified"}],
        "counterevidence": [],
        "outline": "결론",
        "visuals": [{"message": 9, "evidence": {"file": 1}}],
    }
    w(d, "prompts/report-brief.json", json.dumps(brief, ensure_ascii=False))
    w(d, ".gitignore", "")


def b_report_brief_partial_without_scope(d):
    """부분 검증 주장은 확인 범위와 한계를 생략할 수 없다."""
    import json
    brief = {
        "version": 1,
        "profile": "business-strategy",
        "profile_reason": "사용자 지정",
        "audience": "사업부 책임자",
        "decision": "시범 사업을 시작할 것인가",
        "claims": [{
            "statement": "일부 고객군에서 수요가 확인되었다.",
            "evidence": ["research/interviews.md:31"],
            "status": "partially-verified",
        }],
        "counterevidence": [],
        "outline": ["결론", "근거", "한계"],
    }
    w(d, "prompts/report-brief.json", json.dumps(brief, ensure_ascii=False))
    w(d, ".gitignore", "")


def _w(d, rel, text):
    fp = os.path.join(d, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w", encoding="utf-8").write(text)


def b_spec_match(d):
    """명세와 코드가 일치하면 S3·S4가 나오면 안 된다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n  - GET /api/orders/{id}\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n'
       '    @GetMapping("/{id}")\n    public R one(Long id) { return s.one(id); }\n}\n')


def b_spec_missing(d):
    """명세에 있고 코드에 없으면 누락(S3)."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n  - DELETE /api/orders/{id}\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n}\n')


def b_spec_extra(d):
    """코드에 있고 명세에 없으면 과잉 구현(S4)."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n'
       '    @GetMapping("/{id}/history")\n    public List<H> h(Long id) { return s.h(id); }\n}\n')


def b_spec_pathvar_name(d):
    """경로 변수 이름만 다른 것은 불일치가 아니다. Flask <id>도 같다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/x/{id}\n  - GET /api/y/{id}\n")
    _w(d, "src/a.py",
       '@router.get("/api/x/{orderId}")\ndef x(orderId):\n    return 1\n\n'
       '@app.route("/api/y/<int:id>", methods=["GET"])\ndef y(id):\n    return 2\n')


def b_spec_exclude(d):
    """exclude에 적은 것은 과잉으로 잡지 않는다."""
    _w(d, "SPEC.yaml",
       "version: 1\nendpoints:\n  - GET /api/orders\nexclude:\n"
       "  - endpoint: DELETE /api/orders/{id}\n    reason: framework-provided endpoint\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n'
       '    @DeleteMapping("/{id}")\n    public void d(Long id) { s.d(id); }\n}\n')


def b_spec_code_roots(d):
    """code_roots 밖의 컨트롤러는 공개 표면으로 세지 않는다.

    fixtures/의 컨트롤러는 채점·예제용 데이터이지 이 서비스가 노출하는 표면이
    아니다. 그래서 명세에 없어도 과잉 구현(S4)이 아니다. 동시에 code_roots 안의
    명세 항목은 정상적으로 구현된 것으로 잡혀야 한다(S3도 뜨면 안 된다).
    """
    _w(d, "SPEC.yaml", "version: 1\ncode_roots:\n  - src\nendpoints:\n  - GET /api/orders\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n}\n')
    _w(d, "fixtures/sample/F.java",
       '@RequestMapping("/api/members")\nclass F {\n'
       '    @GetMapping\n    public List<M> list() { return s.list(); }\n'
       '    @PostMapping("/{id}/ban")\n    public void ban(Long id) { s.ban(id); }\n}\n')


def b_spec_code_roots_absent_scans_all(d):
    """code_roots를 안 쓰면 저장소 전체가 대상이다 — 기존 프로젝트의 동작이 바뀌지 않는다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n")
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n}\n')
    _w(d, "fixtures/sample/F.java",
       '@RequestMapping("/api/members")\nclass F {\n'
       '    @GetMapping\n    public List<M> list() { return s.list(); }\n}\n')


def b_spec_code_roots_typo(d):
    """없는 경로를 적으면 설정 오류(S0)로 잡는다.

    이 검사가 없으면 스캔 대상이 통째로 비어 "코드에서 엔드포인트를 찾지 못함"(S3)이
    되는데, 그 안내문은 미구현·미지원 프레임워크를 가리키므로 오타가 미구현으로
    위장된다. 설정 오류와 진행 상태는 다른 사실이라 다르게 보고해야 한다.
    """
    _w(d, "SPEC.yaml", "version: 1\ncode_roots:\n  - src/mian\nendpoints:\n  - GET /api/orders\n")
    _w(d, "src/main/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n}\n')


def b_spec_absent(d):
    """SPEC.yaml이 없으면 이 축은 아무것도 하지 않는다."""
    _w(d, "src/C.java",
       '@RequestMapping("/api/orders")\nclass C {\n'
       '    @GetMapping\n    public List<R> list() { return s.list(); }\n}\n')


def b_spec_reqmapping(d):
    """[피드백] 메서드 수준 @RequestMapping을 클래스 기준 경로로 오인해
    정상 코드에 없는 누락(S3)을 만들어냈다. 다중 verb 지정도 함께 본다."""
    _w(d, "SPEC.yaml",
       "version: 1\nendpoints:\n  - GET /api/items\n"
       "  - POST /api/orders/{id}/lock\n  - DELETE /api/orders/{id}/lock\n")
    _w(d, "src/NoBase.java",
       'class NoBase {\n'
       '    @RequestMapping(value = "/api/items", method = RequestMethod.GET)\n'
       '    public List<Item> list() { return s.list(); }\n}\n')
    _w(d, "src/Mix.java",
       '@RequestMapping("/api/orders")\nclass Mix {\n'
       '    @RequestMapping(value = "/{id}/lock", method = {RequestMethod.POST, RequestMethod.DELETE})\n'
       '    public void lock(Long id) { s.lock(id); }\n}\n')


def b_leak_label(d):
    """미해결 라벨이 제출물에 남으면 완료 불가(L1)."""
    _w(d, "docs/report.md", "# \ubcf4\uace0\uc11c\n\ucc98\ub9ac\ub7c9\uc740 \ucd08\ub2f9 1200\uac74\uc774\ub2e4. [\ubbf8\uac80\uc99d]\n")


def b_leak_tag(d):
    """\ud558\ub124\uc2a4 \ub0b4\ubd80 \ud0dc\uadf8\uac00 \ucf54\ub4dc\uc5d0 \ub0a8\uc73c\uba74 \uc81c\ucd9c \ubd88\uac00(L2)."""
    _w(d, "src/A.java",
       "public class A {\n    // [\ud53c\ub4dc\ubc317] \uc608\uc804\uc5d4 \uc120\ud589 \uac80\uc0ac\ub97c \ud588\ub2e4.\n    void f() {}\n}\n")


def b_leak_harness_ok(d):
    """\ud558\ub124\uc2a4 \uc790\uc2e0\uc758 \ud30c\uc77c\uc5d0 \ub4e4\uc5b4\uc788\ub294 \ub77c\ubca8\u00b7\ud0dc\uadf8\ub294 \uc624\ud0d0\uc774\ub2e4."""
    _w(d, "PROJECT_STATE.md", "## Open Labels\n- `[\ubbf8\uac80\uc99d]`:\n- `[\ud655\uc778 \ud544\uc694]`:\n")
    _w(d, "PROJECT_LOG.md", "| 1 | \uc0ac\uc6a9\uc790 | \uc9c0\uc801 | \uc870\uce58 |\n")
    _w(d, "tools/test_gate.py", '"""[\ud53c\ub4dc\ubc311] \ub3c4\uad6c \ud30c\uc77c\uc740 \uc81c\uc678\ub41c\ub2e4."""\n')
    _w(d, "reference/code-tell-checklist.md", "\uc608\uc2dc: [\ud53c\ub4dc\ubc31N] \uc8fc\uc11d\n")


def b_secret_key_format(d):
    """발급 기관이 형식을 고정한 키는 형식만으로 자격증명임이 증명된다(X1)."""
    _w(d, "src/config.py",
       "AWS_KEY = \"AKIAIOSFODNN7EXAMPLE\"\n"
       "def client():\n    return AWS_KEY\n")


def b_secret_assigned_literal(d):
    """이름이 자격증명인 변수에 문자열을 직접 넣은 자리(X1)."""
    _w(d, "src/db.properties",
       "spring.datasource.url=jdbc:postgresql://localhost:5432/app\n"
       "spring.datasource.password=\"Gg7!vQ2mLp0x\"\n")


def b_secret_placeholder_ok(d):
    """자리표시자와 환경변수 참조는 값이 아니다 — 잡으면 축 전체가 꺼진다."""
    _w(d, "src/settings.py",
       "import os\n"
       "PASSWORD = os.environ[\"DB_PASSWORD\"]\n"
       "API_KEY = os.getenv(\"API_KEY\", \"\")\n"
       "SECRET = \"your-secret-here\"\n"
       "TOKEN = \"changeme12345\"\n")
    _w(d, "src/app.yaml",
       "database:\n  password: ${DB_PASSWORD}\n  api_key: <your-api-key>\n")


def b_secret_doc_example_ok(d):
    """문서에 적은 예시 문자열은 유출 경로가 아니다. 검사 자체를 설명해야 한다."""
    _w(d, "docs/guide.md",
       "게이트는 `AKIAIOSFODNN7EXAMPLE` 같은 형식을 X1으로 잡는다.\n\n"
       "## 한계\n문서는 검사 대상이 아니다.\n")


def b_infra_exposed_data_tier(d):
    """데이터 계층이 호스트 포트를 열면 앱을 거치지 않는 경로가 생긴다(I1·I5)."""
    _w(d, "compose.yaml",
       "services:\n"
       "  api:\n"
       "    image: myapp:1\n"
       "    user: \"1000:1000\"\n"
       "    read_only: true\n"
       "    networks: [front, back]\n"
       "  db:\n"
       "    image: postgres:16\n"
       "    ports:\n"
       "      - \"5432:5432\"\n"
       "    user: \"999:999\"\n"
       "    read_only: true\n"
       "    networks: [front]\n"
       "networks:\n"
       "  front: {}\n"
       "  back:\n"
       "    internal: true\n")


def b_infra_depends_without_healthcheck(d):
    """의존 선언만 있고 대상에 상태 확인이 없으면 준비 상태는 보장되지 않는다(I3)."""
    _w(d, "docker-compose.yml",
       "services:\n"
       "  api:\n"
       "    image: myapp:1\n"
       "    user: \"1000\"\n"
       "    read_only: true\n"
       "    depends_on:\n"
       "      db:\n"
       "        condition: service_started\n"
       "  db:\n"
       "    image: postgres:16\n"
       "    user: \"999\"\n"
       "    read_only: true\n")


def b_infra_compose_ok(d):
    """반증: 격리·상태 확인·권한이 갖춰진 구성은 잡히지 않아야 한다."""
    _w(d, "compose.yaml",
       "services:\n"
       "  api:\n"
       "    image: myapp:1\n"
       "    user: \"1000:1000\"\n"
       "    read_only: true\n"
       "    networks:\n"
       "      - front\n"
       "      - back\n"
       "    depends_on:\n"
       "      db:\n"
       "        condition: service_healthy\n"
       "  db:\n"
       "    image: postgres:16\n"
       "    user: \"999:999\"\n"
       "    read_only: true\n"
       "    networks:\n"
       "      - back\n"
       "    healthcheck:\n"
       "      test: [\"CMD-SHELL\", \"pg_isready -U app\"]\n"
       "networks:\n"
       "  front: {}\n"
       "  back:\n"
       "    internal: true\n")


def b_infra_no_compose_ok(d):
    """반증: 배포 구성이 없는 프로젝트에서 이 축이 돌면 안 된다."""
    _w(d, "src/app.py", "def add(a, b):\n    return a + b\n")


def b_health_static(d):
    """정적 200 헬스체크는 DB가 죽어도 healthy로 보인다(I3)."""
    _w(d, "src/api.py",
       "from flask import Flask\n"
       "app = Flask(__name__)\n\n\n"
       "@app.route(\"/health\")\n"
       "def health():\n"
       "    return {\"status\": \"ok\"}, 200\n")


def b_health_checks_dependency_ok(d):
    """반증: 의존 자원을 실제로 확인하는 헬스체크는 잡히지 않아야 한다."""
    _w(d, "src/api.py",
       "from flask import Flask\n"
       "app = Flask(__name__)\n\n\n"
       "@app.route(\"/health\")\n"
       "def health():\n"
       "    with pool.connection() as conn:\n"
       "        conn.execute(\"SELECT 1\")\n"
       "    return {\"status\": \"ok\"}, 200\n")


def b_secret_compare_plain(d):
    """비밀값을 일반 비교로 대조하면 시간차가 샌다(I4)."""
    _w(d, "src/auth.py",
       "import os\n\n\n"
       "def check(admin_token):\n"
       "    return admin_token == os.environ[\"ADMIN_TOKEN\"]\n")


def b_secret_compare_safe_ok(d):
    """반증: 상수 시간 비교와 존재 확인은 잡히지 않아야 한다."""
    _w(d, "src/auth.py",
       "import hmac\n"
       "import os\n\n\n"
       "def check(admin_token):\n"
       "    if admin_token == None:\n"
       "        return False\n"
       "    return hmac.compare_digest(admin_token, os.environ[\"ADMIN_TOKEN\"])\n")


def b_secret_bare_env(d):
    """인용부호 없는 목록형 환경변수도 값이 박힌 것은 같다(X1)."""
    _w(d, "compose.yaml",
       "services:\n"
       "  db:\n"
       "    image: postgres:16\n"
       "    environment:\n"
       "      - POSTGRES_PASSWORD=Gg7vQ2mLp0x\n")


def b_secret_bare_env_ref_ok(d):
    """반증: 환경변수 참조는 값이 아니다."""
    _w(d, "compose.yaml",
       "services:\n"
       "  db:\n"
       "    image: postgres:16\n"
       "    environment:\n"
       "      - POSTGRES_PASSWORD=${DB_PASSWORD}\n")


def b_test_coverage_gap(d):
    """T1은 테스트 파일이 하나라도 있으면 통과한다. 항목별 누락은 T2가 본다."""
    _w(d, "SPEC.yaml",
       'version: 1\nendpoints:\n  - GET /api/orders\n  - GET /api/orders/{id}\n')
    _w(d, "src/api.py",
       '@router.get("/api/orders")\ndef list_orders():\n    return svc.list()\n\n'
       '@router.get("/api/orders/{id}")\ndef get_order(id):\n    return svc.get(id)\n')
    _w(d, "tests/test_api.py",
       'def test_list():\n    assert client.get("/api/orders").status_code == 200\n')


def b_test_coverage_ok(d):
    """항목마다 경로를 참조하는 테스트가 있으면 뜨지 않는다."""
    _w(d, "SPEC.yaml",
       'version: 1\nendpoints:\n  - GET /api/orders\n  - GET /api/orders/{id}\n')
    _w(d, "src/api.py",
       '@router.get("/api/orders")\ndef list_orders():\n    return svc.list()\n\n'
       '@router.get("/api/orders/{id}")\ndef get_order(id):\n    return svc.get(id)\n')
    _w(d, "tests/test_api.py",
       'def test_list():\n    assert client.get("/api/orders").status_code == 200\n\n'
       'def test_get():\n    assert client.get("/api/orders/7").status_code == 200\n')


def b_test_coverage_code_roots(d):
    """code_roots 밖의 테스트는 우리 항목을 충족하지 않는다.

    check_spec이 그 경로의 코드를 보지 않으므로 T2도 같은 범위여야 한다. 범위가
    어긋나면 예제·픽스처의 테스트가 우리 명세를 덮어 미탐이 된다.
    """
    _w(d, "SPEC.yaml",
       'version: 1\ncode_roots:\n  - app\nendpoints:\n  - GET /api/orders\n')
    _w(d, "app/api.py",
       '@router.get("/api/orders")\ndef list_orders():\n    return svc.list()\n')
    _w(d, "samples/tests/test_sample.py",
       'def test_list():\n    assert client.get("/api/orders").status_code == 200\n')


def _spec_project(d, test_ok=True, extra_src=""):
    _w(d, "SPEC.yaml",
       'version: 1\ntest_command: "python3 -m unittest discover -s tests -q"\n'
       'endpoints:\n  - GET /api/orders\n  - GET /api/orders/{id}\n')
    _w(d, "src/api.py",
       '@router.get("/api/orders")\ndef list_orders():\n'
       '    """\uc8fc\ubb38 \ubaa9\ub85d\uc744 \ubc18\ud658\ud55c\ub2e4."""\n    return svc.list()\n' + extra_src)
    body = "self.assertTrue(True)" if test_ok else "self.assertEqual(1, 2)"
    _w(d, "tests/test_api.py",
       "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        " + body + "\n")


def b_commit_pending_ok(d):
    """\ubbf8\uad6c\ud604 \uba85\uc138 \ud56d\ubaa9(S3)\uc740 \uac1c\ubc1c \uc911 \uc815\uc0c1 \u2014 \ucee4\ubc0b\uc744 \ub9c9\uc9c0 \uc54a\ub294\ub2e4."""
    _spec_project(d, test_ok=True)


def b_commit_test_fail(d):
    """\ud14c\uc2a4\ud2b8\uac00 \uc2e4\ud328\ud558\uba74 \ucee4\ubc0b \ubd88\uac00(V1)."""
    _spec_project(d, test_ok=False)


def b_commit_no_testcmd(d):
    """test_command\uac00 \uc5c6\uc73c\uba74 \uae30\uacc4 \uac80\uc99d \ubd88\uac00\ub97c \uacbd\uace0\ud55c\ub2e4."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n")
    _w(d, "src/api.py", '@router.get("/api/orders")\ndef list_orders():\n    return svc.list()\n')


def b_changeset(d):
    """--changeset\uc740 \ubbf8\ucee4\ubc0b \ubcc0\uacbd\uc744 \uba85\uc138 \ud56d\ubaa9\ubcc4\ub85c \ubb36\uace0,
    \uc5d4\ub4dc\ud3ec\uc778\ud2b8\uac00 \uc5c6\ub294 \ud30c\uc77c\uc740 \ubbf8\ubd84\ub958\ub85c \ub0a8\uae34\ub2e4."""
    w(d, ".gitignore", "")
    git(d, "git add .gitignore", "git commit -q -m init")
    w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n  - POST /api/orders\n")
    w(d, "src/L.java", '@RequestMapping("/api/orders")\nclass L {\n    @GetMapping\n    public List<R> l() { return s.l(); }\n}\n')
    w(d, "src/C.java", '@RequestMapping("/api/orders")\nclass C {\n    @PostMapping\n    public R c() { return s.c(); }\n}\n')
    w(d, "src/cfg/Cfg.java", "class Cfg {}\n")


def _deck(d, **over):
    import json as _j
    n = over.get("n", 5)
    good = over.get("good", True)
    slides = []
    for i in range(1, n + 1):
        if good:
            items = [{"text": "\ubd88\ub7c9\ub960 3% \ucd08\uacfc \uc2dc \ub77c\uc778 \uc815\uc9c0",
                      "threshold": "3%", "failure_mode": "\uc13c\uc11c \uace0\uc7a5\uc774\uba74 \uc624\ud310"},
                     {"text": "\uc218\uc728 \ud655\uc778", "failure_mode": "\ud638\uae30\ubcc4 \ud3b8\ucc28 \ubb34\uc2dc \uc2dc \uc655\uace1"}]
            items = items[: (2 if i % 2 else 1)]
            if i == 1:
                items.append({"text": "\uacf5\uc815 \ub370\uc774\ud130\uc5d0\uc11c \uc7ac\uac80\uc0ac \uc774\ub825\uc744 \ubcc4\ub3c4 \ubcf4\uad00\ud558\uace0 \uc124\ube44 \uc9c4\ub3d9 \uac12\uacfc \ub300\uc870",
                              "threshold": "10\ud68c", "failure_mode": "\uc591\uc0b0 \ucd08\uae30 \ub370\uc774\ud130\ub294 \ud45c\ubcf8 \ubd80\uc871"})
        else:
            items = [{"text": "\ub2e4\uc591\ud55c \ubc29\ubc95\uc73c\ub85c \ud6a8\uacfc\uc801\uc73c\ub85c \ucc98\ub9ac\ud568"}] * 4
        slides.append({"id": f"s{i}", "kind": "technique",
                       "title": f"\uacf5\uc815 {i}",
                       "subtitle": "\ud1b5\uacc4\uc801 \uc774\uc0c1\uacfc \uacf5\uc815\uc0c1 \uc774\uc0c1\uc740 \uac19\uc9c0 \uc54a\uc74c",
                       "probe": "\uc5b4\ub290 \ucabd\uc744 \uba3c\uc800 \ubcf4\ub294\uac00?",
                       "blocks": [{"label": "How", "items": items}]})
    _w(d, over.get("name", "deck.json"),
       _j.dumps({"meta": {"title": "t", "audience": "3\ub144\ucc28 \uacf5\uc815 \ubd84\uc11d\uac00",
                          "home_domain": "manufacturing", "version": "1"},
                 "slides": slides}, ensure_ascii=False))


def b_deck_ok(d):
    """\ud310\ub2e8\u00b7\uc2e4\ud328\uc870\uac74\u00b7\ube44\ub300\uce6d\uc744 \uac16\ucd98 \ub371\uc740 \ud1b5\uacfc\ud574\uc57c \ud55c\ub2e4."""
    _deck(d, good=True)


def b_deck_ai(d):
    """\ud310\ub2e8 \uc5c6\uc74c\u00b7\uc644\uc804 \ub300\uce6d\u00b7\uc218\uc2dd\uc5b4 \ub371\uc740 \ucc28\ub2e8\ub41c\ub2e4."""
    _deck(d, good=False)


def b_deck_absent(d):
    """deck.json\uc774 \uc5c6\uc73c\uba74 \uc774 \ucd95\uc740 \ub3d9\uc791\ud558\uc9c0 \uc54a\ub294\ub2e4."""
    _w(d, "src/a.py", "def f():\n    return 1\n")


def _it_deck(d, scattered):
    """IT \uac15\uc758\ub294 \uc8fc\uc81c\uc5b4\uac00 \uc804 \uc2ac\ub77c\uc774\ub4dc\uc5d0 \uae54\ub9b0\ub2e4.
    subject_domain\uc744 \ube7c\uc9c0 \uc54a\uc73c\uba74 \uadf8\uac83\uc774 \uce74\uc6b4\ud2b8\ub97c \ud3ec\ud654\uc2dc\ucf1c K8\uc774 \ubb34\ub825\ud574\uc9c4\ub2e4."""
    import json as _j
    ex = ([("\uc8fc\ubb38 \uc0dd\uc131\uacfc \uc7ac\uace0 \ucc28\uac10\uc744 \ud55c \ud2b8\ub79c\uc7ad\uc158\uc73c\ub85c \ubb36\uc74c", "\uc678\ubd80 api \ud638\ucd9c\uc774 \ub4e4\uc5b4\uac00\uba74 \ucee4\ub125\uc158 \uace0\uac08"),
           ("\uc7a5\ubc14\uad6c\ub2c8 \uc870\ud68c\ub294 \ud1a0\ud070 \uc778\uac00\ub85c \ucc98\ub9ac", "\ud1a0\ud070 \ub9cc\ub8cc \uc2dc \uad6c\ub9e4 \uc774\ud0c8"),
           ("\uc8fc\ubb38 \ubaa9\ub85d \uc5d4\ub4dc\ud3ec\uc778\ud2b8\uc5d0 \ubcf5\ud569 \uc778\ub371\uc2a4", "\uc804\ud658\uc728 \uc9d1\uacc4 \ubc30\uce58\uac00 \ub290\ub824\uc9d0"),
           ("\ucee8\ud14c\uc774\ub108 \uc774\ubbf8\uc9c0 \ud0dc\uadf8\ub97c \uace0\uc815", "\ub9c8\uc774\uadf8\ub808\uc774\uc158\uc774 \ube44\uac00\uc5ed\uc774\uba74 \ub86c\ubc31 \ubd88\uac00")]
          if not scattered else
          [("\ud658\uc790 \uc9c4\ub2e8 \uae30\ub85d \uc800\uc7a5\uc744 \ud55c \ud2b8\ub79c\uc7ad\uc158\uc73c\ub85c \ubb36\uc74c", "\uc784\uc0c1 \ub370\uc774\ud130\uac00 \ud06c\uba74 \ub77d \ub300\uae30"),
           ("\uc5ec\uc2e0 \uc2ec\uc0ac \uc870\ud68c\ub294 \ud1a0\ud070 \uc778\uac00\ub85c \ucc98\ub9ac", "\uc5f0\uccb4 \uc815\ubcf4 \uad8c\ud55c \ubd84\ub9ac \uc2e4\ud328"),
           ("\uac00\uc785\uc790 \uc774\ud0c8 \uc9d1\uacc4\uc5d0 \ubcf5\ud569 \uc778\ub371\uc2a4", "\uc694\uae08\uc81c \ubcc0\uacbd \ud2b8\ub798\ud53d\uc5d0 \uac31\uc2e0 \uc9c0\uc5f0"),
           ("\ubbfc\uc6d0 \ucc98\ub9ac \uc2dc\uc2a4\ud15c \uc778\ud5c8\uac00 \ubc30\ud3ec", "\ud589\uc815 \uc138\uc218 \ub9c8\uac10\uc77c\uacfc \uacb9\uce68")])
    sl = [{"id": f"s{i}", "kind": "technique", "title": f"\uc8fc\uc81c {i}",
           "subtitle": "\uacbd\uacc4\ub97c \uc5b4\ub514\uc5d0 \ub458 \uac83\uc778\uac00\uac00 \uc9c8\ubb38\uc784",
           "probe": "\uc774 \uacbd\uacc4\ub97c \uc5b4\ub514\uc5d0 \ub458 \uac83\uc778\uac00?",
           "blocks": [{"label": "How", "items": [
               {"text": t, "threshold": "200ms", "failure_mode": f}]}]}
          for i, (t, f) in enumerate(ex, 1)]
    _w(d, "deck.json", _j.dumps(
        {"meta": {"title": "t", "audience": "\ubc31\uc5d4\ub4dc \uac1c\ubc1c\uc790",
                  "subject_domain": "it", "home_domain": "ecommerce", "version": "1"},
         "slides": sl}, ensure_ascii=False))


def b_deck_it_ok(d):
    _it_deck(d, scattered=False)


def b_deck_it_scattered(d):
    _it_deck(d, scattered=True)


def b_report_overused(d):
    """[D5] 과용 표현이 밀도 높게 반복되면 문장이 서로 구별되지 않는다.
    한계 절은 이 케이스의 관심사가 아니므로 아예 두지 않는다(D2 WARN은 무방하다)."""
    para = ("이 기능을 통해 문제를 해결하였다. 이 결과를 바탕으로 다음 단계를 진행한다. "
            "중요한 것은 안정성이다. 종합적으로 효율적인 개선이 기대된다. ") * 8
    w(d, "project_보고서.md", "# 보고서\n" + para)
    w(d, ".gitignore", "")


def b_report_overused_ok(d):
    """자연스러운 1~2회 사용은 밀도가 낮아 걸리지 않아야 한다."""
    body = ("승인 실패율은 4.1%에서 0.7%로 내려갔다. 이 결과를 바탕으로 임계값을 조정했다. " +
            "타임아웃 재시도는 3회까지 허용했다. 5xx 오류만 재시도 대상으로 제한했다. " * 15)
    w(d, "project_보고서.md", "# 보고서\n" + body)
    w(d, ".gitignore", "")


def b_report_nominal_limits(d):
    """[D6] '한계'라는 낱말만 있고 본문이 없는 형식적 한계 절은 D2를 통과해도 D6이 잡는다."""
    body = "승인 실패율은 4.1%에서 0.7%로 내려갔다. " * 20
    w(d, "project_보고서.md", "# 보고서\n" + body + "\n## 한계\n특별한 한계는 없다.\n")
    w(d, ".gitignore", "")


def b_report_real_limits(d):
    """실제 분량이 있는 한계 절은 D2·D6 모두 통과해야 한다. D6 임계값(200자)을
    여유 있게 넘기도록 근거를 하나 더 채운다."""
    body = "승인 실패율은 4.1%에서 0.7%로 내려갔다. " * 20
    limits = ("정기결제와 해외 카드 승인은 검증하지 않았다. 스테이징 트래픽이 운영의 12% 수준이라 "
              "서킷 브레이커 임계값은 운영 반영 후 재측정이 필요하다. 지수 백오프의 p99 지연 증가가 "
              "결제 이탈률에 미치는 영향은 이번 범위에서 측정하지 못했다. 카드사 응답이 지역별로 "
              "달라지는지도 이번 검증 범위에 포함하지 않았다. 부분 환불과 취소 후 재승인 흐름은 "
              "이번 시나리오에 포함하지 않았으며 별도 검증이 필요하다.")
    w(d, "project_보고서.md", "# 보고서\n" + body + "\n## 한계\n" + limits + "\n")
    w(d, ".gitignore", "")


def _min_pdf(text_lines, box="0 0 595 842"):
    """의존성 없이 pdftotext가 읽을 수 있는 최소 PDF를 직접 조립한다."""
    content = "BT /F1 10 Tf 50 780 Td\n"
    for ln in text_lines:
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content += f"({esc}) Tj 0 -14 Td\n"
    content += "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] /Resources "
        "<< /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out = ["%PDF-1.4"]
    offsets = [0]
    body = "%PDF-1.4\n"
    for i, o in enumerate(objs, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n{o}\nendobj\n"
    xref_off = len(body)
    body += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n"
    for off in offsets[1:]:
        body += f"{off:010d} 00000 n \n"
    body += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_off}\n%%EOF"
    return body


def _has_pdftotext():
    return shutil.which("pdftotext") is not None


def b_artifact_pdf_no_md(d):
    """[E1] PDF만 있고 같은 이름의 .md가 없다 — 편집 가능한 원본이 없다."""
    w(d, "output/보고서.pdf", _min_pdf(["결론과 핵심 결과", "승인 실패율 0.7%"]))


def b_artifact_pdf_no_html(d):
    """[E2] PDF와 .md는 있지만 .html 미리보기가 없다."""
    w(d, "output/보고서.md", "# 결론과 핵심 결과\n\n승인 실패율 0.7%\n")
    w(d, "output/보고서.pdf", _min_pdf(["결론과 핵심 결과", "승인 실패율 0.7%"]))


def b_artifact_diverged(d):
    """[E3] Markdown의 제목이 PDF 본문에 없다 — 둘을 따로 작성했다는 신호.
    핸드메이드 PDF는 표준 Helvetica라 한글 추출이 보장되지 않으므로 헤딩은
    영문으로 둔다. E3의 판정 로직은 언어와 무관하므로 검증에 지장이 없다."""
    w(d, "output/보고서.md",
      "# Conclusion Summary\n\n## Scenario Verification\n\n## Limitations\n\n" +
      "내용. " * 60)
    w(d, "output/보고서.html", "<html></html>")
    w(d, "output/보고서.pdf", _min_pdf(["Unrelated Different Title", "different body"]))


def b_artifact_consistent(d):
    """Markdown 제목이 PDF에 그대로 있으면 E1~E3 모두 통과해야 한다."""
    w(d, "output/보고서.md",
      "# Conclusion Summary\n\n## Scenario Verification\n\n## Limitations\n\n" +
      "정기결제는 검증하지 않았다. " * 10)
    w(d, "output/보고서.html", "<html></html>")
    w(d, "output/보고서.pdf",
      _min_pdf(["Conclusion Summary", "Scenario Verification", "Limitations",
                "recurring billing was not verified"] * 3))


def _chrome_bin():
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "google-chrome", "chromium", "chromium-browser"):
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        elif shutil.which(c):
            return c
    return None


def b_artifact_pdf_overused(d):
    """[D7] PDF 본문에도 D1·D5 축이 그대로 적용되어야 한다.
    핸드메이드 PDF는 표준 Helvetica라 한글이 정상 추출된다는 보장이 없으므로,
    이 케이스만은 실제 렌더 경로(Chrome headless)로 진짜 PDF를 만든다.
    report-exec-harness.md §5가 Chrome을 필수로 요구하므로 이 환경 의존은 정당하다."""
    para = ["이 기능을 통해 문제를 해결하였다.", "이 결과를 바탕으로 다음 단계를 진행한다.",
            "중요한 것은 안정성이다.", "종합적으로 효율적인 개선이 기대된다."] * 6
    md = "# 결론\n\n" + " ".join(para)
    w(d, "output/보고서.md", md)
    html_path = os.path.join(d, "output", "보고서.html")
    w(d, "output/보고서.html", "<meta charset='utf-8'><body>" + " ".join(para) + "</body>")
    chrome = _chrome_bin()
    pdf_path = os.path.join(d, "output", "보고서.pdf")
    if chrome:
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path}", html_path],
                       capture_output=True, timeout=60)
    if not os.path.isfile(pdf_path):
        w(d, "output/보고서.pdf", _min_pdf(["Chrome 없음 — D7 실환경 검증 불가"]))


def b_artifact_pdf_wrong_size(d):
    """[D8] report.css가 A4를 정의하는데 PDF가 다른 판형이면 조판이 토큰을 어겼다."""
    w(d, "output/보고서.md", "# Conclusion Summary\n\n" + "내용. " * 30)
    w(d, "output/보고서.html", "<html></html>")
    # US Letter: 612 x 792pt — A4(595 x 842)와 확실히 다르다
    w(d, "output/보고서.pdf",
      _min_pdf(["Conclusion Summary", "body"], box="0 0 612 792"))


def _consistent_md_pdf(d):
    """E1~E3가 통과하는 md/pdf 쌍. E5 격리용 — html의 본문 구조만 바꿔 재사용한다."""
    w(d, "output/보고서.md",
      "# Conclusion Summary\n\n## Scenario Verification\n\n## Limitations\n\n" +
      "정기결제는 검증하지 않았다. " * 10)
    w(d, "output/보고서.pdf",
      _min_pdf(["Conclusion Summary", "Scenario Verification", "Limitations",
                "recurring billing was not verified"] * 3))


def b_artifact_modern_no_row_aside(d):
    """[E5] l-modern인데 report.css의 .row/.aside 비대칭 구조를 한 번도 안 씀 —
    본문을 풀폭으로 쌓아 세로 공간을 낭비하는 실패 모드(재현: Day_20 사례)."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-orange l-modern">'
      '<section class="sheet cover"><div class="cover-head"><h1 class="title">t</h1></div></section>'
      '<section class="sheet"><h1>Conclusion Summary</h1>'
      '<figure><img src="a.png"><figcaption>그림 1</figcaption></figure>'
      '</section></body>')


def b_artifact_modern_with_aside(d):
    """l-modern이면서 .row/.aside를 쓰면 E5가 나지 않는다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-orange l-modern">'
      '<section class="sheet cover"><div class="cover-head"><h1 class="title">t</h1></div></section>'
      '<section class="sheet"><div class="row"><div><h1>Conclusion Summary</h1>'
      '<figure><img src="a.png"><figcaption>그림 1</figcaption></figure></div>'
      '<aside class="aside"><div class="note">측정 조건</div></aside></div>'
      '</section></body>')


def b_artifact_formal_no_row_aside(d):
    """[E5] l-formal도 .row/.aside 2단 구조를 쓴다. 주석열이 좌측이라는 것만 다르다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-vermilion l-formal">'
      '<section class="sheet cover"><h1 class="title">t</h1></section>'
      '<section class="sheet"><h1>Conclusion Summary</h1>'
      '<figure><img src="a.png"><figcaption>그림 1</figcaption></figure>'
      '</section></body>')


def b_artifact_inline_style(d):
    """[E6] 인라인 style은 조판 값을 report.css 밖에 두는 것이라 예외 없이 막는다.
    실제로 figure의 max-width·span의 폰트·각주의 색이 인라인으로 새어 있었다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-vermilion l-formal">'
      '<section class="sheet"><div class="row"><div class="body">'
      '<h1>Conclusion Summary</h1>'
      '<figure style="max-width: 88mm"><img src="a.png"></figure>'
      '<p style="color:#5C5C5C">각주</p></div>'
      '<aside class="aside">측정 조건</aside></div></section></body>')


def b_artifact_bottom_overflow(d):
    """[E7] 하단 여백을 넘긴 쪽. 육안 검토가 놓치는 실패라 좌표로만 잡힌다.
    l-formal의 --mb는 28mm이므로 콘텐츠 하한은 269mm다. 그 아래까지 줄을 흘린다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-vermilion l-formal">'
      '<section class="sheet"><div class="row"><div class="body">'
      '<h1>Conclusion Summary</h1><h2>Scenario Verification</h2>'
      '<h2>Limitations</h2></div><aside class="aside">측정 조건</aside>'
      '</div></section></body>')
    w(d, "output/보고서.pdf",
      _min_pdf(["Conclusion Summary", "Scenario Verification", "Limitations",
                "recurring billing was not verified"]
               + ["overflow line"] * 55))


def b_artifact_formal_ok(d):
    """판면 안에 있고 .row/.aside를 쓰고 인라인 style이 없으면 아무것도 막지 않는다.
    E7은 이 경우에도 하단 여유를 INFO로 보고하므로 코드 부재가 아니라
    BLOCK 부재로 확인한다 — 여유 수치 자체가 조판 검수에 필요한 값이다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-vermilion l-formal">'
      '<section class="sheet cover"><h1 class="title">t</h1></section>'
      '<section class="sheet g2"><div class="row"><div class="body">'
      '<h1>Conclusion Summary</h1><h2>Scenario Verification</h2></div>'
      '<aside class="aside">측정 조건<span class="src">출처</span></aside>'
      '</div></section></body>')


def b_artifact_classic_no_row_aside(d):
    """l-classic은 애초에 단일 단이므로 .row/.aside가 없어도 정상이다."""
    _consistent_md_pdf(d)
    w(d, "output/보고서.html",
      '<body class="report t-black l-classic">'
      '<section class="sheet cover"><div class="cover-head"><h1 class="title">t</h1></div></section>'
      '<section class="sheet"><h1>Conclusion Summary</h1>'
      '<figure><img src="a.png"><figcaption>그림 1</figcaption></figure>'
      '</section></body>')


def b_artifact_stale(d):
    """[E4] 승인 후 고친 .md가 PDF보다 새로우면 재렌더가 필요하다."""
    w(d, "output/보고서.pdf", _min_pdf(["Conclusion Summary"] * 3))
    w(d, "output/보고서.html", "<html></html>")
    import time
    time.sleep(1.1)
    w(d, "output/보고서.md", "# Conclusion Summary\n\n" + "내용. " * 60)


def b_api_verb_in_uri(d):
    """[A1] URI에 동사가 들어간 명세는 설계 단계에서 잡는다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - POST /api/create-order\n")
    _w(d, "src/a.py", '@router.post("/api/create-order")\ndef x():\n    return 1\n')


def b_api_bulk_delete(d):
    """[A4] 컬렉션 전체 DELETE는 한 번의 오작동으로 데이터셋을 지운다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - DELETE /api/orders\n")
    _w(d, "src/a.py", '@router.delete("/api/orders")\ndef x():\n    return 1\n')


def b_api_bulk_delete_with_reason(d):
    """[A4 반증] 사유를 단 일괄 삭제는 의도된 설계이므로 통과해야 한다.

    사유 없는 노출만 결함이다. 사유를 요구하는 것이 이 축의 목적이고,
    막는 것 자체가 목적이 아니다.
    """
    _w(d, "SPEC.yaml",
       "version: 1\nendpoints:\n  - endpoint: DELETE /api/sessions\n"
       "    reason: 만료 세션 일괄 정리 — 관리자 권한·감사 로그 적용\n")
    _w(d, "src/a.py", '@router.delete("/api/sessions")\ndef x():\n    return 1\n')


def b_api_clean_spec(d):
    """[A 반증] 관례를 지킨 명세에서 A축이 하나도 울리면 안 된다.

    `POST /api/orders`의 orders처럼 뒤에 변수가 오지 않는 컬렉션과,
    address(ss로 끝나는 단수)가 오탐을 내지 않는지 함께 본다.
    """
    _w(d, "SPEC.yaml",
       "version: 1\nendpoints:\n  - GET /api/orders\n  - POST /api/orders\n"
       "  - GET /api/orders/{id}\n  - PUT /api/orders/{id}\n"
       "  - GET /api/customers/{id}/orders\n  - GET /api/customers/{id}/address\n")
    _w(d, "src/a.py",
       '@router.get("/api/orders")\ndef a():\n    return 1\n\n'
       '@router.post("/api/orders")\ndef b():\n    return 1\n\n'
       '@router.get("/api/orders/{id}")\ndef c():\n    return 1\n\n'
       '@router.put("/api/orders/{id}")\ndef e():\n    return 1\n\n'
       '@router.get("/api/customers/{id}/orders")\ndef f():\n    return 1\n\n'
       '@router.get("/api/customers/{id}/address")\ndef g():\n    return 1\n')


def b_wrap_split_deck(d):
    """[K10] 슬라이드 텍스트를 어절 중간에서 끊은 줄바꿈."""
    _w(d, "deck.json", json.dumps({
        "meta": {"title": "t", "audience": "a", "subject_domain": "it"},
        "slides": [{"id": "s1", "kind": "technique", "title": "결측 처리",
                    "subtitle": "결측은 설비 상태의 신호임",
                    "probe": "특정 호기에만 몰렸다면 결측인가 고장인가?",
                    "blocks": [{"label": "How", "items": [
                        {"text": "결측 10% 이하면 공정 데이터\n에서 row 제거",
                         "threshold": "10%",
                         "failure_mode": "특정 라인에 몰리면 그 라인이 통째로 사라짐"}]}]}]},
        ensure_ascii=False))


def b_wrap_ok_deck(d):
    """[K10 반증] 어절 경계에서 접은 줄바꿈은 잡지 않는다.

    「할 수」의 '수'처럼 한 글자짜리 정상 어절이 오탐을 내지 않는지 함께 본다.
    """
    _w(d, "deck.json", json.dumps({
        "meta": {"title": "t", "audience": "a", "subject_domain": "it"},
        "slides": [{"id": "s1", "kind": "technique", "title": "결측 처리",
                    "subtitle": "결측은 설비 상태의 신호임",
                    "probe": "특정 호기에만 몰렸다면 결측인가 고장인가?",
                    "blocks": [{"label": "How", "items": [
                        {"text": "공정 데이터에서\n결측 10% 이하면 row 제거",
                         "threshold": "10%",
                         "failure_mode": "라인 단위로 볼 수\n있어야 판정 가능"}]}]}]},
        ensure_ascii=False))


def b_spec_broken(d):
    """명세가 깨졌으면 조용히 넘기지 않는다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - 이건 엔드포인트가 아니다\n")
    _w(d, "src/C.java", 'class C {}\n')


def b_spec_mixed_invalid(d):
    """유효 항목 사이의 오타도 조용히 버리지 않는다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\n  - 잘못된 항목\n")
    _w(d, "src/a.py", '@router.get("/api/orders")\ndef x():\n    return 1\n')


def b_spec_exclude_without_reason(d):
    """사유 없는 exclude는 공개 표면 대조를 우회하므로 차단한다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n  - GET /api/orders\nexclude:\n  - GET /health\n")
    _w(d, "src/a.py", '@router.get("/api/orders")\ndef x():\n    return 1\n')


def b_spec_empty(d):
    """빈 endpoints 목록은 공개 HTTP 표면이 없는 프로젝트에서 축을 끈다."""
    _w(d, "SPEC.yaml", "version: 1\nendpoints:\n")
    _w(d, "src/C.java", 'class C {}\n')


CASES = [
    # 이름,                     빌더,                    기대,           금지,             BLOCK
    ("빈 디렉터리",             b_empty,                 (),             ("H1", "C1"),     False),
    ("바이너리 .py",            b_binary,                (),             ("C1", "C3"),     False),
    ("심볼릭 링크 순환",        b_symlink,               (),             (),               False),
    (".gitignore 정상 저장소",  b_gitignore,             (),             ("H1", "H2"),     False),
    ("라이선스 헤더 반복",      b_license,               (),             ("C3",),          False),
    ("도구 흔적·프롬프트 동봉", b_artifacts,             ("H1",),        (),               True),
    ("동일 주석 복제",          b_dupcomment,            ("C3",),        (),               True),
    ("''' 한 줄 docstring",     b_docstring_singlequote, ("C2",),        (),               False),
    ("문체 정규화 커밋",        b_style_commit,          ("G3",),        (),               True),
    ("약어 병기·한계 절 부재",  b_report_no_limits,      ("D1", "D2"),   (),               None),
    ("과용 표현 밀집",          b_report_overused,       ("D5",),        (),               False),
    ("과용 표현 자연 사용",     b_report_overused_ok,    (),             ("D5",),          None),
    ("형식적 한계 절",          b_report_nominal_limits, ("D6",),        (),               True),
    ("실질적 한계 절",          b_report_real_limits,    (),             ("D6",),          None),
    ("PDF만 있고 .md 없음",     b_artifact_pdf_no_md,    ("E1",),        (),               True),
    ("PDF·md 있고 .html 없음",  b_artifact_pdf_no_html,  ("E2",),        (),               True),
    ("md와 PDF 내용 불일치",    b_artifact_diverged,     ("E3",),        (),               True),
    ("PDF 본문 과용 표현",      b_artifact_pdf_overused, ("D7",),        ("E1", "E2"),     False),
    ("PDF 판형이 A4가 아님",    b_artifact_pdf_wrong_size, ("D8",),      ("E1", "E2", "E3"), False),
    ("modern인데 row/aside 없음", b_artifact_modern_no_row_aside, ("E5",), (),              False),
    ("modern + row/aside 사용",  b_artifact_modern_with_aside,   (),      ("E5",),          None),
    ("classic은 row/aside 불필요", b_artifact_classic_no_row_aside, (),   ("E5",),          None),
    ("formal인데 row/aside 없음", b_artifact_formal_no_row_aside, ("E5",), (),              False),
    ("보고서 HTML에 인라인 style", b_artifact_inline_style,       ("E6",), (),              True),
    ("하단 여백 침범",           b_artifact_bottom_overflow,     ("E7",), (),              True),
    ("formal 정상 조판",         b_artifact_formal_ok,           (),      ("E5", "E6"),     False),
    ("md·html·PDF 일관",       b_artifact_consistent,   (),             ("E1", "E2", "E3"), None),
    ("md가 PDF보다 최신",       b_artifact_stale,        ("E4",),        (),               False),
    ("보고서 브리프: 판단 구조", b_report_brief_ok,       (),               ("R0", "R1", "R2", "R3"), None),
    ("보고서 브리프: 판단 누락", b_report_brief_missing_judgment, ("R1", "R2"), (),          True),
    ("보고서 브리프: 장식 차트", b_report_brief_decorative_visual, ("R3",),  (),               True),
    ("보고서 브리프: 비객체 JSON", b_report_brief_non_object, ("R0",),       (),               True),
    ("보고서 브리프: 잘못된 타입", b_report_brief_wrong_types, ("R1", "R2", "R3"), (),        True),
    ("보고서 브리프: 부분 검증 범위", b_report_brief_partial_without_scope, ("R2",), (),          True),
    ("명세 일치",               b_spec_match,            (),             ("S3", "S4"),     None),
    ("명세 누락",               b_spec_missing,          ("S3",),        ("S4",),          True),
    ("명세 대비 과잉 구현",     b_spec_extra,            ("S4",),        ("S3",),          True),
    ("경로 변수명만 다름",      b_spec_pathvar_name,     (),             ("S3", "S4"),     None),
    ("exclude 지정",            b_spec_exclude,          (),             ("S4",),          None),
    ("code_roots 밖은 표면 아님", b_spec_code_roots,      (),             ("S3", "S4"),     None),
    ("code_roots 반증: 없으면 전체", b_spec_code_roots_absent_scans_all, ("S4",), (),       True),
    ("code_roots 오타는 설정 오류", b_spec_code_roots_typo, ("S0",),      ("S3",),          True),
    ("SPEC.yaml 없음",          b_spec_absent,           (),             ("S3", "S4", "S0"), None),
    ("SPEC.yaml 빈 표면",       b_spec_empty,            (),             ("S3", "S4", "S0"), None),
    ("메서드 수준 @RequestMapping", b_spec_reqmapping,   (),             ("S3", "S4"),     None),
    ("라벨 유출(제출물)",       b_leak_label,            ("L1",),        (),               True),
    ("내부 태그 유출(코드)",    b_leak_tag,              ("L2",),        (),               True),
    ("하네스 파일은 제외",      b_leak_harness_ok,       (),             ("L1", "L2"),     None),
    ("보안: 키 형식 그대로",     b_secret_key_format,     ("X1",),        (),               True),
    ("보안: 변수에 박은 값",     b_secret_assigned_literal, ("X1",),      (),               True),
    ("보안 반증: 자리표시자",    b_secret_placeholder_ok, (),             ("X1",),          False),
    ("보안 반증: 문서의 예시",   b_secret_doc_example_ok, (),             ("X1",),          False),
    ("인프라: 데이터 계층 포트 노출", b_infra_exposed_data_tier, ("I1", "I5"), (),   False),
    ("인프라: 준비 상태 미확인",  b_infra_depends_without_healthcheck, ("I3",), (),   False),
    ("인프라 반증: 격리된 구성",  b_infra_compose_ok,      (),   ("I1", "I2", "I3", "I5"), False),
    ("인프라 반증: 구성 없음",    b_infra_no_compose_ok,   (),   ("I1", "I2", "I3", "I5"), False),
    ("인프라: 정적 헬스체크",     b_health_static,         ("I3",),        (),               False),
    ("인프라 반증: 의존 확인 헬스체크", b_health_checks_dependency_ok, (), ("I3",),          False),
    ("인프라: 비밀값 일반 비교",  b_secret_compare_plain,  ("I4",),        (),               False),
    ("인프라 반증: 상수 시간 비교", b_secret_compare_safe_ok, (),          ("I4",),          False),
    ("보안: 인용부호 없는 환경변수", b_secret_bare_env,     ("X1",),        (),               True),
    ("보안 반증: 환경변수 참조",  b_secret_bare_env_ref_ok, (),            ("X1",),          False),
    ("테스트: 항목별 누락",      b_test_coverage_gap,     ("T2",),        (),               False),
    ("테스트 반증: 항목별 존재", b_test_coverage_ok,      (),             ("T2",),          False),
    ("테스트: code_roots 밖은 불인정", b_test_coverage_code_roots, ("T2",),   ("S3", "S4"),     False),
    ("덱: 판단 갖춘 스펙",      b_deck_ok,               (),             ("K1","K2","K6"), None),
    ("덱: AI 지문 스펙",        b_deck_ai,               ("K1","K2","K6"), (),             True),
    ("덱: deck.json 없음",      b_deck_absent,           (),             ("K0","K1","K2"), None),
    ("덱: IT주제+예시 일관",    b_deck_it_ok,            (),             ("K8",),          None),
    ("덱: IT주제+예시 순회",    b_deck_it_scattered,     ("K8",),        (),               None),
    ("API: URI에 동사",         b_api_verb_in_uri,       ("A1",),        (),               True),
    ("API: 컬렉션 일괄 삭제",   b_api_bulk_delete,       ("A4",),        (),               True),
    ("API: 사유 있으면 통과",   b_api_bulk_delete_with_reason, (),       ("A4",),          False),
    ("API 반증: 정상 명세",     b_api_clean_spec,        (),   ("A1", "A2", "A3", "A4", "A5"), False),
    ("줄바꿈: 어절 쪼갬",       b_wrap_split_deck,       ("K10",),       (),               False),
    ("줄바꿈 반증: 정상 개행",  b_wrap_ok_deck,          (),             ("K10",),         False),
    ("SPEC.yaml 형식 오류",     b_spec_broken,           ("S0",),        (),               True),
    ("SPEC.yaml 혼합 오타",      b_spec_mixed_invalid,    ("S0",),        (),               True),
    ("exclude 사유 누락",        b_spec_exclude_without_reason, ("S0",),    (),               True),
    ("커밋: 미구현은 통과",     b_commit_pending_ok,     ("S3",),        ("S4", "L1", "L2"), False, ("--commit",)),
    ("커밋: 테스트 실패 차단",  b_commit_test_fail,      ("V1",),        (),               True,  ("--commit",)),
    ("커밋: test_command 부재", b_commit_no_testcmd,     ("V1",),        (),               False, ("--commit",)),
]

for row in CASES:
    case(*row)

# --changeset\uc740 findings\uac00 \uc544\ub2c8\ub77c \uc870\ud68c \ucd9c\ub825\uc774\ubbc0\ub85c \ubcc4\ub3c4\ub85c \ubcf8\ub2e4.
_d = tempfile.mkdtemp(prefix="gate-t-")
try:
    b_changeset(_d)
    _out = subprocess.run([sys.executable, GATE, _d, "--changeset"],
                          capture_output=True, text=True, timeout=120).stdout
    _bad = []
    for need in ("GET /api/orders", "POST /api/orders", "src/L.java", "src/C.java"):
        if need not in _out:
            _bad.append(f"{need} \ub204\ub77d")
    if "src/cfg/Cfg.java" not in _out or "\ubbf8\ubd84\ub958" not in _out:
        _bad.append("\ubbf8\ubd84\ub958 \uadf8\ub8f9 \ub204\ub77d")
    if "2 feature group(s)" not in _out:
        _bad.append("\uadf8\ub8f9 \uc218 \ubd88\uc77c\uce58")
    results.append(("--changeset \uae30\ub2a5\ubcc4 \ubb36\uc74c", _bad, _out))
finally:
    shutil.rmtree(_d, ignore_errors=True)

# E9는 ROOT가 아니라 게이트 자신의 reference/report.css를 읽으므로, 임시 폴더를
# 만드는 case() 틀로는 못 흔든다. 하네스 사본을 통째로 떠서 그 CSS를 실제로 어긋나게
# 고친 뒤 돌린다 — 검사기를 만든 것만으로는 안전망이 아니고, 어겼을 때 실제로 걸리는지
# 확인해야 안전망이다.
_d = tempfile.mkdtemp(prefix="gate-t-")
try:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    shutil.copytree(os.path.join(_root, "reference"), os.path.join(_d, "reference"))
    shutil.copytree(_here, os.path.join(_d, "tools"))
    _css_path = os.path.join(_d, "reference", "report.css")
    _css = io.open(_css_path, encoding="utf-8").read()
    # 실제로 났던 버그를 그대로 재현한다: g2에서 1안용 본문 인셋을 지우는 걸 빠뜨려
    # 주석열이 있는 절의 본문만 밀려 시작했다.
    _broken = _css.replace(
        ".l-formal .sheet.g2 .row:not(.full) > .body { padding-left: 0; }",
        ".l-formal .sheet.g2 .row:not(.full) > .body { padding-left: 3.4mm; }")
    _bad = []
    if _broken == _css:
        _bad.append("규칙 문자열을 못 찾음 — 선택자가 바뀌었으면 CSS_RULES도 함께 고칠 것")
    io.open(_css_path, "w", encoding="utf-8").write(_broken)
    _out = subprocess.run([sys.executable, os.path.join(_d, "tools", "gate.py"), _d],
                          capture_output=True, text=True, timeout=120).stdout or ""
    if "[E9]" not in _out:
        _bad.append("E9 미검출")
    if "■" not in _out:
        _bad.append("BLOCK 아님")
    results.append(("E9 반증: report.css 들여쓰기 규칙 훼손", _bad, _out))
finally:
    shutil.rmtree(_d, ignore_errors=True)

# 어절 단위 줄바꿈도 같은 성격이다 — 규칙을 지워도 조판은 그대로 나오기 때문에
# 육안 검토를 그냥 통과한다. 깨지는 건 한글뿐이므로 영문 위주로 보면 끝까지 안 보인다.
_d = tempfile.mkdtemp(prefix="gate-t-")
try:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    shutil.copytree(os.path.join(_root, "reference"), os.path.join(_d, "reference"))
    shutil.copytree(_here, os.path.join(_d, "tools"))
    _css_path = os.path.join(_d, "reference", "report.css")
    _css = io.open(_css_path, encoding="utf-8").read()
    _broken = _css.replace("word-break: keep-all;", "word-break: break-all;", 1)
    _bad = []
    if _broken == _css:
        _bad.append("규칙 문자열을 못 찾음 — 선택자가 바뀌었으면 CSS_RULES도 함께 고칠 것")
    io.open(_css_path, "w", encoding="utf-8").write(_broken)
    _out = subprocess.run([sys.executable, os.path.join(_d, "tools", "gate.py"), _d],
                          capture_output=True, text=True, timeout=120).stdout or ""
    if "[E9]" not in _out:
        _bad.append("E9 미검출")
    if "■" not in _out:
        _bad.append("BLOCK 아님")
    results.append(("E9 반증: 어절 줄바꿈 규칙 훼손", _bad, _out))
finally:
    shutil.rmtree(_d, ignore_errors=True)

# ── X2 반증: semgrep 출력 파싱 ───────────────────────────────────────────
# 도구가 설치되지 않은 환경에서는 X2가 항상 "미설치" WARN으로 끝나므로, 파싱 경로가
# 깨져 있어도 아무도 모른다. 실제로 죽은 코드가 되기 쉬운 자리다. 스텁을 PATH에
# 앞세워 판정 경로(ERROR→BLOCK, WARNING→WARN)까지 돌려 본다.
_d = tempfile.mkdtemp(prefix="gate-t-")
try:
    os.makedirs(os.path.join(_d, "bin"))
    os.makedirs(os.path.join(_d, "src"))
    io.open(os.path.join(_d, "src", "app.py"), "w", encoding="utf-8").write(
        "def run(cmd):\n    return cmd\n")
    io.open(os.path.join(_d, "SPEC.yaml"), "w", encoding="utf-8").write(
        'version: 1\ntest_command: ""\nendpoints:\n')
    _stub = os.path.join(_d, "bin", "semgrep")
    io.open(_stub, "w", encoding="utf-8").write(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'results': [\n"
        "  {'path': 'src/app.py', 'start': {'line': 2},\n"
        "   'check_id': 'python.lang.security.audit.dangerous-subprocess-use',\n"
        "   'extra': {'severity': 'ERROR'}},\n"
        "  {'path': 'src/app.py', 'start': {'line': 1},\n"
        "   'check_id': 'python.lang.best-practice.unspecified-encoding',\n"
        "   'extra': {'severity': 'WARNING'}}]}))\n")
    os.chmod(_stub, 0o755)
    _env = dict(os.environ, PATH=os.path.join(_d, "bin") + os.pathsep + os.environ["PATH"])
    _out = subprocess.run([sys.executable, GATE, _d, "--commit"], env=_env,
                          capture_output=True, text=True, timeout=300).stdout or ""
    _bad = []
    if "[X2]" not in _out:
        _bad.append("X2 미검출")
    if "high-severity" not in _out:
        _bad.append("ERROR를 BLOCK으로 올리지 못함")
    if "medium-severity" not in _out:
        _bad.append("WARNING을 WARN으로 내지 못함")
    if "■" not in _out:
        _bad.append("BLOCK 아님")
    if "dangerous-subprocess-use" not in _out:
        _bad.append("규칙 id를 보여주지 않음 — 어디를 고칠지 알 수 없다")
    results.append(("X2 반증: semgrep 출력 파싱", _bad, _out))
finally:
    shutil.rmtree(_d, ignore_errors=True)

fail = [r for r in results if r[1]]
print()
for name, bad, _ in results:
    print(f"  {'FAIL' if bad else ' ok '}  {name}" + (f"   ← {', '.join(bad)}" if bad else ""))
print(f"\n{len(results) - len(fail)}/{len(results)} 통과\n")
if fail:
    for name, bad, out in fail:
        print(f"── {name} ──\n{out}")
sys.exit(1 if fail else 0)
