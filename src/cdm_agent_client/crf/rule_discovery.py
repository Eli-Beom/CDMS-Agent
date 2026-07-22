from __future__ import annotations

from typing import Any

from .availability_discovery import build_browser_availability_discovery_candidates
from .candidate_prerequisites import enrich_same_page_prerequisites
from .row_matcher import current_input_row_labels, first_step_label, force_include_browser_row, resolve_field_for_label
from .taxonomy import enrich_candidate_taxonomy
from .trigger_matcher import condition_comparisons
from .value_planner import fallback_query_steps, query_mode_step


def build_browser_query_discovery_candidates(runner: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_query_discovery_candidates_for_intent(runner, context, expect_query=True))
    candidates.extend(_query_discovery_candidates_for_intent(runner, context, expect_query=False))
    candidates.extend(_availability_discovery_candidates(runner, context))
    if candidates:
        return candidates

    return [
        {
            "name": "CURRENT_QUERY_CANDIDATE",
            "intent": "query 발생 후보",
            "evidence": "CRF rule 후보 매칭 실패. 현재 inspection row 기본값으로 관찰합니다.",
            "DVS ID": "CURRENT_QUERY_CANDIDATE",
            "discovery_kind": "query",
            "item_id": "",
            "item_label": "",
            "rule_type": "query",
            "rule_source": "Browser",
            "Specification": "Current browser page query discovery candidate",
            "Expected Result": "query_expected",
            "requires_prerequisite": False,
            "condition_steps": steps_to_discovery_dicts(fallback_query_steps(context, expect_query=True)),
            "steps": steps_to_discovery_dicts(fallback_query_steps(context, expect_query=True)),
        },
        {
            "name": "CURRENT_NON_QUERY_CANDIDATE",
            "intent": "query 미발생 후보",
            "evidence": "CRF rule 후보 매칭 실패. 현재 inspection row 기본값으로 관찰합니다.",
            "DVS ID": "CURRENT_NON_QUERY_CANDIDATE",
            "discovery_kind": "query",
            "item_id": "",
            "item_label": "",
            "rule_type": "query",
            "rule_source": "Browser",
            "Specification": "Current browser page non-query discovery candidate",
            "Expected Result": "no_query_expected",
            "requires_prerequisite": False,
            "condition_steps": steps_to_discovery_dicts(fallback_query_steps(context, expect_query=False)),
            "steps": steps_to_discovery_dicts(fallback_query_steps(context, expect_query=False)),
        },
    ]


def _query_discovery_candidates_for_intent(runner: Any, context: dict[str, Any], *, expect_query: bool) -> list[dict[str, Any]]:
    page_id = context.get("page_id") or ""
    row_labels = current_input_row_labels(context)
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
            if label not in row_labels and not force_include_browser_row(label):
                continue
            if label in seen:
                continue
            seen.add(label)
            steps.append(query_mode_step(step, expect_query=expect_query))
        if not steps:
            continue
        evidence = case.note or "CRF query rule 후보"
        if case.errors:
            evidence += " / manual review 필요: " + "; ".join(case.errors[:2])
        expected_result = "query_expected" if expect_query else "no_query_expected"
        trigger = _trigger_for_case(runner, str(case.id))
        issue_ids = _issue_item_ids(trigger or {})
        input_item_labels = [str((step.get("args") or [""])[0]) for step in steps if step.get("args")]
        input_item_ids = [
            getattr(resolve_field_for_label(getattr(runner, "_field_map", {}), page_id, label), "item_id", "") or "unknown"
            for label in input_item_labels
        ]
        issue_id = next((item for item in issue_ids if item), "") or (input_item_ids[0] if input_item_ids else "unknown")
        issue_label = _label_for_item_id(runner, page_id, issue_id) or case.label or first_step_label(steps)
        condition_items = _condition_items_for_trigger(runner, trigger, page_id)
        input_item_id_set = {str(item_id) for item_id in input_item_ids}
        expected_query_message_labels = _unique_labels(
            [
                *[_label_for_item_id(runner, page_id, item_id) or item_id for item_id in issue_ids],
                *[
                    str(item.get("item_label") or "")
                    for item in condition_items
                    if str(item.get("item_id") or "") in input_item_id_set
                ],
            ]
        )
        raw_candidate = {
                "name": case.id,
                "intent": intent,
                "evidence": evidence,
                "DVS ID": case.id,
                "discovery_kind": "query",
                "item_id": issue_id,
                "item_label": issue_label,
                "input_item_ids": input_item_ids,
                "input_item_labels": input_item_labels,
                "expected_query_message_label": issue_label,
                "expected_query_message_labels": expected_query_message_labels,
                "condition_items": condition_items,
                "rule_type": rule_type_for_case(case),
                "rule_source": "CRF+Browser",
                "Specification": specification_for_case(case),
                "Expected Result": expected_result,
                "condition_steps": steps_to_discovery_dicts(steps),
                "steps": steps_to_discovery_dicts(steps),
        }
        raw_candidate = enrich_same_page_prerequisites(
            raw_candidate,
            runner,
            current_page_id=page_id,
        )
        candidates.append(
            enrich_candidate_taxonomy(
                raw_candidate,
                current_page_id=page_id,
                trigger=trigger,
            )
        )
    return candidates


def _availability_discovery_candidates(runner: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in build_browser_availability_discovery_candidates(runner, context):
        target_label = candidate.get("target_label") or ""
        available_steps = candidate.get("steps_to_make_available") or []
        unavailable_steps = candidate.get("steps_to_make_unavailable") or []
        candidates.append(
            enrich_candidate_taxonomy(
                {
                "name": candidate.get("availability_id") or candidate.get("name"),
                "intent": "availability observation",
                "evidence": candidate.get("Specification") or "",
                "DVS ID": candidate.get("target_item_id") or candidate.get("availability_id") or candidate.get("name"),
                "discovery_kind": "availability",
                "page_id": candidate.get("page_id") or "",
                "visit_id": candidate.get("visit_id"),
                "item_id": candidate.get("target_item_id") or "",
                "item_label": target_label,
                "rule_type": "availability",
                "rule_source": "CRF+Browser",
                "Specification": candidate.get("Specification") or "",
                "Test Script": _availability_test_script_text(candidate),
                "Expected Result": "availability_changed",
                "requires_prerequisite": False,
                "steps": [],
                "steps_to_make_unavailable": unavailable_steps,
                "steps_to_make_available": available_steps,
                "control_item_id": candidate.get("control_item_id") or "",
                "control_label": candidate.get("control_label") or "",
                },
                current_page_id=candidate.get("page_id") or "",
            )
        )
    return candidates


def _condition_items_for_trigger(runner: Any, trigger: dict[str, Any] | None, page_id: str) -> list[dict[str, Any]]:
    if not trigger:
        return []
    out: list[dict[str, Any]] = []
    field_map = getattr(runner, "_field_map", {}) or {}
    for comparison in condition_comparisons(trigger):
        item_id = str(comparison.get("item_id") or "")
        item_page_id = str(comparison.get("page_id") or page_id or "")
        field = field_map.get(f"{item_page_id}.{item_id}") or field_map.get(item_id)
        label = str(getattr(field, "label", "") or item_id)
        raw_value = comparison.get("value")
        out.append(
            {
                "item_id": item_id,
                "item_label": label,
                "operator": comparison.get("operator") or "",
                "value": raw_value,
                "ui_value": _option_ui_value(field, raw_value),
                "page_id": item_page_id,
                "visit_id": comparison.get("visit_id") or "",
                "section_id": comparison.get("section_id") or "",
            }
        )
    return out


def _option_ui_value(field: Any, value: Any) -> str:
    if field is None:
        return str(value)
    for option in getattr(field, "options", []) or []:
        if str(option.get("dbVal")) == str(value):
            return str(option.get("uiVal") or value)
    return str(value)


def _unique_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for label in labels:
        text = str(label or "").strip()
        key = "".join(text.split()).lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _availability_test_script_text(candidate: dict[str, Any]) -> str:
    target = candidate.get("target_label") or candidate.get("target_item_id") or "target row"
    unavailable = _steps_text(candidate.get("steps_to_make_unavailable") or [])
    available = _steps_text(candidate.get("steps_to_make_available") or [])
    return (
        f"{unavailable}\n"
        f"inspect {target} unavailable state\n"
        f"{available}\n"
        f"inspect {target} available state"
    ).strip()


def _steps_text(steps: list[dict[str, Any]]) -> str:
    return "\n".join(_step_call_text(step) for step in steps)


def _step_call_text(step: dict[str, Any]) -> str:
    method = step.get("method")
    args = ", ".join(repr(arg) for arg in (step.get("args") or []))
    kwargs = ", ".join(f"{key}={value!r}" for key, value in (step.get("kwargs") or {}).items())
    joined = ", ".join(part for part in (args, kwargs) if part)
    return f"agent.{method}({joined})"


def _trigger_for_case(runner: Any, case_id: str) -> dict[str, Any] | None:
    triggers = {str(trigger.get("id") or ""): trigger for trigger in (getattr(runner, "_spec", {}) or {}).get("triggers", [])}
    if case_id in triggers:
        return triggers[case_id]
    match = __import__("re").match(r"^(D_[A-Z0-9]+_\d+)_\d+$", case_id)
    if match:
        return triggers.get(match.group(1))
    return None


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


def _label_for_item_id(runner: Any, page_id: str, item_id: str) -> str:
    field_map = getattr(runner, "_field_map", {}) or {}
    field = field_map.get(f"{page_id}.{item_id}") or field_map.get(item_id)
    return str(getattr(field, "label", "") or "") if field else ""


def rule_type_for_case(case: Any) -> str:
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


def specification_for_case(case: Any) -> str:
    note = str(getattr(case, "note", "") or "").strip()
    if note:
        return note
    case_id = str(getattr(case, "id", "") or "").strip()
    return f"CRF query trigger candidate: {case_id}" if case_id else "CRF query trigger candidate"


def steps_to_discovery_dicts(steps: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "method": step.method,
            "args": list(step.args),
            "kwargs": dict(step.kwargs),
            "note": step.note,
        }
        for step in steps
    ]
