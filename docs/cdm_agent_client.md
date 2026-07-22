# cdm_agent_client 패키지 문서

CDMS 브라우저 자동화 및 DVS(Data Validation Specification) 검증을 위한 Python 패키지.

---

## 설치 및 Import

```python
import sys
sys.path.insert(0, r"C:\Users\SunbeomGwon\CDMS-Agent\src")

from cdm_agent_client import CDMAgent
from cdm_agent_client.dvs import DVSRunner
```

---

## 패키지 구조

```
src/cdm_agent_client/
├── __init__.py       # 패키지 진입점
├── client.py         # CDMAgent 클래스
├── models.py         # PageSnapshot, PageList, StepResult
├── exceptions.py     # 에러 클래스
└── dvs/
    ├── __init__.py   # DVSRunner, DVSRow, DVSResult, Precondition export
    ├── runner.py     # DVSRunner 클래스
    ├── schema.py     # DVSRow, DVSResult, Precondition, ActionStep, PlanResult
    ├── parser.py     # Excel → DVSRow 파싱
    ├── planner.py    # Precondition → ActionStep 변환
    ├── checker.py    # 페이지 상태 검증 로직
    ├── registry.py   # ItemDef, ItemRegistry (CRF 항목 메타데이터)
    └── reporter.py   # Excel/HTML 결과 리포트 생성
```

---

## CDMAgent

Chrome extension을 통해 CDMS 브라우저를 조작하는 클라이언트.  
내부적으로 로컬 daemon(`http://127.0.0.1:3200`)과 HTTP로 통신한다.

### 생성

```python
agent = CDMAgent(
    base_url="http://127.0.0.1:3200",  # daemon 주소
    study_id=None,                      # 스터디 ID (미지정 시 자동)
    timeout=30,                         # HTTP 요청 타임아웃 (초)
    run_timeout=120,                    # 브라우저 스텝 실행 타임아웃 (초)
    raise_on_failure=True,              # 실패 시 예외 발생 여부
    runner="extension",                 # 실행 방식
)
```

### Daemon / 연결 확인

| 메서드 | 설명 |
|--------|------|
| `agent.ping()` | daemon이 살아있는지 확인 |
| `agent.clients()` | 연결된 브라우저 extension client 목록 반환 |

> `agent.client()` 는 없음. 반드시 `agent.clients()` 사용.

### 페이지 정보

| 메서드 | 설명 |
|--------|------|
| `agent.inspect()` | 현재 CDMS 페이지 스냅샷 반환 (`PageSnapshot`) |
| `agent.list_pages()` | CRF 페이지 목록 반환 (`PageList`). Jupyter에서 표로 출력됨 |

### 필드 입력

| 메서드 | 설명 |
|--------|------|
| `agent.set_text("Height ...", "170")` | 텍스트/숫자 필드 입력 |
| `agent.set_date("Birth date", "1997-01-02")` | 날짜 필드 입력 (`YYYY-MM-DD`) |
| `agent.select_radio("Sex", "Female")` | 라디오 버튼 선택 |
| `agent.select_option("필드명", "옵션")` | 드롭다운 선택 |

### 버튼 / 네비게이션

| 메서드 | 설명 |
|--------|------|
| `agent.click_save()` | Save 버튼 클릭 |
| `agent.click_save_next()` | Save & Next 버튼 클릭 |
| `agent.go_to_page("V2/SV")` | 특정 페이지로 이동 |
| `agent.navigate_to("/some/path")` | 경로로 직접 이동 |
| `agent.go_back()` | 이전 페이지로 이동 |

### DVS 결과 확인

| 메서드 | 설명 |
|--------|------|
| `agent.has_query()` | 현재 페이지에 Query가 있는지 여부 반환 |
| `agent.check_result("Query")` | Query 발생 여부를 검증 |
| `agent.check_result("No Query")` | Query 없음을 검증 |

---

## DVSRunner

DVS Excel 파일을 읽어서 자동/수동으로 검증 결과를 기록하고 Excel에 저장하는 오케스트레이터.

### 생성

```python
excel_path = r"C:\...\FAST-AF_EDC Validation List_001_draft(0.1)_20260422_밸데_GSB.xlsx"
runner = DVSRunner(agent, excel_path)
```

### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `runner._get_rows()` | Excel에서 DVSRow 리스트 파싱 |
| `runner.dry_run()` | Excel 파싱 결과만 출력 (브라우저 조작 없음) |
| `runner.run_one(dvs_id, no=None)` | 특정 DVS ID 하나 실행 |
| `runner.run_all()` | 전체 DVS 자동 실행 후 Excel/HTML 리포트 생성 |
| `runner.generate_notebook()` | DVS별 Jupyter 노트북 셀 자동 생성 |
| `runner.record(dvs_id, no, result, comment="")` | 결과를 메모리에 기록 |
| `runner.flush_to_excel()` | 기록된 결과를 `_validated.xlsx`에 저장 |

### 수동 결과 기록 흐름

```python
runner.record("D_EN_SQ_1", 1, "PASS", "수동 확인")
runner.flush_to_excel()
```

`flush_to_excel()`은 원본 파일을 덮어쓰지 않고 `_validated.xlsx` 파일을 새로 생성한다.  
결과는 **R열 (Result)**, 코멘트는 **S열 (Comment)** 에 기록되며 색상 코딩이 적용된다.

| 결과 | 색상 |
|------|------|
| PASS | 초록 (#00B050) |
| FAIL | 빨강 (#FF0000) |
| SKIP / ERROR | 노랑 |

---

## DVSRow

`runner._get_rows()`가 반환하는 객체. Excel 한 행에 대응한다.

### 속성

| 속성 | 설명 |
|------|------|
| `dvs_id` | DVS 식별자 (예: `D_EN_SQ_1`) |
| `no` | 행 번호 |
| `domain` | 도메인 (예: `EN`, `DM`) |
| `page_label` | CRF 페이지 레이블 |
| `visit_codes` | 해당 방문 코드 목록 |
| `item_id` | CRF 항목 ID |
| `item_label` | CRF 항목 레이블 |
| `layout` | 레이아웃 타입 |
| `data_type` | 데이터 타입 |
| `dvs_type` | DVS 종류 |
| `specification` | 스펙 설명 |
| `query_message` | 예상 쿼리 메시지 |
| `test_script` | 테스트 스크립트 원문 |
| `expected_result` | 기대 결과 (`Query` / `No Query` 등) |
| `excel_row` | Excel 행 번호 (디버깅용) |

### DataFrame 변환 예시

```python
rows = runner._get_rows()
df = pd.DataFrame([
    {
        "DVS ID":   r.dvs_id,
        "No":       r.no,
        "Page":     r.page_label,
        "Item":     r.item_label,
        "Expected": r.expected_result,
        "Excel Row": r.excel_row,
    }
    for r in rows
])
display(df)
```

---

## 예외 클래스

| 클래스 | 발생 조건 |
|--------|-----------|
| `CDMAgentError` | 기본 에러 (모든 에러의 부모) |
| `DaemonNotRunningError` | daemon 서버에 연결 불가 |
| `NoBrowserClientError` | 연결된 브라우저 extension 없음 |
| `StepFailedError` | 브라우저 스텝 실행 실패 |

---

## 추천 워크플로우

```python
# 1. 초기화
agent = CDMAgent()
runner = DVSRunner(agent, excel_path)

# 2. DVS 목록 확인
rows = runner._get_rows()
df = pd.DataFrame([
    {"DVS ID": r.dvs_id, "No": r.no, "Page": r.page_label,
     "Item": r.item_label, "Expected": r.expected_result}
    for r in rows
])
display(df)

# 3-A. 자동 실행
runner.run_all()

# 3-B. 수동 기록
runner.record("D_EN_SQ_1", 1, "PASS", "수동 확인")
runner.flush_to_excel()
```

### 역할 구분

| 객체 | 역할 |
|------|------|
| `agent` | 브라우저 / CDMS 조작 |
| `runner` | Excel DVS 관리 및 결과 기록 |
| `rows` | DVSRow 리스트 (파싱 결과) |
| `df` | 사람이 보기 편한 임시 표 (노트북 변수) |
