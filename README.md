# CDMS-Agent

Python client for automating CDMS (Clinical Data Management System) browser sessions via the CDM Agent daemon.

Designed for clinical data managers who need to script repetitive CRF entry tasks — date input, field validation, page navigation — from a Jupyter notebook or Python script, without touching browser DevTools or writing raw JavaScript.

## Architecture

```
Jupyter / Python script
    │
    │  HTTP (requests)
    ▼
CDM Agent Daemon (Node.js, port 3100)
    │
    │  WebSocket
    ▼
Chrome Extension (MV3 service worker)
    │
    │  chrome.scripting.executeScript  (world: "MAIN")
    ▼
CDMS Page DOM  ←  browser-runner-core.js
```

- **This package** handles the Python ↔ Daemon layer only.  
- The daemon and Chrome extension are part of the companion [cdm-agent-platform](https://github.com/Eli-Beom/cdm-agent-platform) project.

## Requirements

| Component | Version |
|---|---|
| Python | ≥ 3.9 |
| CDM Agent daemon | running on `http://127.0.0.1:3100` |
| Chrome extension | loaded in developer mode |

## Installation

```bash
pip install cdm-agent-client
```

Or install directly from this repository:

```bash
pip install git+https://github.com/Eli-Beom/CDMS-Agent.git
```

## Quick Start

```python
from cdm_agent_client import CDMAgent

agent = CDMAgent(
    base_url="http://127.0.0.1:3100",
    study_id="YOUR_STUDY_ID",
)

# 1. Inspect the currently open CDMS page
snapshot = agent.inspect()
print(snapshot.page_label)       # e.g. "Vital Signs"
print(snapshot.visible_rows)     # ["Visit date", "Weight", "Height", ...]
print(snapshot.enabled_actions)  # ["Save & Next", "Save"]

# 2. Type a date into a labelled field
result = agent.set_date("Visit date", "2025-01-15")
print(result.outcome)            # "passed"

# 3. Save and navigate to the next page
nav = agent.click_save_next()
print(nav.page_after)            # "/subjects/S001/NV/V01/vitals"
```

All return values render as HTML cards in Jupyter:

```python
agent.inspect()          # → coloured status card
agent.set_date(...)      # → step result card (green ✓ / red ✗)
agent.click_save_next()  # → step result card with page transition
```

## API Reference

### `CDMAgent(base_url, *, study_id, timeout, run_timeout, raise_on_failure)`

| Parameter | Default | Description |
|---|---|---|
| `base_url` | `http://127.0.0.1:3100` | Daemon URL |
| `study_id` | `None` | Study identifier forwarded with every request |
| `timeout` | `30` | HTTP timeout in seconds |
| `run_timeout` | `120` | Timeout for browser step execution |
| `raise_on_failure` | `True` | Raise `StepFailedError` on failed/blocked outcome |

### Methods

| Method | Description |
|---|---|
| `inspect(client_id?)` | Capture current page state → `PageSnapshot` |
| `set_date(row_label, value)` | Type a date value into a labelled field → `StepResult` |
| `click_save_next()` | Click the Save & Next button → `StepResult` |
| `run_case(case_payload)` | Execute an arbitrary TestCase payload |
| `clients()` | List connected browser clients |
| `ping()` | Check daemon reachability → `bool` |

### `PageSnapshot`

```python
snapshot.connected        # bool
snapshot.page_label       # str | None
snapshot.url              # str | None
snapshot.visible_rows     # list[str]
snapshot.enabled_actions  # list[str]
snapshot.invalid_count    # int
snapshot.invalid_row_labels  # list[str]
```

### `StepResult`

```python
result.ok             # bool  (outcome == "passed")
result.outcome        # "passed" | "failed" | "blocked" | "skipped"
result.failure_reason # str | None
result.page_before    # str | None
result.page_after     # str | None
```

## Error Handling

```python
from cdm_agent_client import (
    StepFailedError,
    NoBrowserClientError,
    DaemonNotRunningError,
)

try:
    result = agent.set_date("Visit date", "2025-01-15")
except StepFailedError as e:
    print(e.outcome, e.reason)
except NoBrowserClientError:
    print("No browser tab is connected to the daemon.")
except DaemonNotRunningError:
    print("Start the daemon with: npm run dev")
```

Set `raise_on_failure=False` to receive a `StepResult` regardless of outcome:

```python
agent = CDMAgent(raise_on_failure=False)
result = agent.set_date("Visit date", "bad-value")
print(result.ok, result.failure_reason)
```

## Jupyter Notebook

See [`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb) for a full walkthrough.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
