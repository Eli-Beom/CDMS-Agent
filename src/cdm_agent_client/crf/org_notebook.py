from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import row_matcher as _row_matcher
from . import rule_discovery as _rule_discovery
from . import value_planner as _value_planner
from . import availability_discovery as _availability_discovery


BROWSER_ASSISTED = "browser-assisted"
BROWSER_ASSISTED_AVAILABILITY_DISCOVERY = "browser-assisted-availability-discovery"
BROWSER_ASSISTED_QUERY_EXPECTED = "browser-assisted-query-expected"
BROWSER_ASSISTED_QUERY_DISCOVERY = "browser-assisted-query-discovery"
BROWSER_ASSISTED_COMBINED_DISCOVERY = "browser-assisted-combined-discovery"
STATIC = "static"


class CRFNotebookBuilder:
    """Generate a Jupyter notebook for CRF-code based UI validation.

    The generated notebook is an operator workspace. ``CRFRunner`` prepares a
    ``CRFPlan`` from TypeScript CRF source, and notebook cells execute cases
    through ``CDMSAgent`` while the user watches the browser.
    """

    def __init__(
        self,
        *,
        crf_path: str | Path | None = None,
        maven_root: str | Path | None = None,
        study: str | None = None,
        agent_project_root: str | Path | None = None,
        visit_map: dict[int, str] | None = None,
        page_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> None:
        from .runner import resolve_crf_location

        self.maven_root, self.study = resolve_crf_location(
            crf_path=crf_path,
            maven_root=maven_root,
            study=study,
        )
        self.crf_path = Path(crf_path) if crf_path is not None else self.maven_root / "src" / "crfs" / self.study
        self.agent_project_root = Path(agent_project_root) if agent_project_root else _default_agent_root()
        self.visit_map = visit_map
        self.page_ids = list(page_ids) if page_ids else None

    def gen_notebook(
        self,
        output_path: str | Path | None = None,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
        max_case_cells: int = 3,
        generation_mode: str = STATIC,
        final_action: str = "save_next",
    ) -> Path:
        """Write a runnable notebook and return its path."""
        out = Path(output_path) if output_path else (
            self.crf_path / "CDMS-Agent_crf_validation.ipynb"
        )
        out.parent.mkdir(parents=True, exist_ok=True)

        generated_cells = _generated_case_cells(
            self,
            include_query=include_query,
            include_visibility=include_visibility,
            include_availability=include_availability,
            max_case_cells=max_case_cells,
            generation_mode=generation_mode,
            final_action=final_action,
        )

        cells: list[dict[str, Any]] = [
            _markdown_cell(
                "# CRF Validation Workspace\n\n"
                "This notebook was generated from TypeScript CRF source. "
                "It keeps CRF analysis in CRFRunner and emits concrete "
                "CDMSAgent code cells that can be run one by one."
            ),
            _setup_cell(self),
            _load_spec_cell(),
            _build_cases_cell(include_query, include_visibility, include_availability, generation_mode),
            _connect_agent_cell(),
            _preview_cell(),
            _markdown_cell("## Generated CDMSAgent Case Cells\n\nRun these cells one by one while watching the browser."),
            *generated_cells,
        ]

        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.9.0"},
                "cdms_agent": {"generation_mode": generation_mode},
            },
            "cells": cells,
        }
        out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        return out

    def generate_notebook(
        self,
        output_path: str | Path | None = None,
        *,
        include_query: bool = True,
        include_visibility: bool = True,
        include_availability: bool = True,
        max_case_cells: int = 3,
        generation_mode: str = STATIC,
        final_action: str = "save_next",
    ) -> Path:
        """Backward-compatible alias for ``gen_notebook``."""
        return self.gen_notebook(
            output_path,
            include_query=include_query,
            include_visibility=include_visibility,
            include_availability=include_availability,
            max_case_cells=max_case_cells,
            generation_mode=generation_mode,
            final_action=final_action,
        )


def gen_notebook(
    output_path: str | Path | None = None,
    *,
    crf_path: str | Path | None = None,
    maven_root: str | Path | None = None,
    study: str | None = None,
    agent_project_root: str | Path | None = None,
    visit_map: dict[int, str] | None = None,
    page_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    include_query: bool = True,
    include_visibility: bool = True,
    include_availability: bool = True,
    max_case_cells: int = 3,
    generation_mode: str = STATIC,
    final_action: str = "save_next",
) -> Path:
    """Generate a CRF-code based validation notebook."""
    builder = CRFNotebookBuilder(
        crf_path=crf_path,
        maven_root=maven_root,
        study=study,
        agent_project_root=agent_project_root,
        visit_map=visit_map,
        page_ids=page_ids,
    )
    return builder.gen_notebook(
        output_path,
        include_query=include_query,
        include_visibility=include_visibility,
        include_availability=include_availability,
        max_case_cells=max_case_cells,
        generation_mode=generation_mode,
        final_action=final_action,
    )


generate_crf_notebook = gen_notebook


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


def _generated_case_cells(
    builder: CRFNotebookBuilder,
    *,
    include_query: bool,
    include_visibility: bool,
    include_availability: bool,
    max_case_cells: int,
    generation_mode: str,
    final_action: str,
) -> list[dict[str, Any]]:
    from .runner import CRFRunner

    runner = CRFRunner(
        crf_path=builder.crf_path,
        visit_map=builder.visit_map,
        page_ids=builder.page_ids,
    )
    runner.load_spec()
    browser_context = _browser_context() if generation_mode in {
        BROWSER_ASSISTED,
        BROWSER_ASSISTED_QUERY_EXPECTED,
        BROWSER_ASSISTED_QUERY_DISCOVERY,
        BROWSER_ASSISTED_AVAILABILITY_DISCOVERY,
        BROWSER_ASSISTED_COMBINED_DISCOVERY,
    } else None
    if browser_context is not None and generation_mode == BROWSER_ASSISTED_AVAILABILITY_DISCOVERY:
        candidates = _browser_availability_discovery_candidates(runner, browser_context)
        page_id = browser_context.get("page_id") or "CURRENT"
        export_path = builder.crf_path / f"CDMS-Agent_availability_discovery_{page_id}_v0.1.csv"
        candidates_path = builder.crf_path / f"CDMS-Agent_availability_candidates_{page_id}_v0.1.json"
        candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        return [
            _markdown_cell(_browser_availability_discovery_markdown(browser_context, candidates)),
            _code_cell(_browser_availability_discovery_code(browser_context, export_path=export_path, candidates_path=candidates_path)),
        ]
    if browser_context is not None and generation_mode == BROWSER_ASSISTED_QUERY_DISCOVERY:
        candidates = _browser_query_discovery_candidates(runner, browser_context)
        page_id = browser_context.get("page_id") or "CURRENT"
        export_path = builder.crf_path / f"CDMS-Agent_rule_discovery_{page_id}_v0.2.csv"
        candidates_path = builder.crf_path / f"CDMS-Agent_rule_discovery_candidates_{page_id}_v0.2.json"
        candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        return [
            _markdown_cell(_browser_query_discovery_markdown(runner, browser_context, candidates)),
            _code_cell(_browser_query_discovery_code(browser_context, export_path=export_path, candidates_path=candidates_path)),
        ]
    if browser_context is not None and generation_mode == BROWSER_ASSISTED_COMBINED_DISCOVERY:
        candidates = _browser_query_discovery_candidates(runner, browser_context)
        page_id = browser_context.get("page_id") or "CURRENT"
        candidates_path = builder.crf_path / f"CDMS-Agent_rule_discovery_candidates_{page_id}_v0.2.json"
        candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        return _gen_combined_discovery_cells(
            builder=builder,
            browser_context=browser_context,
            candidates=candidates,
            candidates_path=candidates_path,
            run_availability=True,
        )
    if browser_context is not None and generation_mode == BROWSER_ASSISTED_QUERY_EXPECTED:
        cases = _browser_query_expected_cases(runner, browser_context)
    elif browser_context is not None:
        cases = _browser_input_cases(browser_context, final_action=final_action)
    else:
        plan = runner.plan(
            include_query=False,
            include_visibility=include_visibility,
            include_availability=include_availability,
        )
        cases = [case for case in plan.all if case.runnable]
    cells: list[dict[str, Any]] = []
    if browser_context is not None:
        if generation_mode == BROWSER_ASSISTED_QUERY_EXPECTED:
            cells.append(_markdown_cell(_browser_query_context_markdown(runner, browser_context, len(cases))))
        else:
            cells.append(_markdown_cell(_browser_context_markdown(browser_context, len(cases))))
    for index, case in enumerate(cases[:max_case_cells]):
        description = _case_description(case)
        cells.append(_markdown_cell(
            f"### Case {index}: {case.id}\n\n"
            f"{description}\n\n"
            f"Page: `{case.page}`"
        ))
        current_page = browser_context.get("page_id") if browser_context and browser_context.get("filter_applied") else None
        cells.extend(_case_step_cells(case, index, current_page=current_page, final_action=final_action))
    return cells


def _browser_context() -> dict[str, Any]:
    from cdm_agent_client import CDMSAgent

    agent = CDMSAgent()
    clients = agent.clients()
    client_id = clients[0].get("clientId") if clients else None
    snap = agent.inspect(client_id=client_id)
    page_id = _page_id_from_path(snap.pathname)
    visible_rows = {str(row).strip() for row in snap.visible_rows if str(row).strip()}
    return {
        "client_id": client_id,
        "page_id": page_id,
        "page_label": snap.page_label,
        "pathname": snap.pathname,
        "visible_rows": visible_rows,
        "structured_rows": snap.structured_rows,
    }


def _page_id_from_path(pathname: str | None) -> str | None:
    if not pathname:
        return None
    parts = [part for part in str(pathname).split("/") if part]
    if len(parts) >= 2 and parts[-1].isdigit():
        return parts[-2]
    return parts[-1] if parts else None


def _browser_assisted_cases(cases: list[Any], context: dict[str, Any]) -> list[Any]:
    current_page = context.get("page_id")
    visible_rows = context.get("visible_rows") or set()
    if current_page and any(str(case.page) == str(current_page) for case in cases):
        context["filter_applied"] = True
        return [case for case in cases if _case_matches_browser(case, current_page, visible_rows)]
    context["filter_applied"] = False
    return cases


def _browser_input_cases(context: dict[str, Any], *, final_action: str = "save_next") -> list[Any]:
    from .models import CRFCase, Step

    page_id = context.get("page_id") or ""
    visit_id = _visit_id_from_path(context.get("pathname"))
    steps: list[Step] = []
    seen: set[str] = set()
    for row in context.get("structured_rows") or []:
        label = str(row.get("rowLabel") or "").strip()
        visible = bool(row.get("visible", True))
        editable = bool(row.get("editable", False))
        if not label or label in seen or _skip_browser_row(label):
            continue
        if not visible:
            continue
        if not editable and not _force_include_browser_row(label) and not (row.get("options") and row.get("controlType")):
            continue
        seen.add(label)
        step = _input_step_from_row(label, row, page_id=page_id, visit_id=visit_id)
        if step:
            steps.append(step)
    if steps:
        method = "click_save_next" if final_action == "save_next" else "click_save"
        steps.append(Step(method, [], {"page_id": page_id or None, "visit_id": visit_id}))
    if not steps:
        return []
    return [
        CRFCase(
            kind="browser_input",
            id=f"{page_id or 'CURRENT'}_INPUT",
            page=page_id or "CURRENT",
            label=str(context.get("page_label") or ""),
            note="connected browser page input smoke",
            steps=steps,
        )
    ]


def _browser_query_expected_cases(runner: Any, context: dict[str, Any]) -> list[Any]:
    return [
        _browser_query_case(runner, context, expect_query=True),
        _browser_query_case(runner, context, expect_query=False),
    ]


def _browser_query_discovery_candidates(runner: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    return _rule_discovery.build_browser_query_discovery_candidates(runner, context)


def _browser_availability_discovery_candidates(runner: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    return _availability_discovery.build_browser_availability_discovery_candidates(runner, context)


def _query_discovery_candidates_for_intent(runner: Any, context: dict[str, Any], *, expect_query: bool) -> list[dict[str, Any]]:
    page_id = context.get("page_id") or ""
    row_labels = _current_input_row_labels(context)
    intent = "query 발생 후보" if expect_query else "query 미발생 후보"
    candidates: list[dict[str, Any]] = []
    for case in runner.query_cases(expect_query=expect_query):
        if str(case.page) != str(page_id):
            continue
        steps = []
        seen: set[str] = set()
        for step in case.steps:
            if step.method not in {"set_text", "set_date", "select_radio", "select_option"} or not step.args:
                continue
            label = str(step.args[0]).strip()
            step_page = step.kwargs.get("page_id")
            if step_page and str(step_page) != str(page_id):
                continue
            if label not in row_labels and not _force_include_browser_row(label):
                continue
            if label in seen:
                continue
            seen.add(label)
            steps.append(_query_mode_step(step, expect_query=expect_query))
        if not steps:
            continue
        evidence = case.note or "CRF query rule 후보"
        if case.errors:
            evidence += " / manual review 필요: " + "; ".join(case.errors[:2])
        expected_result = "query_expected" if expect_query else "no_query_expected"
        candidates.append(
            {
                "name": case.id,
                "intent": intent,
                "evidence": evidence,
                "DVS ID": case.id,
                "item_id": case.id,
                "item_label": case.label or _first_step_label(steps),
                "rule_type": _rule_type_for_case(case),
                "rule_source": "CRF+Browser",
                "Specification": _specification_for_case(case),
                "Expected Result": expected_result,
                "steps": _steps_to_discovery_dicts(steps),
            }
        )
    return candidates


def _first_step_label(steps: list[Any]) -> str:
    for step in steps:
        if step.args:
            label = str(step.args[0]).strip()
            if label:
                return label
    return ""


def _rule_type_for_case(case: Any) -> str:
    note = str(getattr(case, "note", "") or "").lower()
    kind = str(getattr(case, "kind", "") or "").lower()
    if "availability" in kind or "availability" in note:
        return "availability"
    if "visibility" in kind or "visibility" in note:
        return "visibility"
    if "disabled" in note or "readonly" in note or "locked" in note:
        return "disability"
    if "missing" in note or "required" in note or "누락" in note:
        return "missing_query"
    if any(token in note for token in ("range", "min", "max", "<", ">", "이상", "이하", "범위")):
        return "range_query"
    if any(token in note for token in ("option", "radio", "select", "선택")):
        return "option_query"
    if "query" in kind or "query" in note:
        return "query"
    return "unknown"


def _specification_for_case(case: Any) -> str:
    note = str(getattr(case, "note", "") or "").strip()
    if note:
        return note
    case_id = str(getattr(case, "id", "") or "").strip()
    return f"CRF query trigger candidate: {case_id}" if case_id else "CRF query trigger candidate"


def _steps_to_discovery_dicts(steps: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "method": step.method,
            "args": list(step.args),
            "kwargs": dict(step.kwargs),
            "note": step.note,
        }
        for step in steps
    ]


def _browser_query_case(runner: Any, context: dict[str, Any], *, expect_query: bool):
    from .models import CRFCase, Step

    page_id = context.get("page_id") or ""
    visit_id = _visit_id_from_path(context.get("pathname"))
    row_labels = _current_input_row_labels(context)
    raw_cases = runner.query_cases(expect_query=expect_query)
    steps: list[Step] = []
    seen: set[str] = set()
    evidence: list[str] = []

    for case in raw_cases:
        if str(case.page) != str(page_id):
            continue
        if case.errors:
            evidence.append(f"{case.id}: manual review 필요 - {'; '.join(case.errors[:2])}")
        else:
            evidence.append(f"{case.id}: {case.note or 'query rule 후보'}")
        for step in case.steps:
            if step.method not in {"set_text", "set_date", "select_radio", "select_option"} or not step.args:
                continue
            label = str(step.args[0]).strip()
            step_page = step.kwargs.get("page_id")
            if step_page and str(step_page) != str(page_id):
                continue
            if label not in row_labels and not _force_include_browser_row(label):
                continue
            if label in seen:
                continue
            seen.add(label)
            steps.append(_query_mode_step(step, expect_query=expect_query))

    if not steps:
        steps = _fallback_query_steps(context, expect_query=expect_query)

    steps.append(Step("click_save", [], {"page_id": page_id or None, "visit_id": visit_id}, note="save_and_inspect"))
    title = "query 발생 예상" if expect_query else "query 미발생 예상"
    return CRFCase(
        kind=f"browser_assisted_{'query_expected' if expect_query else 'query_not_expected'}",
        id=f"{page_id or 'CURRENT'}_{'QUERY_EXPECTED' if expect_query else 'QUERY_NOT_EXPECTED'}",
        page=page_id or "CURRENT",
        label=str(context.get("page_label") or ""),
        note=f"{title} 입력 - " + "; ".join(evidence[:6]),
        steps=steps,
    )


def _current_input_row_labels(context: dict[str, Any]) -> set[str]:
    return _row_matcher.current_input_row_labels(context)


def _query_mode_step(step: Any, *, expect_query: bool):
    return _value_planner.query_mode_step(step, expect_query=expect_query)


def _fallback_query_steps(context: dict[str, Any], *, expect_query: bool) -> list[Any]:
    return _value_planner.fallback_query_steps(context, expect_query=expect_query)


def _visit_id_from_path(pathname: str | None) -> str | None:
    if not pathname:
        return None
    parts = [part for part in str(pathname).split("/") if part]
    if len(parts) >= 4:
        return parts[-4]
    return None


def _skip_browser_row(label: str) -> bool:
    return _row_matcher.skip_browser_row(label)


def _force_include_browser_row(label: str) -> bool:
    return _row_matcher.force_include_browser_row(label)


def _input_step_from_row(label: str, row: dict[str, Any], *, page_id: str, visit_id: str | None):
    return _value_planner.input_step_from_row(label, row, page_id=page_id, visit_id=visit_id)


def _preferred_option(label: str, row: dict[str, Any]) -> str | None:
    return _value_planner.preferred_option(label, row)


def _default_date_for(label: str) -> str:
    return _value_planner.default_date_for(label)


def _default_text_for(label: str) -> str:
    return _value_planner.default_text_for(label)


def _numeric_discovery_value_for(label: str, *, expect_query: bool) -> str | None:
    return _value_planner.numeric_discovery_value_for(label, expect_query=expect_query)


def _normalize_label(label: str) -> str:
    return _row_matcher.normalize_label(label)


def _case_matches_browser(case: Any, current_page: str | None, visible_rows: set[str]) -> bool:
    if current_page and str(case.page) != str(current_page):
        return False
    return True


def _step_row_labels(steps: list[Any]) -> set[str]:
    labels: set[str] = set()
    for step in steps:
        if step.method in {"set_text", "set_date", "select_radio", "select_option"} and step.args:
            label = str(step.args[0]).strip()
            if label:
                labels.add(label)
    return labels


def _browser_context_markdown(context: dict[str, Any], case_count: int) -> str:
    rows = sorted(context.get("visible_rows") or [])
    shown_rows = ", ".join(f"`{row}`" for row in rows[:20])
    if len(rows) > 20:
        shown_rows += f", ... (+{len(rows) - 20})"
    return (
        "## Browser-Assisted Input\n\n"
        f"Current page: `{context.get('page_id') or ''}` / `{context.get('page_label') or ''}`\n\n"
        f"Path: `{context.get('pathname') or ''}`\n\n"
        f"Client ID: `{context.get('client_id') or ''}`\n\n"
        f"Generated input cases from connected page: `{case_count}`\n\n"
        f"Visible row candidates: {shown_rows or '`(none)`'}"
    )


def _browser_query_context_markdown(runner: Any, context: dict[str, Any], case_count: int) -> str:
    rows = sorted(_current_input_row_labels(context))
    shown_rows = ", ".join(f"`{row}`" for row in rows[:20])
    if len(rows) > 20:
        shown_rows += f", ... (+{len(rows) - 20})"
    page_id = context.get("page_id") or ""
    query_candidates = [case for case in runner.query_cases(expect_query=True) if str(case.page) == str(page_id)]
    shown_rules = ", ".join(f"`{case.id}`" for case in query_candidates[:12])
    if len(query_candidates) > 12:
        shown_rules += f", ... (+{len(query_candidates) - 12})"
    return (
        "## Browser-Assisted Query Expected Input\n\n"
        "현재 페이지 하나만 대상으로 inspection row와 CRF query rule 후보를 함께 사용합니다. "
        "실제 저장 후 query 발생 여부는 자동 판정하지 않고, 사람이 화면 피드백을 확인합니다.\n\n"
        f"Current page: `{page_id}` / `{context.get('page_label') or ''}`\n\n"
        f"Path: `{context.get('pathname') or ''}`\n\n"
        f"Client ID: `{context.get('client_id') or ''}`\n\n"
        f"Generated query 예상 cases from connected page: `{case_count}`\n\n"
        f"Inspection input rows: {shown_rows or '`(none)`'}\n\n"
        f"CRF query rule 후보: {shown_rules or '`(none)`'}"
    )


def _browser_query_discovery_markdown(runner: Any, context: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    rows = sorted(_current_input_row_labels(context))
    shown_rows = ", ".join(f"`{row}`" for row in rows[:20])
    if len(rows) > 20:
        shown_rows += f", ... (+{len(rows) - 20})"
    page_id = context.get("page_id") or ""
    query_rules = [case for case in runner.query_cases(expect_query=True) if str(case.page) == str(page_id)]
    shown_rules = ", ".join(f"`{case.id}`" for case in query_rules[:12])
    if len(query_rules) > 12:
        shown_rules += f", ... (+{len(query_rules) - 12})"
    return (
        "## Browser-Assisted Query Discovery Loop\n\n"
        "현재 페이지 하나만 대상으로 query 발생 후보와 query 미발생 후보를 실제 저장해보고, "
        "저장 후 inspect에서 관찰된 Query row를 결과표로 누적합니다. "
        "이 셀은 assert가 아니라 observation/discovery result를 남기는 하네스입니다.\n\n"
        f"Current page: `{page_id}` / `{context.get('page_label') or ''}`\n\n"
        f"Path: `{context.get('pathname') or ''}`\n\n"
        f"Client ID: `{context.get('client_id') or ''}`\n\n"
        f"Discovery candidates: `{len(candidates)}`\n\n"
        f"Inspection input rows: {shown_rows or '`(none)`'}\n\n"
        f"CRF query rule 후보: {shown_rules or '`(none)`'}"
    )


def _browser_availability_discovery_markdown(context: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    rows = sorted(_current_input_row_labels(context))
    shown_rows = ", ".join(f"`{row}`" for row in rows[:20])
    if len(rows) > 20:
        shown_rows += f", ... (+{len(rows) - 20})"
    return (
        "## Browser-Assisted Availability Discovery Loop\n\n"
        "현재 페이지 하나만 대상으로 CRF availability 조건 후보를 만들고, "
        "조건 입력 전후의 `row_availability`, `row_disability`, `editable` 상태를 관찰합니다. "
        "저장 후 판정이 아니라 before/after observation을 남기는 하네스입니다.\n\n"
        f"Current page: `{context.get('page_id') or ''}` / `{context.get('page_label') or ''}`\n\n"
        f"Path: `{context.get('pathname') or ''}`\n\n"
        f"Client ID: `{context.get('client_id') or ''}`\n\n"
        f"Availability candidates: `{len(candidates)}`\n\n"
        f"Inspection input rows: {shown_rows or '`(none)`'}"
    )


def _browser_availability_discovery_code(
    context: dict[str, Any],
    *,
    export_path: Path | None = None,
    candidates_path: Path | None = None,
) -> str:
    page_id = context.get("page_id") or ""
    visit_id = _visit_id_from_path(context.get("pathname"))
    export_value = str(export_path) if export_path else ""
    candidates_value = str(candidates_path) if candidates_path else ""
    return (
        "from cdm_agent_client.crf.availability_discovery_runtime import (\n"
        "    display_availability_discovery_tables,\n"
        "    export_availability_discovery_result,\n"
        "    load_availability_candidates,\n"
        "    run_availability_discovery_loop,\n"
        ")\n\n"
        f"AVAILABILITY_PAGE_ID = {page_id!r}\n"
        f"AVAILABILITY_VISIT_ID = {visit_id!r}\n"
        f"AVAILABILITY_EXPORT_PATH = {export_value!r}\n"
        f"AVAILABILITY_CANDIDATES_PATH = {candidates_value!r}\n"
        "SAVE_AFTER_EACH_AVAILABILITY_CHECK = False\n\n"
        "AVAILABILITY_CANDIDATES = load_availability_candidates(AVAILABILITY_CANDIDATES_PATH)\n"
        "availability_discovery_result = run_availability_discovery_loop(\n"
        "    agent,\n"
        "    AVAILABILITY_CANDIDATES,\n"
        "    page_id=AVAILABILITY_PAGE_ID,\n"
        "    visit_id=AVAILABILITY_VISIT_ID,\n"
        "    step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        "    save_after_each=SAVE_AFTER_EACH_AVAILABILITY_CHECK,\n"
        ")\n"
        "display_availability_discovery_tables(availability_discovery_result)\n"
        "export_availability_discovery_result(availability_discovery_result, AVAILABILITY_EXPORT_PATH)\n"
    )


def _browser_query_discovery_code(
    context: dict[str, Any],
    *,
    export_path: Path | None = None,
    candidates_path: Path | None = None,
) -> str:
    page_id = context.get("page_id") or ""
    visit_id = _visit_id_from_path(context.get("pathname"))
    export_value = str(export_path) if export_path else ""
    candidates_value = str(candidates_path) if candidates_path else ""
    return (
        "from cdm_agent_client.crf.rule_discovery_runtime import (\n"
        "    display_rule_discovery_tables,\n"
        "    export_rule_discovery_result,\n"
        "    load_candidates,\n"
        "    run_rule_discovery_loop,\n"
        ")\n\n"
        f"DISCOVERY_PAGE_ID = {page_id!r}\n"
        f"DISCOVERY_VISIT_ID = {visit_id!r}\n"
        f"RULE_DISCOVERY_EXPORT_PATH = {export_value!r}\n"
        f"DISCOVERY_CANDIDATES_PATH = {candidates_value!r}\n\n"
        "DISCOVERY_CANDIDATES = load_candidates(DISCOVERY_CANDIDATES_PATH)\n"
        "rule_discovery_result = run_rule_discovery_loop(\n"
        "    agent,\n"
        "    DISCOVERY_CANDIDATES,\n"
        "    page_id=DISCOVERY_PAGE_ID,\n"
        "    visit_id=DISCOVERY_VISIT_ID,\n"
        "    step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        "    post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        ")\n"
        "display_rule_discovery_tables(rule_discovery_result)\n"
        "export_rule_discovery_result(rule_discovery_result, RULE_DISCOVERY_EXPORT_PATH)\n"
    )


def _case_step_cells(case, index: int, *, current_page: str | None = None, final_action: str = "save_next") -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    checks_by_step: dict[int | None, list[Any]] = {}
    for check in case.checks:
        checks_by_step.setdefault(check.after_step, []).append(check)

    chunk: list[tuple[int, Any]] = []
    chunk_index = 1

    def chunk_code_steps() -> list[Any]:
        steps = [step for _, step in chunk]
        if steps and steps[-1].method not in {"click_save", "click_save_next"}:
            steps = [*steps, _save_step_for_chunk(steps, final_action=final_action)]
        if current_page:
            steps = [step for step in steps if not _is_current_page_nav(step, current_page)]
        return steps

    def flush_chunk() -> None:
        nonlocal chunk, chunk_index
        if not chunk:
            return
        start = chunk[0][0]
        end = chunk[-1][0]
        steps = chunk_code_steps()
        methods = " -> ".join(step.method for step in steps)
        description = _case_description(case, steps)
        cells.append(_markdown_cell(
            f"#### Case {index}.{chunk_index}: {case.id}\n\n"
            f"{description}\n\n"
            f"`{methods}`"
        ))
        code = (
            f"# CASE_INDEX = {index}\n"
            f"# CASE_ID = {case.id!r}\n"
            f"# STEPS = {start}-{end}/{len(case.steps)}\n"
            f"# DESCRIPTION = {description!r}\n"
            f"# NOTE = {chunk[-1][1].note!r}\n"
            + "\n".join(_step_to_observable_code(step) for step in steps)
            + "\n"
        )
        cells.append(_code_cell(code))
        chunk = []
        chunk_index += 1

    for step_index, step in enumerate(case.steps, start=1):
        chunk.append((step_index, step))
        if step.method in {"click_save", "click_save_next"}:
            flush_chunk()

    flush_chunk()

    for check in checks_by_step.get(None, []):
        cells.append(_markdown_cell(f"#### Case {index}: final check"))
        cells.append(_code_cell(_check_code(check)))

    return cells


def _is_current_page_nav(step: Any, current_page: str) -> bool:
    if step.method != "go_to_page" or not step.args:
        return False
    segment = str(step.args[0]).strip("/")
    parts = [part for part in segment.split("/") if part]
    target_page = parts[-1] if parts else ""
    return target_page == current_page


def _step_to_observable_code(step: Any) -> str:
    call = step.to_code("agent")
    if step.method == "click_save_next":
        return (
            "if PAUSE_BEFORE_SAVE:\n"
            "    input('Review browser feedback, then press Enter to Save & Next...')\n"
            "try:\n"
            f"    result = {call}\n"
            "    print('Save & Next result:', getattr(result, 'raw', result))\n"
            "except Exception as exc:\n"
            "    print('Save & Next error:', exc)\n"
            "finally:\n"
            "    time.sleep(POST_SAVE_DELAY_SECONDS)\n"
            "    snap_after = agent.inspect()\n"
            "    print('After Save & Next page:', snap_after.page_label)\n"
            "    print('After Save & Next path:', snap_after.pathname)\n"
            "    print('Visible rows:', snap_after.visible_rows[:30])\n"
            "    print('Structured rows:', [\n"
            "        {\n"
            "            'rowLabel': row.get('rowLabel'),\n"
            "            'controlType': row.get('controlType'),\n"
            "            'editable': row.get('editable'),\n"
            "            'row_availability': row.get('row_availability'),\n"
            "            'row_disability': row.get('row_disability'),\n"
            "        }\n"
            "        for row in (snap_after.structured_rows or [])[:20]\n"
            "    ])"
        )
    if step.method == "click_save":
        if step.note == "save_and_inspect":
            return (
                "if PAUSE_BEFORE_SAVE:\n"
                "    input('Review values, then press Enter to Save...')\n"
                "try:\n"
                f"    result = {call}\n"
                "    print('Save result:', getattr(result, 'raw', result))\n"
                "except Exception as exc:\n"
                "    print('Save error:', exc)\n"
                "finally:\n"
                "    time.sleep(POST_SAVE_DELAY_SECONDS)\n"
                "    snap_after = agent.inspect()\n"
                "    print('After Save page:', snap_after.page_label)\n"
                "    print('After Save path:', snap_after.pathname)\n"
                "    print('Visible rows:', snap_after.visible_rows[:30])\n"
                "    print('Structured rows:', [\n"
                "        {\n"
                "            'rowLabel': row.get('rowLabel'),\n"
                "            'controlType': row.get('controlType'),\n"
                "            'editable': row.get('editable'),\n"
                "            'row_availability': row.get('row_availability'),\n"
                "            'row_disability': row.get('row_disability'),\n"
                "        }\n"
                "        for row in (snap_after.structured_rows or [])[:20]\n"
                "    ])"
            )
        return (
            "if PAUSE_BEFORE_SAVE:\n"
            "    input('Review browser feedback, then press Enter to Save...')\n"
            f"{call}\n"
            "time.sleep(POST_SAVE_DELAY_SECONDS)"
        )
    if step.method == "set_date":
        return (
            f"{call}\n"
            "if RUN_STEP_DELAY_SECONDS:\n"
            "    time.sleep(RUN_STEP_DELAY_SECONDS)"
        )
    return (
        f"{call}\n"
        "if RUN_STEP_DELAY_SECONDS:\n"
        "    time.sleep(RUN_STEP_DELAY_SECONDS)"
    )


def _has_save_step(steps: list[Any]) -> bool:
    return any(step.method in {"click_save", "click_save_next"} for step in steps)


def _post_save_probe_code(expected: str) -> str:
    return ""


def _save_step_for_chunk(steps: list[Any], *, final_action: str = "save_next") -> Any:
    from .models import Step

    page_id = None
    visit_id = None
    for step in reversed(steps):
        page_id = step.kwargs.get("page_id") or page_id
        visit_id = step.kwargs.get("visit_id") or visit_id
        if page_id:
            break
        if step.method == "go_to_page" and step.args:
            segment = str(step.args[0]).strip("/")
            parts = segment.split("/")
            if len(parts) >= 2:
                visit_id, page_id = parts[-2], parts[-1]
            elif parts:
                page_id = parts[-1]
            break
    method = "click_save_next" if final_action == "save_next" else "click_save"
    return Step(method, [], {"page_id": page_id, "visit_id": visit_id})


def _case_description(case, steps: list[Any] | None = None) -> str:
    if case.kind == "browser_assisted_query_expected":
        return "현재 페이지 query 발생 예상 입력"
    if case.kind == "browser_assisted_query_not_expected":
        return "현재 페이지 query 미발생 예상 입력"
    text = case.note or ""
    active_steps = steps or case.steps
    main_step = next((step for step in active_steps if step.method in {"set_text", "set_date"} and len(step.args) >= 2), None)
    if main_step is None and steps is not None:
        return _case_description(case)

    if "19 <= AGE < 65" in text or "만 19세 이상 65세 미만" in text:
        if str(case.id).endswith("_1"):
            return "최소 나이 경계값 미만 테스트" if case.expect == "Query" else "최소 나이 경계값 테스트"
        if str(case.id).endswith("_2"):
            return "최대 나이 경계값 초과 테스트" if case.expect == "Query" else "최대 나이 경계값 테스트"

    if main_step is not None:
        label = str(main_step.args[0])
        value = _to_float(main_step.args[1])
        if value is not None:
            lower = _numeric_bound(text, ">=")
            upper = _numeric_bound(text, "<=")
            if lower is not None:
                if value < lower:
                    return f"{label} 최소 경계값 미만 테스트: {value:g} < {lower:g}"
                if value == lower:
                    return f"{label} 최소 경계값 테스트: {value:g}"
            if upper is not None:
                if value > upper:
                    return f"{label} 최대 경계값 초과 테스트: {value:g} > {upper:g}"
                if value == upper:
                    return f"{label} 최대 경계값 테스트: {value:g}"

    return "자동 생성 입력 테스트"


def _numeric_bound(text: str, operator: str) -> float | None:
    pattern = rf"{re.escape(operator)}\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


def _check_code(check) -> str:
    if check.check_type == "query":
        return "# Query check removed. Review browser feedback manually after Save.\n"
    if check.check_type == "visible":
        return (
            "snap = agent.inspect()\n"
            f"print({check.label!r}, 'visible =', {check.label!r} in snap.visible_rows)\n"
        )
    if check.check_type == "not_visible":
        return (
            "snap = agent.inspect()\n"
            f"print({check.label!r}, 'hidden =', {check.label!r} not in snap.visible_rows)\n"
        )
    return f"# Unsupported check: {check.check_type!r}\n"


def _setup_cell(builder: CRFNotebookBuilder) -> dict[str, Any]:
    return _code_cell(
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "import pandas as pd\n\n"
        f"AGENT_ROOT = Path(r'{builder.agent_project_root}')\n"
        "if str(AGENT_ROOT / 'src') not in sys.path:\n"
        "    sys.path.insert(0, str(AGENT_ROOT / 'src'))\n\n"
        "from cdm_agent_client import CDMSAgent\n"
        "from cdm_agent_client.crf import CRFRunner\n\n"
        f"CRF_PATH = Path(r'{builder.crf_path}')\n"
        "# None이면 CRFRunner가 folders.ts/spec에서 visit map을 자동 추출합니다.\n"
        f"VISIT_MAP = {builder.visit_map!r}\n"
        "# None이면 전체 page를 대상으로 생성하고, {'DM'}처럼 지정하면 해당 page만 좁힙니다.\n"
        f"PAGE_IDS = {builder.page_ids!r}\n"
        "\n"
        "# Review controls for generated validation cells.\n"
        "PAUSE_BEFORE_SAVE = True\n"
        "RUN_STEP_DELAY_SECONDS = 0.4\n"
        "POST_SAVE_DELAY_SECONDS = 1.0\n"
    )


def _load_spec_cell() -> dict[str, Any]:
    return _code_cell(
        "from cdm_agent_client.crf.trigger_matcher import summarize_triggers\n\n"
        "runner = CRFRunner(crf_path=CRF_PATH, visit_map=VISIT_MAP, page_ids=PAGE_IDS)\n"
        "runner.load_spec()\n"
        "display(runner.summary())\n"
        "\n"
        "all_runner = CRFRunner(crf_path=CRF_PATH, visit_map=VISIT_MAP, page_ids=None)\n"
        "all_runner.load_spec()\n"
        "all_triggers = (all_runner._spec or {}).get('triggers', [])\n"
        "print('Total triggers in CRF code:', len(all_triggers))\n"
        "\n"
        "all_trigger_summary = pd.DataFrame(\n"
        "    summarize_triggers(all_triggers, current_page_id=None)\n"
        ")\n"
        "display(all_trigger_summary[all_trigger_summary['scope'] == 'all_crf'])\n"
    )


def _build_cases_cell(include_query: bool, include_visibility: bool, include_availability: bool, generation_mode: str) -> dict[str, Any]:
    return _code_cell(
        f"GENERATION_MODE = {generation_mode!r}\n"
        "plan = runner.plan(\n"
        "    include_query=False,\n"
        f"    include_visibility={include_visibility!r},\n"
        f"    include_availability={include_availability!r},\n"
        ")\n"
        "cases = plan.all\n"
        "cases_df = plan.to_dataframe()\n"
        "display(cases_df)\n"
    )


def _connect_agent_cell() -> dict[str, Any]:
    return _code_cell(
        "from cdm_agent_client.crf.trigger_matcher import summarize_triggers, trigger_references_page\n\n"
        "def _page_id_from_path(pathname):\n"
        "    if not pathname:\n"
        "        return None\n"
        "    parts = [part for part in str(pathname).split('/') if part]\n"
        "    if len(parts) >= 2 and parts[-1].isdigit():\n"
        "        return parts[-2]\n"
        "    return parts[-1] if parts else None\n"
        "\n"
        "agent = CDMSAgent()\n"
        "print('Daemon connected:', agent.ping())\n"
        "clients = agent.clients()\n"
        "CLIENT_ID = clients[0]['clientId'] if clients else None\n"
        "print('Client ID:', CLIENT_ID)\n"
        "\n"
        "def _bind_client_id(method_name):\n"
        "    original = getattr(agent, method_name)\n"
        "    def wrapped(*args, **kwargs):\n"
        "        if CLIENT_ID and 'client_id' not in kwargs:\n"
        "            kwargs['client_id'] = CLIENT_ID\n"
        "        return original(*args, **kwargs)\n"
        "    setattr(agent, method_name, wrapped)\n"
        "\n"
        "for _method in ['inspect', 'go_to_page', 'navigate_to', 'click_save', 'click_save_next',\n"
        "                'set_text', 'set_date', 'select_radio', 'select_option',\n"
        "               ]:\n"
        "    if hasattr(agent, _method):\n"
        "        _bind_client_id(_method)\n"
        "\n"
        "snap = agent.inspect()\n"
        "print('Current page:', snap.page_label)\n"
        "print('Path:', snap.pathname)\n"
        "current_page_id = _page_id_from_path(snap.pathname)\n"
        "print('Current page ID:', current_page_id)\n"
        "\n"
        "current_page_triggers = [\n"
        "    trigger for trigger in all_triggers\n"
        "    if trigger_references_page(trigger, current_page_id)\n"
        "]\n"
        "print('Current page triggers:', len(current_page_triggers))\n"
        "\n"
        "trigger_summary = pd.DataFrame(\n"
        "    summarize_triggers(all_triggers, current_page_id=current_page_id)\n"
        ")\n"
        "display(trigger_summary)\n"
        "\n"
        "trigger_type_pivot = trigger_summary.pivot_table(\n"
        "    index='dvs_type',\n"
        "    columns='scope',\n"
        "    values='count',\n"
        "    fill_value=0,\n"
        ")\n"
        "display(trigger_type_pivot)\n"
    )


def _preview_cell() -> dict[str, Any]:
    return _code_cell(
        "RUNNABLE_ONLY = True\n"
        "preview_df = cases_df.copy()\n"
        "if RUNNABLE_ONLY:\n"
        "    preview_df = preview_df[preview_df['runnable']]\n"
        "display(preview_df[['kind', 'id', 'page', 'label', 'steps', 'checks', 'errors']])\n"
    )


# ---------------------------------------------------------------------------
# Combined Discovery Notebook generation (query + availability together)
# ---------------------------------------------------------------------------


def gen_combined_discovery_notebook(
    output_path: "str | Path | None" = None,
    *,
    crf_path: "str | Path | None" = None,
    candidates_path: "str | Path | None" = None,
    page_id: "str | None" = None,
    visit_id: "str | None" = None,
    agent_project_root: "str | Path | None" = None,
    visit_map: "dict | None" = None,
    page_ids: "list | None" = None,
    run_availability: bool = True,
) -> Path:
    """Generate a comprehensive combined query + availability discovery notebook.

    If *candidates_path* is provided, uses the existing candidates JSON.
    Otherwise expects the JSON at the default ``CDMS-Agent_rule_discovery_candidates_{page_id}_v0.2.json`` path.
    """
    builder = CRFNotebookBuilder(
        crf_path=crf_path,
        agent_project_root=agent_project_root,
        visit_map=visit_map,
        page_ids=page_ids or ([page_id] if page_id else None),
    )

    _page_id = page_id or (builder.page_ids[0] if builder.page_ids else "CURRENT")

    if candidates_path is None:
        candidates_path = builder.crf_path / f"CDMS-Agent_rule_discovery_candidates_{_page_id}_v0.2.json"
    candidates_path = Path(candidates_path)

    if not candidates_path.exists():
        raise FileNotFoundError(
            f"Candidates JSON not found: {candidates_path}\n"
            "먼저 BROWSER_ASSISTED_QUERY_DISCOVERY 모드로 candidates JSON을 생성하세요."
        )

    with candidates_path.open("r", encoding="utf-8") as fh:
        candidates = json.load(fh)

    out = Path(output_path) if output_path else (
        builder.crf_path / f"CDMS-Agent_rule_discovery_{_page_id}_combined.ipynb"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    cells = _gen_combined_discovery_cells(
        builder=builder,
        browser_context={"page_id": _page_id, "visit_id": visit_id},
        candidates=candidates,
        candidates_path=candidates_path,
        run_availability=run_availability,
    )

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.9.0"},
            "cdms_agent": {"generation_mode": BROWSER_ASSISTED_COMBINED_DISCOVERY},
        },
        "cells": cells,
    }
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _gen_combined_discovery_cells(
    *,
    builder: "CRFNotebookBuilder",
    browser_context: "dict[str, Any]",
    candidates: "list[dict[str, Any]]",
    candidates_path: Path,
    run_availability: bool = True,
) -> "list[dict[str, Any]]":
    page_id = browser_context.get("page_id") or "CURRENT"
    visit_id = browser_context.get("visit_id") or _visit_id_from_path(browser_context.get("pathname"))
    if visit_id is None:
        visit_id = "V1"

    page_ids_repr = repr([page_id])
    query_count = sum(1 for c in candidates if c.get("rule_type") != "availability")
    avail_count = sum(1 for c in candidates if c.get("rule_type") == "availability")
    total_count = len(candidates)

    return [
        _markdown_cell(
            f"# CDMS-Agent Rule Discovery - {page_id}\n\n"
            "Static CRF analysis 기반 후보입니다. "
            "브라우저 이동이 필요하면 해당 페이지를 연 뒤 runtime cell을 실행합니다."
        ),
        _code_cell(_combined_discovery_setup_src(builder, page_ids_repr)),
        _code_cell(_combined_discovery_runner_src()),
        _markdown_cell(
            f"Discovery candidates: `{total_count}` "
            f"(query: `{query_count}`, availability: `{avail_count}`)"
        ),
        _code_cell(_combined_discovery_candidates_src(candidates_path, page_id, visit_id)),
        _code_cell(_combined_discovery_query_group_src(
            "missing_query_candidates", "Missing Query Validation", page_id, visit_id,
            cell_num=3,
        )),
        _code_cell(_combined_discovery_query_group_src(
            "condition_single_candidates", "Condition Query - Single", page_id, visit_id,
            cell_num=4,
        )),
        _code_cell(_combined_discovery_condition_multi_src(page_id, visit_id)),
        _code_cell(_combined_discovery_query_group_src(
            "range_query_candidates", "Range Query", page_id, visit_id,
            cell_num=6,
        )),
        _code_cell(_combined_discovery_skipped_group_src(
            "calculation_query_candidates", "Calculation Query",
            "RUN_CALCULATION_QUERY_CANDIDATES", page_id, visit_id, cell_num=7,
        )),
        _code_cell(_combined_discovery_skipped_group_src(
            "consistency_query_candidates", "Consistency Query",
            "RUN_CONSISTENCY_QUERY_CANDIDATES", page_id, visit_id, cell_num=8,
        )),
        _code_cell(_combined_discovery_availability_review_src()),
        _code_cell(_combined_discovery_availability_loop_src(page_id, visit_id, run_availability)),
        _code_cell(_combined_discovery_sweep_src(page_id, visit_id)),
        _code_cell(_combined_discovery_unsupported_src()),
        _code_cell(_combined_discovery_merge_src()),
    ]


def _combined_discovery_setup_src(builder: "CRFNotebookBuilder", page_ids_repr: str) -> str:
    return (
        "import sys\n"
        "from pathlib import Path\n"
        "import pandas as pd\n\n"
        f"AGENT_ROOT = Path(r'{builder.agent_project_root}')\n"
        "if str(AGENT_ROOT / 'src') not in sys.path:\n"
        "    sys.path.insert(0, str(AGENT_ROOT / 'src'))\n\n"
        "from cdm_agent_client import CDMSAgent\n"
        "from cdm_agent_client.crf import CRFRunner\n\n"
        f"CRF_PATH = Path(r'{builder.crf_path}')\n"
        f"VISIT_MAP = {builder.visit_map!r}\n"
        f"PAGE_IDS = {page_ids_repr}\n"
        "PAUSE_BEFORE_SAVE = True\n"
        "BROWSER_CLIENT_ID = None  # agent.clients()에서 실제 CRF 탭 clientId를 확인한 뒤 필요하면 입력\n"
        "RUN_STEP_DELAY_SECONDS = 0.4\n"
        "POST_SAVE_DELAY_SECONDS = 1.0\n"
        "STABLE_INSPECT_ATTEMPTS = 5\n"
        "STABLE_INSPECT_DELAY_SECONDS = 0.4\n"
        "QUERY_EVENT_TIMEOUT_MS = 3000\n"
        "EXECUTE_PREREQUISITE_STEPS = False  # prerequisite은 기본 query loop에서 자동 실행하지 않음\n"
        "SHOW_CONTROL_QUERY_ROWS = False  # False이면 no_query_expected control row는 최종 표시에서 숨김\n"
    )


def _combined_discovery_runner_src() -> str:
    return (
        "runner = CRFRunner(crf_path=CRF_PATH, visit_map=VISIT_MAP, page_ids=PAGE_IDS)\n"
        "runner.load_spec()\n"
        "display(runner.summary())\n\n"
        "from cdm_agent_client.crf.trigger_matcher import summarize_triggers\n"
        "all_runner = CRFRunner(crf_path=CRF_PATH, visit_map=VISIT_MAP, page_ids=None)\n"
        "all_runner.load_spec()\n"
        "all_triggers = (all_runner._spec or {}).get('triggers', [])\n"
        "trigger_summary = pd.DataFrame(summarize_triggers(all_triggers, current_page_id=PAGE_IDS[0] if PAGE_IDS else None))\n"
        "display(trigger_summary)\n"
    )


def _combined_discovery_candidates_src(candidates_path: Path, page_id: str, visit_id: str) -> str:
    return (
        "from cdm_agent_client.crf.rule_discovery_runtime import (\n"
        "    display_rule_discovery_tables,\n"
        "    load_candidates,\n"
        "    run_rule_discovery_loop,\n"
        ")\n\n"
        f"DISCOVERY_CANDIDATES_PATH = r'{candidates_path}'\n\n"
        "agent = CDMSAgent()\n"
        "DISCOVERY_CANDIDATES = load_candidates(DISCOVERY_CANDIDATES_PATH)\n"
        "query_candidates = [\n"
        "    c for c in DISCOVERY_CANDIDATES\n"
        "    if c.get('rule_type') != 'availability'\n"
        "]\n"
        "missing_query_candidates = [c for c in query_candidates if c.get('query_category') == 'missing_query']\n"
        "condition_single_candidates = [c for c in query_candidates if c.get('query_category') == 'condition_query' and c.get('condition_type', c.get('prerequisite_shape')) == 'single']\n"
        "condition_multi_candidates = [c for c in query_candidates if c.get('query_category') == 'condition_query' and c.get('condition_type', c.get('prerequisite_shape')) == 'multi' and not c.get('requires_prerequisite')]\n"
        "condition_multi_prerequisite_candidates = [c for c in query_candidates if c.get('query_category') == 'condition_query' and c.get('condition_type', c.get('prerequisite_shape')) == 'multi' and c.get('requires_prerequisite')]\n"
        "range_query_candidates = [c for c in query_candidates if c.get('query_category') == 'range_query']\n"
        "calculation_query_candidates = [c for c in query_candidates if c.get('query_category') == 'calculation_query']\n"
        "consistency_query_candidates = [c for c in query_candidates if c.get('query_category') == 'consistency_query']\n"
        "unsupported_query_candidates = [c for c in query_candidates if c.get('query_category') == 'unsupported_query' or c.get('condition_type', c.get('prerequisite_shape')) in {'cross', 'unsupported'}]\n"
        "availability_candidates = [\n"
        "    c for c in DISCOVERY_CANDIDATES\n"
        "    if c.get('rule_type') == 'availability'\n"
        "]\n"
        "candidate_group_summary = pd.DataFrame([\n"
        "    {'group': 'missing_query_candidates', 'count': len(missing_query_candidates)},\n"
        "    {'group': 'condition_single_candidates', 'count': len(condition_single_candidates)},\n"
        "    {'group': 'condition_multi_candidates', 'count': len(condition_multi_candidates)},\n"
        "    {'group': 'condition_multi_prerequisite_candidates', 'count': len(condition_multi_prerequisite_candidates)},\n"
        "    {'group': 'range_query_candidates', 'count': len(range_query_candidates)},\n"
        "    {'group': 'calculation_query_candidates', 'count': len(calculation_query_candidates)},\n"
        "    {'group': 'consistency_query_candidates', 'count': len(consistency_query_candidates)},\n"
        "    {'group': 'unsupported_query_candidates', 'count': len(unsupported_query_candidates)},\n"
        "    {'group': 'availability_candidates', 'count': len(availability_candidates)},\n"
        "])\n"
        "display(candidate_group_summary)\n\n"
        "if query_candidates:\n"
        "    _cs = pd.DataFrame(query_candidates)\n"
        "    _cs['DVS Type'] = _cs.get('rule_type', '')\n"
        "    _cs['Query Category'] = _cs.get('query_category', '')\n"
        "    _cs['Condition Type'] = _cs.get('condition_type', _cs.get('prerequisite_shape', ''))\n"
        "    _mask = _cs['Query Category'].astype(str) == _cs['DVS Type'].astype(str)\n"
        "    _cs.loc[_mask, 'Query Category'] = ''\n"
        "    _cat = _cs.groupby(['DVS Type', 'Query Category', 'Condition Type'], dropna=False).size().reset_index(name='count')\n"
        "    display(_cat)\n\n"
        "QUERY_RESULT_DISPLAY_COLUMNS = [\n"
        "    'DVS ID', 'page_id', 'page_label', 'visit_id', 'item_id', 'item_label',\n"
        "    'DVS Type', 'Query Category', 'Condition Type', 'rule_source',\n"
        "    'Specification', 'Test Script', 'Expected Result', 'observed_query_messages', 'Result',\n"
        "]\n"
        "AVAILABILITY_RESULT_DISPLAY_COLUMNS = [\n"
        "    'DVS ID', 'page_id', 'page_label', 'visit_id', 'item_id', 'item_label',\n"
        "    'DVS Type', 'Availability Category', 'Availability Condition Type', 'rule_source',\n"
        "    'Specification', 'Test Script', 'Expected Result',\n"
        "    'before_availability', 'after_unavailable_availability', 'after_available_availability',\n"
        "    'disappeared_labels', 'appeared_labels',\n"
        "    'target_in_disappeared', 'target_in_appeared',\n"
        "    'availability_step_error', 'Result',\n"
        "]\n\n"
        "def prepare_query_result_display(df):\n"
        "    if df.empty:\n"
        "        return df\n"
        "    df = df.copy()\n"
        "    if not SHOW_CONTROL_QUERY_ROWS and 'Expected Result' in df.columns:\n"
        "        _qe = df[df['Expected Result'].astype(str) == 'query_expected'].copy()\n"
        "        if not _qe.empty:\n"
        "            df = _qe\n"
        "    if 'target_observed_query_count' in df.columns:\n"
        "        df['observed_query_count'] = df['target_observed_query_count']\n"
        "    if 'target_observed_query_messages' in df.columns:\n"
        "        df['observed_query_messages'] = df['target_observed_query_messages']\n"
        "    for _src, _dst in [('rule_type','DVS Type'),('query_category','Query Category'),('condition_type','Condition Type')]:\n"
        "        if _dst not in df.columns and _src in df.columns:\n"
        "            df[_dst] = df[_src]\n"
        "    if 'DVS Type' in df.columns and 'Query Category' in df.columns:\n"
        "        _m = df['Query Category'].astype(str) == df['DVS Type'].astype(str)\n"
        "        df.loc[_m, 'Query Category'] = ''\n"
        "    return df[[c for c in QUERY_RESULT_DISPLAY_COLUMNS if c in df.columns]]\n\n"
        "def prepare_availability_result_display(df):\n"
        "    if df.empty:\n"
        "        return df\n"
        "    df = df.copy()\n"
        "    for _src, _dst in [('rule_type','DVS Type'),('availability_category','Availability Category'),('availability_condition_type','Availability Condition Type')]:\n"
        "        if _dst not in df.columns and _src in df.columns:\n"
        "            df[_dst] = df[_src]\n"
        "    if 'observed_availability_state' not in df.columns and 'availability_target_state' in df.columns:\n"
        "        df['observed_availability_state'] = df['availability_target_state']\n"
        "    return df[[c for c in AVAILABILITY_RESULT_DISPLAY_COLUMNS if c in df.columns]]\n"
    )


def _combined_discovery_query_group_src(
    group_var: str,
    group_name: str,
    page_id: str,
    visit_id: str,
    *,
    cell_num: int,
) -> str:
    result_var = group_var.replace("_candidates", "_result")
    return (
        f"# Cell {cell_num}. {group_name}\n"
        f"{result_var} = run_rule_discovery_loop(\n"
        f"    agent,\n"
        f"    {group_var},\n"
        f"    page_id={page_id!r},\n"
        f"    visit_id={visit_id!r},\n"
        f"    client_id=BROWSER_CLIENT_ID,\n"
        f"    step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        f"    post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        f"    stable_inspect_attempts=STABLE_INSPECT_ATTEMPTS,\n"
        f"    stable_inspect_delay_seconds=STABLE_INSPECT_DELAY_SECONDS,\n"
        f"    query_event_timeout_ms=QUERY_EVENT_TIMEOUT_MS,\n"
        f"    execute_prerequisite_steps=EXECUTE_PREREQUISITE_STEPS,\n"
        f"    query_observation_mode='per_candidate',\n"
        f")\n"
        f"{result_var} = prepare_query_result_display({result_var})\n"
        f"display_rule_discovery_tables({result_var})\n"
    )


def _combined_discovery_condition_multi_src(page_id: str, visit_id: str) -> str:
    return (
        "# Cell 5. Condition Query - Multi\n"
        "RUN_CONDITION_MULTI_CANDIDATES = True\n\n"
        "if RUN_CONDITION_MULTI_CANDIDATES:\n"
        "    condition_multi_result = run_rule_discovery_loop(\n"
        "        agent,\n"
        "        condition_multi_candidates,\n"
        f"        page_id={page_id!r},\n"
        f"        visit_id={visit_id!r},\n"
        "        client_id=BROWSER_CLIENT_ID,\n"
        "        step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        "        post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        "        stable_inspect_attempts=STABLE_INSPECT_ATTEMPTS,\n"
        "        stable_inspect_delay_seconds=STABLE_INSPECT_DELAY_SECONDS,\n"
        "        query_event_timeout_ms=QUERY_EVENT_TIMEOUT_MS,\n"
        "        execute_prerequisite_steps=EXECUTE_PREREQUISITE_STEPS,\n"
        "        query_observation_mode='per_candidate',\n"
        "    )\n"
        "    condition_multi_result = prepare_query_result_display(condition_multi_result)\n"
        "    display_rule_discovery_tables(condition_multi_result)\n"
        "else:\n"
        "    condition_multi_result = pd.DataFrame()\n"
        "    _t = pd.DataFrame(condition_multi_candidates)\n"
        "    if not _t.empty:\n"
        "        _t = _t.rename(columns={'rule_type': 'DVS Type', 'query_category': 'Query Category', 'condition_type': 'Condition Type'})\n"
        "    display(_t[[c for c in ['DVS ID', 'item_id', 'item_label', 'Query Category', 'Condition Type', 'condition_items', 'condition_steps'] if c in _t.columns]] if not _t.empty else _t)\n"
        "    print('Set RUN_CONDITION_MULTI_CANDIDATES=True to run multi condition candidates.')\n\n"
        "condition_multi_prerequisite_review = pd.DataFrame(condition_multi_prerequisite_candidates)\n"
        "if not condition_multi_prerequisite_review.empty:\n"
        "    print('Condition multi candidates requiring prerequisite/row disambiguation are excluded from the default loop:')\n"
        "    condition_multi_prerequisite_review = condition_multi_prerequisite_review.rename(columns={'rule_type': 'DVS Type', 'query_category': 'Query Category', 'condition_type': 'Condition Type'})\n"
        "    _cols = [c for c in ['DVS ID', 'item_id', 'item_label', 'DVS Type', 'Query Category', 'Condition Type', 'requires_prerequisite', 'prerequisite_item_ids', 'prerequisite_steps_count', 'condition_items', 'Specification'] if c in condition_multi_prerequisite_review.columns]\n"
        "    display(condition_multi_prerequisite_review[_cols])\n"
    )


def _combined_discovery_skipped_group_src(
    group_var: str,
    group_name: str,
    run_flag: str,
    page_id: str,
    visit_id: str,
    *,
    cell_num: int,
) -> str:
    result_var = group_var.replace("_candidates", "_result")
    return (
        f"# Cell {cell_num}. {group_name}\n"
        f"{run_flag} = False\n\n"
        f"if {run_flag}:\n"
        f"    {result_var} = run_rule_discovery_loop(\n"
        f"        agent,\n"
        f"        {group_var},\n"
        f"        page_id={page_id!r},\n"
        f"        visit_id={visit_id!r},\n"
        f"        client_id=BROWSER_CLIENT_ID,\n"
        f"        step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        f"        post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        f"        stable_inspect_attempts=STABLE_INSPECT_ATTEMPTS,\n"
        f"        stable_inspect_delay_seconds=STABLE_INSPECT_DELAY_SECONDS,\n"
        f"        query_event_timeout_ms=QUERY_EVENT_TIMEOUT_MS,\n"
        f"        execute_prerequisite_steps=EXECUTE_PREREQUISITE_STEPS,\n"
        f"        query_observation_mode='per_candidate',\n"
        f"    )\n"
        f"    {result_var} = prepare_query_result_display({result_var})\n"
        f"    display_rule_discovery_tables({result_var})\n"
        f"else:\n"
        f"    {result_var} = pd.DataFrame()\n"
        f"    display(pd.DataFrame({group_var}))\n"
    )


def _combined_discovery_availability_review_src() -> str:
    return (
        "# Cell 9. Availability Candidate Review\n"
        "availability_candidate_table = pd.DataFrame([\n"
        "    {\n"
        "        'DVS ID': c.get('DVS ID') or c.get('name'),\n"
        "        'item_id': c.get('item_id'),\n"
        "        'item_label': c.get('item_label'),\n"
        "        'Availability Category': c.get('Availability Category') or c.get('availability_category'),\n"
        "        'Availability Condition Type': c.get('Availability Condition Type') or c.get('availability_condition_type'),\n"
        "        'control_item_id': c.get('control_item_id'),\n"
        "        'control_label': c.get('control_label'),\n"
        "        'availability_condition_items': c.get('availability_condition_items'),\n"
        "        'Specification': c.get('Specification'),\n"
        "    }\n"
        "    for c in availability_candidates\n"
        "])\n"
        "if not availability_candidate_table.empty:\n"
        "    display(availability_candidate_table)\n"
        "print('Review availability candidates here. Run the next cell to validate selected availability rows.')\n"
    )


def _combined_discovery_availability_loop_src(page_id: str, visit_id: str, run_availability: bool) -> str:
    run_val = "True" if run_availability else "False"
    return (
        "# Cell 10. Availability Validation Loop\n"
        f"RUN_AVAILABILITY_VALIDATION = {run_val}\n"
        "TARGET_AVAILABILITY_ITEM_IDS = []  # []이면 모든 availability candidate 실행\n\n"
        "target_availability_candidates = [\n"
        "    c for c in availability_candidates\n"
        "    if not TARGET_AVAILABILITY_ITEM_IDS or c.get('item_id') in TARGET_AVAILABILITY_ITEM_IDS\n"
        "]\n"
        "print('target availability candidates:', len(target_availability_candidates))\n\n"
        "if RUN_AVAILABILITY_VALIDATION and target_availability_candidates:\n"
        "    availability_result = run_rule_discovery_loop(\n"
        "        agent,\n"
        "        target_availability_candidates,\n"
        f"        page_id={page_id!r},\n"
        f"        visit_id={visit_id!r},\n"
        "        client_id=BROWSER_CLIENT_ID,\n"
        "        step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        "        post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        "        stable_inspect_attempts=STABLE_INSPECT_ATTEMPTS,\n"
        "        stable_inspect_delay_seconds=STABLE_INSPECT_DELAY_SECONDS,\n"
        "        query_event_timeout_ms=QUERY_EVENT_TIMEOUT_MS,\n"
        "        execute_prerequisite_steps=False,\n"
        "    )\n"
        "    availability_result = prepare_availability_result_display(availability_result)\n"
        "    display_rule_discovery_tables(availability_result)\n"
        "else:\n"
        "    availability_result = pd.DataFrame()\n"
        "    print('Set RUN_AVAILABILITY_VALIDATION=True to run availability candidates. Use TARGET_AVAILABILITY_ITEM_IDS to limit targets.')\n"
    )


def _combined_discovery_sweep_src(page_id: str, visit_id: str) -> str:
    return (
        "# Cell 11. Sweep Mode\n"
        "RUN_QUERY_SWEEP = False\n"
        "SWEEP_CANDIDATES = query_candidates\n\n"
        "if RUN_QUERY_SWEEP:\n"
        "    query_sweep_result = run_rule_discovery_loop(\n"
        "        agent,\n"
        "        SWEEP_CANDIDATES,\n"
        f"        page_id={page_id!r},\n"
        f"        visit_id={visit_id!r},\n"
        "        client_id=BROWSER_CLIENT_ID,\n"
        "        step_delay_seconds=RUN_STEP_DELAY_SECONDS,\n"
        "        post_save_delay_seconds=POST_SAVE_DELAY_SECONDS,\n"
        "        stable_inspect_attempts=STABLE_INSPECT_ATTEMPTS,\n"
        "        stable_inspect_delay_seconds=STABLE_INSPECT_DELAY_SECONDS,\n"
        "        query_event_timeout_ms=QUERY_EVENT_TIMEOUT_MS,\n"
        "        execute_prerequisite_steps=EXECUTE_PREREQUISITE_STEPS,\n"
        "        query_observation_mode='sweep',\n"
        "    )\n"
        "    display_rule_discovery_tables(prepare_query_result_display(query_sweep_result))\n"
        "else:\n"
        "    query_sweep_result = pd.DataFrame()\n"
        "    print('Set RUN_QUERY_SWEEP=True to run cumulative query sweep mode.')\n"
    )


def _combined_discovery_unsupported_src() -> str:
    return (
        "# Cell 12. Unsupported / Manual Review\n"
        "unsupported_review = pd.DataFrame(unsupported_query_candidates)\n"
        "if not unsupported_review.empty:\n"
        "    unsupported_review = unsupported_review.rename(columns={'rule_type': 'DVS Type', 'query_category': 'Query Category', 'condition_type': 'Condition Type'})\n"
        "    _cols = [c for c in ['DVS ID', 'item_id', 'item_label', 'DVS Type', 'Query Category', 'Condition Type', 'Specification', 'condition_items', 'limitation_reason'] if c in unsupported_review.columns]\n"
        "    display(unsupported_review[_cols])\n"
        "else:\n"
        "    display(unsupported_review)\n"
    )


def _combined_discovery_merge_src() -> str:
    return (
        "# Cell 13. Final Merge\n"
        "validation_frames = [\n"
        "    missing_query_result,\n"
        "    condition_single_result,\n"
        "    condition_multi_result,\n"
        "    range_query_result,\n"
        "    calculation_query_result,\n"
        "    consistency_query_result,\n"
        "]\n"
        "validation_frames = [df for df in validation_frames if isinstance(df, pd.DataFrame) and not df.empty]\n"
        "rule_discovery_result = pd.concat(validation_frames, ignore_index=True) if validation_frames else pd.DataFrame()\n"
        "rule_discovery_result = prepare_query_result_display(rule_discovery_result)\n"
        "display_rule_discovery_tables(rule_discovery_result)\n\n"
        "if isinstance(availability_result, pd.DataFrame) and not availability_result.empty:\n"
        "    print('\\n=== Availability Results ===')\n"
        "    display_rule_discovery_tables(availability_result)\n"
    )
