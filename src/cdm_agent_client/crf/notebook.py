from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CRFNotebookBuilder:
    """Generate a Jupyter notebook for CRF-code based UI validation.

    The generated notebook is an operator workspace. ``CRFRunner`` prepares
    scenarios from TypeScript CRF source, and notebook cells execute those
    scenarios through ``CDMSAgent`` while the user watches the browser.
    """

    def __init__(
        self,
        *,
        maven_root: str | Path,
        study: str,
        study_id: str,
        agent_project_root: str | Path | None = None,
        visit_map: dict[int, str] | None = None,
    ) -> None:
        self.maven_root = Path(maven_root)
        self.study = study
        self.study_id = study_id
        self.agent_project_root = Path(agent_project_root) if agent_project_root else _default_agent_root()
        self.visit_map = visit_map or {}

    def generate_notebook(
        self,
        output_path: str | Path | None = None,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
    ) -> Path:
        """Write a runnable notebook and return its path."""
        out = Path(output_path) if output_path else (
            self.maven_root / "src" / "crfs" / self.study / "CDMS-Agent_crf_validation.ipynb"
        )
        out.parent.mkdir(parents=True, exist_ok=True)

        cells: list[dict[str, Any]] = [
            _markdown_cell(
                "# CRF Validation Workspace\n\n"
                "This notebook was generated from TypeScript CRF source. "
                "It keeps CRF analysis in CRFRunner and executes browser steps "
                "through CDMSAgent so each validation can be observed interactively."
            ),
            _setup_cell(self),
            _load_spec_cell(),
            _build_scenarios_cell(include_query, include_visibility, include_availability),
            _connect_agent_cell(),
            _executor_cell(),
            _preview_cell(),
            _single_scenario_cell(),
            _selected_run_cell(),
            _failure_report_cell(),
        ]

        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.9.0"},
            },
            "cells": cells,
        }
        out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        return out


def generate_crf_notebook(
    output_path: str | Path | None = None,
    *,
    maven_root: str | Path,
    study: str,
    study_id: str,
    agent_project_root: str | Path | None = None,
    visit_map: dict[int, str] | None = None,
    include_query: bool = True,
    include_visibility: bool = True,
    include_availability: bool = True,
) -> Path:
    """Generate a CRF-code based validation notebook."""
    builder = CRFNotebookBuilder(
        maven_root=maven_root,
        study=study,
        study_id=study_id,
        agent_project_root=agent_project_root,
        visit_map=visit_map,
    )
    return builder.generate_notebook(
        output_path,
        include_query=include_query,
        include_visibility=include_visibility,
        include_availability=include_availability,
    )


def _default_agent_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _code_cell(source: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _markdown_cell(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _setup_cell(builder: CRFNotebookBuilder) -> dict[str, Any]:
    return _code_cell(
        "import sys\n"
        "from pathlib import Path\n"
        "import pandas as pd\n\n"
        f"AGENT_ROOT = Path(r'{builder.agent_project_root}')\n"
        "if str(AGENT_ROOT / 'src') not in sys.path:\n"
        "    sys.path.insert(0, str(AGENT_ROOT / 'src'))\n\n"
        "from cdm_agent_client import CDMSAgent\n"
        "from cdm_agent_client.crf import CRFRunner\n\n"
        f"MAVEN_ROOT = Path(r'{builder.maven_root}')\n"
        f"STUDY = {builder.study!r}\n"
        f"STUDY_ID = {builder.study_id!r}\n"
        f"VISIT_MAP = {builder.visit_map!r}\n"
    )


def _load_spec_cell() -> dict[str, Any]:
    return _code_cell(
        "runner = CRFRunner(maven_root=MAVEN_ROOT, study=STUDY, visit_map=VISIT_MAP)\n"
        "runner.load_spec()\n"
        "display(runner.summary())\n"
    )


def _build_scenarios_cell(include_query: bool, include_visibility: bool, include_availability: bool) -> dict[str, Any]:
    query_expr = "runner.query_scenarios()" if include_query else "[]"
    visibility_expr = "runner.visibility_scenarios()" if include_visibility else "[]"
    availability_expr = "runner.availability_scenarios()" if include_availability else "[]"
    return _code_cell(
        f"query_scenarios = {query_expr}\n"
        f"visibility_scenarios = {visibility_expr}\n"
        f"availability_scenarios = {availability_expr}\n"
        "scenarios = [*query_scenarios, *visibility_scenarios, *availability_scenarios]\n"
        "scenarios_df = runner.to_dataframe(scenarios)\n"
        "display(scenarios_df)\n"
    )


def _connect_agent_cell() -> dict[str, Any]:
    return _code_cell(
        "agent = CDMSAgent(study_id=STUDY_ID, stop_on_error=False)\n"
        "print('Daemon connected:', agent.ping())\n"
        "snap = agent.inspect()\n"
        "print('Current page:', snap.page_label)\n"
        "print('Path:', snap.pathname)\n"
    )


def _executor_cell() -> dict[str, Any]:
    return _code_cell(
        "def _run_check(check, failures):\n"
        "    if check.check_type == 'query':\n"
        "        actual = agent.check_result(check.expected)\n"
        "        print('check_result:', check.expected, '=>', actual)\n"
        "        if actual != 'PASS':\n"
        "            failures.append(f\"query expected {check.expected}\")\n"
        "    elif check.check_type in ('visible', 'not_visible'):\n"
        "        snap = agent.inspect()\n"
        "        visible = check.label in snap.visible_rows\n"
        "        passed = visible if check.check_type == 'visible' else not visible\n"
        "        print(check.label, check.check_type, '=>', 'PASS' if passed else 'FAIL')\n"
        "        if not passed:\n"
        "            failures.append(f\"{check.label} {check.check_type}\")\n\n"
        "def run_scenario(scenario, *, stop_on_error=False):\n"
        "    rows = []\n"
        "    failures = []\n"
        "    print(f\"[{scenario.kind}] {scenario.id} {scenario.label or ''}\")\n"
        "    if scenario.errors:\n"
        "        return {'id': scenario.id, 'kind': scenario.kind, 'result': 'SKIP', 'errors': '; '.join(scenario.errors)}\n"
        "    for step_index, step in enumerate(scenario.steps, start=1):\n"
        "        call = getattr(agent, step.method)\n"
        "        print('>', step.to_code('agent'))\n"
        "        result = call(*step.args, **step.kwargs)\n"
        "        rows.append({'step': step.method, 'outcome': getattr(result, 'outcome', '')})\n"
        "        if stop_on_error and getattr(result, 'ok', True) is False:\n"
        "            return {'id': scenario.id, 'kind': scenario.kind, 'result': 'ERROR', 'errors': getattr(result, 'failure_reason', '')}\n"
        "        for check in scenario.checks:\n"
        "            if check.after_step == step_index:\n"
        "                _run_check(check, failures)\n"
        "    for check in scenario.checks:\n"
        "        if check.after_step is None:\n"
        "            _run_check(check, failures)\n"
        "    return {'id': scenario.id, 'kind': scenario.kind, 'result': 'FAIL' if failures else 'PASS', 'errors': '; '.join(failures)}\n"
    )


def _preview_cell() -> dict[str, Any]:
    return _code_cell(
        "RUNNABLE_ONLY = True\n"
        "preview_df = scenarios_df.copy()\n"
        "if RUNNABLE_ONLY:\n"
        "    preview_df = preview_df[preview_df['runnable']]\n"
        "display(preview_df[['kind', 'id', 'page', 'label', 'expect', 'steps', 'checks', 'errors']])\n"
    )


def _single_scenario_cell() -> dict[str, Any]:
    return _code_cell(
        "SCENARIO_INDEX = 0\n"
        "scenario = scenarios[SCENARIO_INDEX]\n"
        "print(scenario.to_code('agent'))\n"
        "single_result = run_scenario(scenario)\n"
        "display(pd.DataFrame([single_result]))\n"
    )


def _selected_run_cell() -> dict[str, Any]:
    return _code_cell(
        "SELECTED = range(0, min(5, len(scenarios)))\n"
        "results = []\n"
        "for i in SELECTED:\n"
        "    results.append(run_scenario(scenarios[i]))\n"
        "results_df = pd.DataFrame(results)\n"
        "display(results_df)\n"
    )


def _failure_report_cell() -> dict[str, Any]:
    return _code_cell(
        "if 'results_df' not in globals():\n"
        "    print('Run selected scenarios first.')\n"
        "else:\n"
        "    review_df = results_df[results_df['result'].isin(['FAIL', 'SKIP', 'ERROR'])].copy()\n"
        "    out = Path.cwd() / f'{STUDY}_crf_validation_failures.xlsx'\n"
        "    review_df.to_excel(out, index=False)\n"
        "    display(review_df)\n"
        "    print('Saved:', out)\n"
    )
