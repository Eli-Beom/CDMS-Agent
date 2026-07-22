# CDMS-Agent

Maven CDMS(임상시험 데이터 관리 시스템) 브라우저 세션을 Python/Jupyter에서 원격 조작하고,
CRF(TypeScript) 소스로부터 검증 시나리오/노트북을 자동 생성하는 로컬 RPA 도구.

> 오랜만에 다시 실행한다면 바로 [How to Run](#how-to-run-오랜만에-다시-실행할-때) 섹션으로 이동하세요.

---

## Architecture

3개의 컴포넌트가 로컬에서 서로 통신한다.

```
Jupyter / Python (cdm_agent_client)
    │  HTTP  (기본 http://127.0.0.1:3200)
    ▼
CDM Agent Daemon  (Node/Express, daemon/)
    │  WebSocket
    ▼
Chrome Extension  (extension/, service-worker + content-script)
    │  chrome.tabs.sendMessage / chrome.debugger
    ▼
browser-runner-core.js  (CDMS 페이지 안에서 실행되는 DOM 조작 코어)
```

| 컴포넌트 | 역할 | 위치 |
|---|---|---|
| `cdm-agent-client` (Python) | `CDMSAgent` 클라이언트 + CRF 분석/노트북 생성 파이프라인 | [src/cdm_agent_client/](src/cdm_agent_client/) |
| CDM Agent Daemon | 로컬 HTTP/WebSocket 서버. Python ↔ 브라우저 중계, 세션/케이스 저장 | [daemon/](daemon/) *(별도 git 저장소, 아래 참고)* |
| Chrome Extension | 사이드패널 UI + CDMS 탭에서 DOM 조작 실행 | [extension/](extension/) |

> **daemon/ 은 이 저장소가 아니라 별도 git 저장소(`cdm-agent-platform`)를 이 폴더 안에 체크아웃해 둔 것**이다.
> `CDMS-Agent`의 `git status`에는 `daemon/` 전체가 통째로 untracked 항목 하나로만 보인다.
> `daemon/` 안에서 커밋/푸시를 하려면 `daemon/` 디렉터리에서 별도로 git 작업을 해야 한다.

---

## Repository Layout

```
CDMS-Agent/
├── src/cdm_agent_client/        # Python 패키지 (pip install -e 대상)
│   ├── client.py                #   CDMSAgent — 브라우저 제어 HTTP 클라이언트
│   ├── models.py                #   PageSnapshot, StepResult, PageList
│   ├── exceptions.py            #   CDMAgentError 계열
│   └── crf/                     #   CRF(TypeScript) 소스 기반 분석/생성 파이프라인
│       ├── extractor.py / parser.py   # CRF TS 소스 → spec 추출/파싱
│       ├── simulator.py               # 조건식 → 테스트 입력값 시뮬레이션
│       ├── runner.py / models.py      # CRFRunner, CRFPlan, CRFCase
│       ├── run.py                     # CRFRun — 생성된 케이스를 CDMSAgent로 실행
│       ├── notebook.py / org_notebook.py  # gen_notebook() — 검증 Jupyter 노트북 생성
│       ├── doctor.py                  # cdms-crf doctor — 브라우저 없이 정적 진단
│       ├── audit.py                   # Phase0 감사, query 케이스 감사
│       ├── availability_discovery*.py # 필드 활성/비활성 조건 탐색
│       ├── rule_discovery*.py         # Query 트리거 규칙 탐색
│       ├── trigger_matcher.py / row_matcher.py / taxonomy.py
│       ├── candidate_prerequisites.py / overrides.py / value_planner.py
│       ├── value_generators/          # 타입별(나이, 숫자 등) 테스트값 생성기
│       └── cli.py / __main__.py       # cdms-crf-notebook / cdms-crf CLI 진입점
│
├── extension/                   # Chrome Extension (개발 소스, load unpacked 대상)
│   ├── manifest.json
│   ├── service-worker.js        #   daemon과 WebSocket 연결, CDP 권한 관리
│   ├── content-script.js        #   탭 ↔ service-worker 메시지 중계
│   ├── browser-runner-core.js   #   CDMS 페이지에서 실행되는 DOM 조작 코어
│   └── sidepanel.*               #   사이드패널 UI
│
├── daemon/                      # ⚠️ 별도 git 저장소(cdm-agent-platform) 체크아웃
│   ├── src/cdm-agent/            #   TypeScript 서버 소스 (CdmsAgent.service, BrowserBridge ...)
│   │   └── storage/AgentStore.ts #   SQLite(schema-v2) 저장소 — 아래 "SQL 스키마" 참고
│   ├── public/cdm-agent/         #   daemon이 정적 서빙하는 브라우저 브릿지 두 가지
│   │   ├── chrome-extension/     #     extension/ 사본(참고용, extension/이 원본) — 실제 사용 중인 경로
│   │   └── tampermonkey/         #     Tampermonkey userscript 브릿지 — 대안으로 만들어졌으나 실사용 안 함 (아래 참고)
│   ├── docs/schema-v2.sqlite.sql #   SQLite 스키마 정의 (projects/studies/test_cases/execution_runs/memories ...)
│   └── package.json              #   npm run dev / build / start
│
├── notebooks/                   # 예시/PoC 노트북 (quickstart.ipynb 등)
├── tests/                       # pytest — crf 파이프라인 단위 테스트
├── docs/                        # API 문서(html), 개발 보고서(dev.report/), PPT 작업 산출물
├── data/cdms_agent.sqlite       # daemon이 생성한 SQLite 파일 — 아래 "SQL 스키마" 참고 (gitignore 대상)
├── CLAUDE.md                    # Claude Code용 프로젝트 컨텍스트 (아키텍처/이슈 노트)
├── SKILL.md                     # Claude Code 스킬: CRF 노트북 생성 워크플로
├── pyproject.toml               # Python 패키지 정의 (hatchling)
└── package.json                 # 루트 npm 스크립트 (daemon 위임)
```

정리 대상으로 눈에 띄는 것들 (당장은 정리하지 않고 남겨둠, 후임자가 판단해서 정리):
- 루트의 `avail_candidates.json`, `avail_debug.json`, `avail_result*.json`, `avail_step_debug*.json` — 2026-06-10 즈음 `availability_discovery` 디버깅 중 남은 1회성 덤프로 보임. 코드에서 참조하지 않음.
- `daemon/.claude/worktrees/` 아래 두 개의 완전한 nested git 워크트리(festive-elion-*, trusting-williamson-*) — daemon 쪽 저장소의 잔여물. daemon은 별도 저장소이므로 daemon 쪽에서 직접 확인 후 정리 필요.

### Tampermonkey 브릿지 (미사용)

`daemon/public/cdm-agent/tampermonkey/cdm-agent.user.js`는 Chrome Extension과 별개로 만들어 둔
대안 브릿지(Tampermonkey userscript)다. 코드상으로는 동작하도록 작성돼 있지만, 실제 검증/운영에서는
**한 번도 사용하지 않았다** — 실제로 CDMS 브라우저 세션을 제어하는 경로는 항상 `extension/`(Chrome Extension)이었고,
`CDMSAgent`의 기본값도 `runner="extension"`이다. daemon 저장소 안에서만 참조되며, 이 저장소(`CDMS-Agent`)의
어떤 문서·코드도 Tampermonkey를 전제로 하지 않는다. 후임자가 새로 셋업할 때는 Tampermonkey 관련 안내는 무시하고
extension만 로드하면 된다.

### SQL 스키마 (아직 미활용)

`daemon/docs/schema-v2.sqlite.sql`과 이를 읽어 만들어지는 `data/cdms_agent.sqlite`는 향후
**과제(study)별 데이터가 쌓이면** 프로젝트/과제/소스파일/생성 케이스/실행 이력/재사용 메모리를
정규화된 SQL로 조회·리포팅할 수 있게 하려는 목적으로 설계해 둔 것이다 (`projects`, `studies`,
`source_files`, `test_cases`, `execution_runs`, `memories` 등의 테이블 포함).
다만 **현재까지는 실제로 활용하지 않았다** — 스키마와 빈 DB 파일만 만들어져 있는 상태이며,
daemon이 case/run 데이터를 이 스키마에 실제로 쓰고 있는지는 후임자가 `AgentStore.ts` 기준으로
다시 확인이 필요하다.

---

## How to Run (오랜만에 다시 실행할 때)

### 0. 사전 요구사항
- Python ≥ 3.9, Node.js ≥ 22 / npm ≥ 10
- Chrome (side panel + `chrome.debugger` API 사용)

### 1. Python 패키지 설치 (최초 1회 / venv 갱신 시)
```bash
cd C:\Users\SunbeomGwon\CDMS-Agent
pip install -e ".[dev]"      # pytest, ipython, notebook, openpyxl 포함
```

### 2. Daemon 설치 & 기동
```bash
cd C:\Users\SunbeomGwon\CDMS-Agent\daemon
npm install                  # package-lock.json 기준 최초 1회 / 의존성 변경 시
cd ..
npm run daemon                # = npm run dev --prefix daemon (ts-node, 기본 포트 3200)
```
헬스체크: 브라우저에서 `http://127.0.0.1:3200/api/health` 접속 → `{"result": true, ...}` 확인.

> `PORT` 환경변수로 포트를 바꿀 수 있다. 바꾸면 `extension/manifest.json`의 `host_permissions`와
> `service-worker.js`/`sidepanel.js`의 `DEFAULT_DAEMON_ORIGIN`, 그리고 Python `CDMSAgent(base_url=...)`도 맞춰야 한다.
> (참고: 예전 `CLAUDE.md`/구버전 README는 포트 3100을 언급하지만, 현재 코드 기본값은 **3200**이다.)

### 3. Chrome Extension 로드
1. `chrome://extensions` → 우측 상단 "개발자 모드" ON
2. "압축해제된 확장 프로그램을 로드합니다" → `C:\Users\SunbeomGwon\CDMS-Agent\extension` 선택
3. 이미 로드되어 있었다면 코드가 바뀌었을 수 있으니 새로고침(⟳) 아이콘으로 리로드
4. CDMS 사이트(`sbx.cdms.mavenclinical.com` 또는 `cdms.mavenclinical.com`)를 열고 확장 프로그램 아이콘으로 사이드패널을 연다
5. 사이드패널에 daemon 연결 상태가 표시된다 (연결 안 되면 daemon이 떠 있는지, origin/포트가 맞는지 확인)

### 4. Python에서 연결 확인
```python
from cdm_agent_client import CDMSAgent

agent = CDMSAgent(study_id="YOUR_STUDY_ID")   # base_url 기본값 http://127.0.0.1:3200
print(agent.ping())        # True 여야 정상
print(agent.clients())     # 연결된 브라우저 client 목록
snap = agent.inspect()
print(snap.page_label, snap.pathname)
```

### 5. CRF 검증 노트북 생성 / 정적 진단
```bash
# 브라우저 없이 CRF 소스만 정적 점검 (트리거 중복, pageId 누락 등)
cdms-crf doctor "C:\Users\SunbeomGwon\maven-crfs\src\crfs\<study>"

# 대화형으로 검증 notebook 생성
cdms-crf-notebook
# 또는: cdms-crf gen-notebook
```
Python API로 직접 생성하려면:
```python
from cdm_agent_client.crf import gen_notebook

path = gen_notebook(
    crf_path=r"C:\Users\SunbeomGwon\maven-crfs\src\crfs\20260325_PRACTICE_GSB",
    agent_project_root=r"C:\Users\SunbeomGwon\CDMS-Agent",
    visit_map={1: "V0", 2: "V1", 60: "V60"},
)
print(path)
```
생성된 `.ipynb`는 Jupyter에서 열어 셀을 하나씩 실행하며 브라우저를 눈으로 보고 검증하는 용도다.
**생성 ≠ 실행**이다 — 노트북을 만든다고 자동으로 검증이 돌지 않는다.

### 6. 테스트
```bash
pytest
```

---

## CDMSAgent 주요 메서드

| 분류 | 메서드 |
|---|---|
| 연결 | `ping()`, `clients()` |
| 조회 | `inspect()`, `list_pages()` |
| 입력 | `set_text()`, `set_date()`, `select_radio()`, `select_option()`, `probe_radio()` |
| 이동/저장 | `go_to_page()`, `navigate_to()`, `go_back()`, `click_save()`, `click_save_next()` |
| 쿼리 확인 | `has_query()`, `check_result()`, `wait_query()`, `clear_query()` |
| 고급 | `run_case()` |

## CRF 파이프라인 핵심 객체 (`cdm_agent_client.crf`)

| 객체 | 역할 |
|---|---|
| `CRFRunner` | CRF TS 소스를 읽어 `CRFPlan`(query/visibility/availability 케이스 묶음)을 만든다 |
| `CRFRun` | `CRFPlan`의 케이스를 `CDMSAgent`로 실제 실행 |
| `gen_notebook` | 검증용 Jupyter 노트북 파일 생성 (`generate_crf_notebook`은 구버전 호환 별칭) |
| `CRFDoctor` / `run_doctor` | 브라우저 없이 CRF 소스 정적 진단 (`cdms-crf doctor`) |
| `audit_phase0`, `audit_query_cases` | 커버리지/누락 감사 |

---

## 알려진 기술 이슈 메모

Fluent UI 라디오버튼의 `isTrusted` 문제, React SPA 네비게이션 처리, 방문 코드 매핑 등
구현상의 트릭은 [CLAUDE.md](CLAUDE.md)에 정리되어 있다 (해당 파일은 한글 인코딩이 깨져 있는 부분이
있으니 코드 블록 위주로 참고).

## Related Files

- [notebooks/quickstart.ipynb](notebooks/quickstart.ipynb)
- [docs/cdm_agent_client.md](docs/cdm_agent_client.md)
- [SKILL.md](SKILL.md) — CRF 노트북 생성 Claude Code 스킬
