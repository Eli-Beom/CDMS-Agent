from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd


def load_availability_candidates(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run_availability_discovery_loop(
    agent: Any,
    candidates: list[dict[str, Any]],
    *,
    page_id: str,
    visit_id: str | None,
    step_delay_seconds: float = 0.0,
    save_after_each: bool = False,
) -> pd.DataFrame:
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        print("\n=== Availability candidate ===")
        print("availability_id:", candidate.get("availability_id") or candidate.get("name"))
        print("target:", candidate.get("target_label"), "/", candidate.get("target_item_id"))
        print("control:", candidate.get("control_label"), "/", candidate.get("control_item_id"))
        print("Specification:", candidate.get("Specification"))
        input(f"Run availability candidate {candidate.get('name')}? Press Enter to continue...")

        before = _row_state(agent.inspect(), candidate.get("target_label"))
        unavailable_error = _run_steps(agent, candidate.get("steps_to_make_unavailable") or [], step_delay_seconds)
        input("Review unavailable state, then press Enter to inspect...")
        after_unavailable = _row_state(agent.inspect(), candidate.get("target_label"))

        available_error = _run_steps(agent, candidate.get("steps_to_make_available") or [], step_delay_seconds)
        input("Review available state, then press Enter to inspect...")
        after_available_snap = agent.inspect()
        after_available = _row_state(after_available_snap, candidate.get("target_label"))

        save_error = None
        if save_after_each:
            try:
                agent.click_save(page_id=page_id, visit_id=visit_id)
            except Exception as exc:
                save_error = str(exc)

        observation_result = _observation_result(
            before,
            after_unavailable,
            after_available,
            unavailable_error or available_error or save_error,
        )
        results.append(
            {
                "availability_id": candidate.get("availability_id") or candidate.get("name"),
                "page_id": page_id,
                "page_label": after_available_snap.page_label,
                "visit_id": visit_id,
                "target_item_id": candidate.get("target_item_id") or "",
                "target_label": candidate.get("target_label") or "",
                "control_item_id": candidate.get("control_item_id") or "",
                "control_label": candidate.get("control_label") or "",
                "Specification": candidate.get("Specification") or "",
                "before_availability": before.get("row_availability"),
                "before_disability": before.get("row_disability"),
                "before_editable": before.get("editable"),
                "unavailable_step": _steps_text(candidate.get("steps_to_make_unavailable") or []),
                "after_unavailable_availability": after_unavailable.get("row_availability"),
                "after_unavailable_disability": after_unavailable.get("row_disability"),
                "after_unavailable_editable": after_unavailable.get("editable"),
                "available_step": _steps_text(candidate.get("steps_to_make_available") or []),
                "after_available_availability": after_available.get("row_availability"),
                "after_available_disability": after_available.get("row_disability"),
                "after_available_editable": after_available.get("editable"),
                "observation_result": observation_result,
                "review_decision": "",
            }
        )
        print("before:", before)
        print("after_unavailable:", after_unavailable)
        print("after_available:", after_available)
        print("observation_result:", observation_result)
        input("Review this availability result, then press Enter for next candidate...")
    return pd.DataFrame(results)


def display_availability_discovery_tables(availability_discovery_result: pd.DataFrame) -> None:
    if not availability_discovery_result.empty:
        changed_as_expected = availability_discovery_result[
            availability_discovery_result["observation_result"] == "availability_changed_as_expected"
        ]
        not_changed_or_manual_review = availability_discovery_result[
            availability_discovery_result["observation_result"].isin(
                ["availability_not_changed", "target_row_not_found", "control_step_blocked", "manual_review"]
            )
        ]
        review_queue = availability_discovery_result[
            availability_discovery_result["review_decision"].astype(str).str.len() == 0
        ]
    else:
        changed_as_expected = availability_discovery_result
        not_changed_or_manual_review = availability_discovery_result
        review_queue = availability_discovery_result
    print("전체 availability_discovery_result")
    display(availability_discovery_result)
    print("changed_as_expected")
    display(changed_as_expected)
    print("not_changed_or_manual_review")
    display(not_changed_or_manual_review)
    print("review_queue")
    display(review_queue)


def export_availability_discovery_result(result: pd.DataFrame, path: str | Path) -> None:
    if result.empty:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print("exported:", output_path)


def _run_steps(agent: Any, steps: list[dict[str, Any]], delay_seconds: float) -> str | None:
    for step in steps:
        try:
            method = step.get("method")
            args = step.get("args") or []
            kwargs = step.get("kwargs") or {}
            getattr(agent, method)(*args, **kwargs)
            if delay_seconds:
                time.sleep(delay_seconds)
        except Exception as exc:
            print("step error:", step.get("method"), step.get("args"), exc)
            return str(exc)
    return None


def _row_state(snapshot: Any, target_label: str | None) -> dict[str, Any]:
    target_label = str(target_label or "").strip()
    if not target_label:
        return {}
    for row in getattr(snapshot, "structured_rows", []) or []:
        if str(row.get("rowLabel") or "").strip() == target_label:
            return {
                "rowLabel": row.get("rowLabel"),
                "row_availability": row.get("row_availability"),
                "row_disability": row.get("row_disability"),
                "editable": row.get("editable"),
                "visible": row.get("visible"),
            }
    return {}


def _observation_result(before: dict[str, Any], after_unavailable: dict[str, Any], after_available: dict[str, Any], error: str | None) -> str:
    if error:
        return "control_step_blocked"
    if not before or not after_unavailable or not after_available:
        return "target_row_not_found"
    unavailable = after_unavailable.get("row_availability")
    available = after_available.get("row_availability")
    if unavailable == "unavailable" and available == "available":
        return "availability_changed_as_expected"
    if unavailable != available:
        return "availability_changed_as_expected"
    return "availability_not_changed"


def _steps_text(steps: list[dict[str, Any]]) -> str:
    return "\n".join(_step_call_text(step) for step in steps)


def _step_call_text(step: dict[str, Any]) -> str:
    method = step.get("method")
    args = ", ".join(repr(arg) for arg in (step.get("args") or []))
    kwargs = ", ".join(f"{key}={value!r}" for key, value in (step.get("kwargs") or {}).items())
    joined = ", ".join(part for part in (args, kwargs) if part)
    return f"agent.{method}({joined})"
