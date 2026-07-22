from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


DEFAULT_QUERY_AUDIT_TARGETS = (
    "D_DM_1_2",
    "D_PY_3",
    "D_BU_2",
    "D_BQ_2",
)

DEFAULT_CALCULATION_AUDIT_TARGETS = (
    "AGE",
    "BQTOT",
    "BQ_RASCH",
)


@dataclass
class QueryCaseAudit:
    dvs_id: str
    expected_result: str
    trigger_found: bool
    generation_status: str
    case_count: int = 0
    runnable_count: int = 0
    page_id: str = ""
    issue_item_ids: list[str] = field(default_factory=list)
    step_methods: list[str] = field(default_factory=list)
    step_pages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dvs_id": self.dvs_id,
            "expected_result": self.expected_result,
            "trigger_found": self.trigger_found,
            "generation_status": self.generation_status,
            "case_count": self.case_count,
            "runnable_count": self.runnable_count,
            "page_id": self.page_id,
            "issue_item_ids": self.issue_item_ids,
            "step_methods": self.step_methods,
            "step_pages": self.step_pages,
            "errors": self.errors,
            "notes": self.notes,
        }


@dataclass
class CalculationItemAudit:
    page_id: str
    item_id: str
    label: str
    field_type: str
    calculation_subtype: str
    calculate_summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "item_id": self.item_id,
            "label": self.label,
            "field_type": self.field_type,
            "calculation_subtype": self.calculation_subtype,
            "calculate_summary": self.calculate_summary,
        }


def audit_query_cases(
    runner: Any,
    *,
    target_dvs_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Summarize what ``runner.query_cases()`` currently generates.

    Phase 0 intentionally audits existing behavior only. It does not introduce
    dependency graph planning or change candidate generation.
    """

    _require_loaded_runner(runner)
    targets = list(target_dvs_ids or DEFAULT_QUERY_AUDIT_TARGETS)
    triggers = {str(trigger.get("id") or ""): trigger for trigger in (runner._spec or {}).get("triggers", [])}
    rows: list[dict[str, Any]] = []
    for dvs_id in targets:
        trigger = triggers.get(dvs_id)
        for expect_query in (True, False):
            expected_result = "query_expected" if expect_query else "no_query_expected"
            if trigger is None:
                rows.append(
                    QueryCaseAudit(
                        dvs_id=dvs_id,
                        expected_result=expected_result,
                        trigger_found=False,
                        generation_status="trigger_not_found",
                    ).as_dict()
                )
                continue

            cases = runner.build_query_cases_for_trigger(trigger, expect_query=expect_query)
            case_errors = _case_errors(cases)
            runnable_count = sum(1 for case in cases if getattr(case, "runnable", False))
            status = _query_generation_status(cases, case_errors, runnable_count)
            rows.append(
                QueryCaseAudit(
                    dvs_id=dvs_id,
                    expected_result=expected_result,
                    trigger_found=True,
                    generation_status=status,
                    case_count=len(cases),
                    runnable_count=runnable_count,
                    page_id=str(trigger.get("pageId") or ""),
                    issue_item_ids=_issue_item_ids(trigger),
                    step_methods=sorted(_case_step_methods(cases)),
                    step_pages=sorted(_case_step_pages(cases)),
                    errors=case_errors,
                    notes=_case_notes(cases),
                ).as_dict()
            )
    return rows


def collect_calculation_items(
    runner: Any,
    *,
    target_item_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return extracted CRF fields that have a calculate definition."""

    _require_loaded_runner(runner)
    targets = {str(item_id) for item_id in (target_item_ids or [])}
    rows: list[dict[str, Any]] = []
    for page_id, fields in ((runner._spec or {}).get("pages") or {}).items():
        for field in fields or []:
            calculate = field.get("calculate")
            item_id = str(field.get("itemId") or "")
            if not calculate:
                continue
            if targets and item_id not in targets:
                continue
            rows.append(
                CalculationItemAudit(
                    page_id=str(page_id),
                    item_id=item_id,
                    label=str(field.get("label") or ""),
                    field_type=str(field.get("type") or field.get("fieldType") or ""),
                    calculation_subtype=classify_calculation_subtype(item_id, calculate),
                    calculate_summary=_short_json(calculate),
                ).as_dict()
            )
    return rows


def audit_phase0(
    runner: Any,
    *,
    target_dvs_ids: list[str] | tuple[str, ...] | None = None,
    calculation_item_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "query_case_audit": audit_query_cases(runner, target_dvs_ids=target_dvs_ids),
        "calculation_item_audit": collect_calculation_items(runner, target_item_ids=calculation_item_ids),
    }


def classify_calculation_subtype(item_id: str, calculate: Any) -> str:
    text = json.dumps(calculate, ensure_ascii=False, sort_keys=True).upper()
    item_id = str(item_id or "").upper()
    function_name = ""
    if isinstance(calculate, dict):
        function_name = str(calculate.get("function") or calculate.get("operator") or "").upper()
    if item_id == "AGE" or function_name == "AGE":
        return "age"
    if "SUM" in text:
        return "sum_score"
    if "CHOICE" in text or "RASCH" in text:
        return "rasch_score"
    return "unknown"


def _query_generation_status(cases: list[Any], errors: list[str], runnable_count: int) -> str:
    if not cases:
        return "generation_failed"
    if errors and runnable_count == 0:
        return "generation_failed"
    if errors and runnable_count > 0:
        return "partial"
    return "generated"


def _case_errors(cases: list[Any]) -> list[str]:
    errors: list[str] = []
    for case in cases:
        for error in getattr(case, "errors", []) or []:
            text = str(error)
            if text and text not in errors:
                errors.append(text)
    return errors


def _case_notes(cases: list[Any]) -> list[str]:
    notes: list[str] = []
    for case in cases:
        note = str(getattr(case, "note", "") or "").strip()
        if note and note not in notes:
            notes.append(note)
    return notes


def _case_step_methods(cases: list[Any]) -> set[str]:
    methods: set[str] = set()
    for case in cases:
        for step in getattr(case, "steps", []) or []:
            method = str(getattr(step, "method", "") or "")
            if method:
                methods.add(method)
    return methods


def _case_step_pages(cases: list[Any]) -> set[str]:
    pages: set[str] = set()
    for case in cases:
        for step in getattr(case, "steps", []) or []:
            kwargs = getattr(step, "kwargs", {}) or {}
            page_id = kwargs.get("page_id")
            if page_id:
                pages.add(str(page_id))
            if getattr(step, "method", "") == "go_to_page":
                for arg in getattr(step, "args", []) or []:
                    segment = str(arg or "")
                    if segment:
                        pages.add(segment.split("/")[-1])
    return pages


def _issue_item_ids(trigger: dict[str, Any]) -> list[str]:
    issue = trigger.get("issue") or {}
    item_ids = issue.get("itemId") or []
    if isinstance(item_ids, str):
        return [item_ids]
    out: list[str] = []
    for item in item_ids if isinstance(item_ids, list) else []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            value = str(item.get("itemId") or "")
            if value:
                out.append(value)
    return out


def _short_json(value: Any, *, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _require_loaded_runner(runner: Any) -> None:
    if getattr(runner, "_spec", None) is None:
        raise RuntimeError("Call runner.load_spec() before running Phase 0 audit.")
