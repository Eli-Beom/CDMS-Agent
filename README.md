# CDM Agent Client

`cdm-agent-client` is a Python package for controlling a CDMS browser session
from Python or Jupyter Notebook through a local CDM Agent daemon.

## Responsibility Model

| Component | Responsibility |
| --- | --- |
| `cdm-agent-client` | The Python package containing the client API and CRF tooling. |
| `CDMSAgent` | Browser-control client. It sends HTTP requests to the local daemon and exposes methods such as `go_to_page`, `set_text`, `set_date`, `select_radio`, `select_option`, `click_save`, `inspect`, `has_query`, and `check_result`. |
| CDM Agent daemon | Local server, usually `http://127.0.0.1:3100`, that connects Python requests to the browser runner. |
| `CRFRunner` | CRF source analyzer and validation scenario generator. It reads TypeScript CRF specs and creates Query, Visibility, and Availability scenarios. It does not directly operate the browser. |
| Generated Notebook | Human-operated validation workspace. Notebook cells execute generated scenarios through `CDMSAgent` while the operator watches the browser and reviews results. |

## Install

```bash
pip install cdm-agent-client
```

For local development:

```bash
pip install -e .[dev]
```

## CDMSAgent Quick Start

Start the CDM Agent daemon and connect a browser runner first.

```python
from cdm_agent_client import CDMSAgent

agent = CDMSAgent(
    base_url="http://127.0.0.1:3100",
    study_id="YOUR_STUDY_ID",
    stop_on_error=True,
    runner="extension",
)

print("Daemon connected:", agent.ping())

snapshot = agent.inspect()
print(snapshot.page_label)
print(snapshot.visible_rows)

agent.go_to_page("DM")
agent.set_date("Visit date", "2025-01-15")
agent.set_text("Weight", "70")
agent.select_radio("Sex", "Female")
agent.select_option("Result", "Normal")
agent.click_save()

print(agent.has_query())
print(agent.check_result("No Query"))
```

## CDMSAgent API Summary

| Category | Methods |
| --- | --- |
| Connection | `ping()`, `clients()` |
| Inspection | `inspect()`, `list_pages()` |
| Input | `set_text()`, `set_date()`, `select_radio()`, `select_option()` |
| Navigation/save | `go_to_page()`, `navigate_to()`, `go_back()`, `click_save()`, `click_save_next()` |
| Query checks | `has_query()`, `check_result()` |
| Advanced | `run_case()` |

## CRF Scenario Generation

`cdm_agent_client.crf` reads TypeScript CRF source from `maven-crfs` and
generates scenarios for:

- Query expected
- No Query expected
- Visibility
- Availability

`CRFRunner` keeps the CRF analysis and simulation-case generation logic, but it
does not call browser-control methods itself. It returns `CRFScenario` objects
containing `CDMSAgent` method calls and checks.

```python
from cdm_agent_client.crf import CRFRunner

runner = CRFRunner(
    maven_root=r"C:\path\to\maven-crfs",
    study="20260325_PRACTICE_GSB",
    visit_map={1: "V0", 2: "V1", 60: "V60"},
)

runner.load_spec()
display(runner.summary())

scenarios = runner.all_scenarios()
display(runner.to_dataframe(scenarios))

print(scenarios[0].to_code("agent"))
```

For compatibility with older notebooks, `sim_query`, `sim_visibility`,
`sim_availability`, and `run_all` still exist, but they now generate scenarios
instead of executing browser automation.

## Generate a Validation Notebook

The recommended CRF workflow is to generate a notebook, inspect generated cases,
and run selected cells while watching the connected CDMS browser.

```python
from cdm_agent_client.crf import generate_crf_notebook

notebook_path = generate_crf_notebook(
    maven_root=r"C:\path\to\maven-crfs",
    study="20260325_PRACTICE_GSB",
    study_id="PRACTICE_GSB",
    visit_map={1: "V0", 2: "V1", 60: "V60"},
)

print(notebook_path)
```

The generated notebook includes cells for:

- Loading the TypeScript CRF spec
- Building Query, Visibility, and Availability scenarios
- Connecting `CDMSAgent`
- Previewing generated scenarios
- Running a single selected scenario
- Running a small selected range
- Saving FAIL/SKIP/ERROR results for review

Scenario execution cells call `CDMSAgent` methods directly, for example:

```python
agent.go_to_page("V1/VS")
agent.set_text("Weight", "999", page_id="VS", visit_id="V1")
agent.click_save(page_id="VS", visit_id="V1")
print(agent.check_result("Query"))
```

## Project Structure

```text
src/cdm_agent_client/
  __init__.py
  client.py
  models.py
  exceptions.py
  crf/
    __init__.py
    extractor.py
    parser.py
    simulator.py
    runner.py
    notebook.py
    models.py
```

## Related Files

- `notebooks/quickstart.ipynb`
- `docs/cdm_agent_client.md`
- `LICENSE`

## License

Apache License 2.0
