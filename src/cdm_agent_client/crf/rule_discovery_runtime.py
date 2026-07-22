from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


def load_candidates(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run_rule_discovery_loop(
    agent: Any,
    candidates: list[dict[str, Any]],
    *,
    page_id: str,
    visit_id: str | None,
    client_id: str | None = None,
    step_delay_seconds: float = 0.0,
    post_save_delay_seconds: float = 1.0,
    stable_inspect_attempts: int = 5,
    stable_inspect_delay_seconds: float = 0.4,
    query_event_timeout_ms: int = 3000,
    execute_setup_steps: bool = False,
    execute_prerequisite_steps: bool | None = None,
    query_observation_mode: str = "per_candidate",
    clear_target_query_before_candidate: bool = False,
    pause_between_candidates: bool = True,
) -> pd.DataFrame:
    results: list[dict[str, Any]] = []
    query_observation_mode = str(query_observation_mode or "per_candidate").strip().lower()
    if query_observation_mode not in {"per_candidate", "sweep"}:
        raise ValueError("query_observation_mode must be 'per_candidate' or 'sweep'")
    warmup_snap = _stable_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    if _is_unsupported_page_label(getattr(warmup_snap, "page_label", "")):
        print("warning: initial inspect did not capture a valid CRF page label.")
    elif getattr(warmup_snap, "page_label", None):
        print("active page:", getattr(warmup_snap, "page_label", ""))
    initial_query_rows = observed_query_rows_from_snapshot(warmup_snap)
    for candidate in candidates:
        print("\n=== Discovery candidate ===")
        print("DVS ID:", candidate.get("DVS ID") or candidate.get("name"))
        print("DVS Type:", candidate.get("DVS Type") or candidate.get("rule_type"))
        print("Query Category:", candidate.get("Query Category") or candidate.get("query_category", ""))
        print("Condition Type:", candidate.get("Condition Type") or candidate.get("condition_type", candidate.get("prerequisite_shape", "")))
        print("Expected Result:", candidate.get("Expected Result"))
        print("Specification:", candidate.get("Specification"))
        if pause_between_candidates:
            input(f"Run candidate {candidate.get('name')}? Press Enter to continue...")

        if candidate.get("rule_type") == "availability":
            results.append(
                _run_availability_candidate(
                    agent,
                    candidate,
                    page_id=page_id,
                    visit_id=visit_id,
                    client_id=client_id,
                    step_delay_seconds=step_delay_seconds,
                    stable_inspect_attempts=stable_inspect_attempts,
                    stable_inspect_delay_seconds=stable_inspect_delay_seconds,
                    pause=pause_between_candidates,
                    post_save_delay_seconds=post_save_delay_seconds,
                )
            )
            if pause_between_candidates:
                input("Review this discovery result, then press Enter for next candidate...")
            continue

        step_results: list[dict[str, Any]] = []
        before_snap = _stable_inspect(
            agent,
            page_id=page_id,
            client_id=client_id,
            attempts=stable_inspect_attempts,
            delay_seconds=stable_inspect_delay_seconds,
        )
        clear_result = {"attempted": False, "failed": False, "before": [], "after": [], "cleared": []}
        if clear_target_query_before_candidate:
            clear_result = _clear_target_query_before_candidate(
                agent,
                candidate,
                before_snap=before_snap,
                page_id=page_id,
                visit_id=visit_id,
                client_id=client_id,
                stable_inspect_attempts=stable_inspect_attempts,
                stable_inspect_delay_seconds=stable_inspect_delay_seconds,
            )
            before_snap = clear_result.get("snapshot") or before_snap
            if clear_result.get("failed"):
                labels = _candidate_query_labels(candidate)
                before_query_rows = list(clear_result.get("before") or [])
                after_query_rows = list(clear_result.get("after") or [])
                target_query_rows = _target_query_rows(after_query_rows, candidate)
                results.append(
                    {
                        "DVS ID": candidate.get("DVS ID") or candidate.get("name"),
                        "page_id": page_id,
                        "page_label": getattr(before_snap, "page_label", ""),
                        "visit_id": visit_id,
                        "item_id": candidate.get("item_id") or "",
                        "item_label": candidate.get("item_label") or "",
                        "DVS Type": candidate.get("DVS Type") or candidate.get("rule_type") or "unknown",
                        "Query Category": candidate.get("Query Category") or candidate.get("query_category") or "",
                        "Condition Type": candidate.get("Condition Type") or candidate.get("condition_type") or candidate.get("prerequisite_shape") or "none",
                        "rule_type": candidate.get("rule_type") or "unknown",
                        "query_category": candidate.get("query_category") or "",
                        "condition_type": candidate.get("condition_type") or candidate.get("prerequisite_shape") or "none",
                        "prerequisite_shape": candidate.get("prerequisite_shape") or candidate.get("condition_type") or "none",
                        "rule_source": candidate.get("rule_source") or "Unknown",
                        "Specification": candidate.get("Specification") or "",
                        "Test Script": test_script_text(candidate),
                        "requires_prerequisite": _candidate_requires_prerequisite(candidate),
                        "prerequisite_steps_count": len(_candidate_prerequisite_steps(candidate)),
                        "prerequisite_item_ids": ",".join(candidate.get("prerequisite_item_ids") or []),
                        "Expected Result": candidate.get("Expected Result") or "manual_review",
                        "observed_query_count": len(target_query_rows),
                        "observed_query_messages": target_query_rows,
                        "all_observed_query_messages": after_query_rows,
                        "before_query_messages": before_query_rows,
                        "after_query_messages": after_query_rows,
                        "query_event_outcome": "",
                        "query_event_elapsed_ms": "",
                        "target_observed_query_count": len(target_query_rows),
                        "target_observed_query_messages": target_query_rows,
                        "query_clear_attempted": True,
                        "query_clear_failed": True,
                        "query_clear_labels": labels,
                        "Result": "REVIEW",
                        "discovery_category": "query_clear_failed",
                        "review_decision": "query_clear_failed",
                    }
                )
                print("query clear failed:", target_query_rows)
                if pause_between_candidates:
                    input("Review this discovery result, then press Enter for next candidate...")
                continue
        before_query_rows = observed_query_rows_from_snapshot(before_snap)
        prerequisite_steps = _candidate_prerequisite_steps(candidate)
        should_execute_prerequisites = execute_setup_steps if execute_prerequisite_steps is None else execute_prerequisite_steps
        if should_execute_prerequisites:
            for step in prerequisite_steps:
                try:
                    result = _run_discovery_step(agent, step, client_id=client_id)
                    step_results.append(
                        {
                            "method": step.get("method"),
                            "args": step.get("args"),
                            "ok": True,
                            "outcome": _step_result_summary(result),
                            "phase": "prerequisite",
                        }
                    )
                    if step_delay_seconds:
                        time.sleep(step_delay_seconds)
                except Exception as exc:
                    step_results.append(
                        {
                            "method": step.get("method"),
                            "args": step.get("args"),
                            "ok": False,
                            "error": str(exc),
                            "phase": "prerequisite",
                        }
                    )
                    print("prerequisite step error:", step.get("method"), step.get("args"), exc)
        elif prerequisite_steps:
            print("prerequisite_steps available but not executed in this loop. Review/run prerequisite separately.")

        for step in _candidate_execution_steps(candidate):
            try:
                result = _run_discovery_step(agent, step, client_id=client_id)
                step_results.append(
                    {
                        "method": step.get("method"),
                        "args": step.get("args"),
                        "ok": True,
                        "outcome": _step_result_summary(result),
                    }
                )
                if step_delay_seconds:
                    time.sleep(step_delay_seconds)
            except Exception as exc:
                step_results.append(
                    {
                        "method": step.get("method"),
                        "args": step.get("args"),
                        "ok": False,
                        "error": str(exc),
                    }
                )
                print("step error:", step.get("method"), step.get("args"), exc)

        if pause_between_candidates:
            input("Press Enter to Save and observe query...")
        save_error = None
        try:
            if client_id:
                agent.click_save(page_id=page_id, visit_id=visit_id, client_id=client_id)
            else:
                agent.click_save(page_id=page_id, visit_id=visit_id)
        except Exception as exc:
            save_error = str(exc)
            print("Save error:", exc)

        wait_query_result: dict[str, Any] | None = None
        wait_query_rows: list[str] = []
        target_labels = _candidate_query_labels(candidate)
        if hasattr(agent, "wait_query"):
            try:
                wait_query_result = agent.wait_query(
                    target_labels,
                    timeout_ms=query_event_timeout_ms,
                    client_id=client_id,
                )
                wait_query_rows = [str(row) for row in (wait_query_result.get("queryRows") or [])]
            except Exception as exc:
                print("wait_query fallback:", exc)
        else:
            time.sleep(post_save_delay_seconds)

        if post_save_delay_seconds:
            time.sleep(post_save_delay_seconds)
        snap = _settled_inspect(
            agent,
            page_id=page_id,
            client_id=client_id,
            attempts=stable_inspect_attempts,
            delay_seconds=stable_inspect_delay_seconds,
        )
        after_query_rows = observed_query_rows_from_snapshot(snap)
        observed_query_rows = _observed_query_rows_for_mode(
            after_rows=after_query_rows,
            before_rows=before_query_rows,
            initial_rows=initial_query_rows,
            wait_query_rows=wait_query_rows,
            query_observation_mode=query_observation_mode,
        )
        before_target_query_rows = _target_query_rows(before_query_rows, candidate)
        after_target_query_rows = _target_query_rows(after_query_rows, candidate)
        observed_target_query_rows = _target_query_rows(observed_query_rows, candidate)
        target_query_rows = _unique_query_rows([*before_target_query_rows, *after_target_query_rows, *observed_target_query_rows])
        query_count = len(target_query_rows)
        observation_value = _query_observation_value(query_count, step_results, save_error)
        if query_observation_mode == "sweep":
            result_value = ""
            discovery_category = _sweep_discovery_category(query_count, observed_query_rows)
        else:
            result_value, discovery_category = _query_result_and_category(
                candidate.get("Expected Result"),
                before_count=len(before_target_query_rows),
                after_count=len(after_target_query_rows),
                observed_count=len(observed_target_query_rows),
                step_results=step_results,
                save_error=save_error,
            )

        results.append(
            {
                "DVS ID": candidate.get("DVS ID") or candidate.get("name"),
                "page_id": page_id,
                "page_label": snap.page_label,
                "visit_id": visit_id,
                "item_id": candidate.get("item_id") or "",
                "item_label": candidate.get("item_label") or "",
                "DVS Type": candidate.get("DVS Type") or candidate.get("rule_type") or "unknown",
                "Query Category": candidate.get("Query Category") or candidate.get("query_category") or "",
                "Condition Type": candidate.get("Condition Type") or candidate.get("condition_type") or candidate.get("prerequisite_shape") or "none",
                "rule_type": candidate.get("rule_type") or "unknown",
                "query_category": candidate.get("query_category") or "",
                "condition_type": candidate.get("condition_type") or candidate.get("prerequisite_shape") or "none",
                "prerequisite_shape": candidate.get("prerequisite_shape") or candidate.get("condition_type") or "none",
                "rule_source": candidate.get("rule_source") or "Unknown",
                "Specification": candidate.get("Specification") or "",
                "Test Script": test_script_text(candidate),
                "requires_prerequisite": _candidate_requires_prerequisite(candidate),
                "prerequisite_steps_count": len(prerequisite_steps),
                "prerequisite_item_ids": ",".join(candidate.get("prerequisite_item_ids") or []),
                "Expected Result": candidate.get("Expected Result") or "manual_review",
                "observed_query_count": query_count,
                "observed_query_messages": target_query_rows,
                "all_observed_query_messages": observed_query_rows,
                "before_query_messages": before_query_rows,
                "after_query_messages": after_query_rows,
                "query_event_outcome": (wait_query_result or {}).get("outcome", ""),
                "query_event_elapsed_ms": (wait_query_result or {}).get("elapsedMs", ""),
                "target_observed_query_count": len(target_query_rows),
                "target_observed_query_messages": target_query_rows,
                "before_target_query_count": len(before_target_query_rows),
                "before_target_query_messages": before_target_query_rows,
                "after_target_query_count": len(after_target_query_rows),
                "after_target_query_messages": after_target_query_rows,
                "query_clear_attempted": bool(clear_result.get("attempted")),
                "query_clear_failed": bool(clear_result.get("failed")),
                "query_clear_labels": clear_result.get("labels") or [],
                "Result": result_value,
                "discovery_category": discovery_category,
                "review_decision": "",
            }
        )
        print("observed_query_count:", query_count)
        print("target_observed_query_count:", len(target_query_rows))
        print("actual_observation:", observation_value)
        print("Result:", result_value)
        print("discovery_category:", discovery_category)
        print("before_query_messages:", before_query_rows)
        print("after_query_messages:", after_query_rows)
        print("all_observed_query_messages:", observed_query_rows)
        print("observed_query_messages:", target_query_rows)
        print("target_observed_query_messages:", target_query_rows)
        if pause_between_candidates:
            input("Review this discovery result, then press Enter for next candidate...")
    return pd.DataFrame(results)


def _run_availability_candidate(
    agent: Any,
    candidate: dict[str, Any],
    *,
    page_id: str,
    visit_id: str | None,
    client_id: str | None,
    step_delay_seconds: float,
    stable_inspect_attempts: int,
    stable_inspect_delay_seconds: float,
    pause: bool = True,
    post_save_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    if (candidate.get("Availability Category") or candidate.get("availability_category")) == "table_availability":
        return _availability_skipped_result(
            candidate,
            page_id=page_id,
            visit_id=visit_id,
            reason="table_availability_not_implemented",
        )

    # Availability is a client-side UI state. Do not save here; saving can
    # trigger the modify-reason popup and mixes query/save validation into
    # availability validation.
    before_snap = _stable_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    before_labels = _row_label_counter(before_snap)

    available_error, available_skipped = _run_availability_steps(
        agent,
        candidate.get("steps_to_make_available") or [],
        step_delay_seconds,
        client_id=client_id,
    )
    if pause:
        input("Review available state, then press Enter to inspect...")
    after_available_snap = _settled_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    after_available_labels = _row_label_counter(after_available_snap)
    available_probe = _run_availability_probe(agent, candidate, step_delay_seconds, client_id=client_id)

    unavailable_error, unavailable_skipped = _run_availability_steps(
        agent,
        candidate.get("steps_to_make_unavailable") or [],
        step_delay_seconds,
        client_id=client_id,
    )
    if pause:
        input("Review unavailable state, then press Enter to inspect...")
    after_unavailable_snap = _settled_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    after_unavailable_labels = _row_label_counter(after_unavailable_snap)
    unavailable_probe = _run_availability_probe(agent, candidate, step_delay_seconds, client_id=client_id)

    restored_error, restored_skipped = _run_availability_steps(
        agent,
        candidate.get("steps_to_make_available") or [],
        step_delay_seconds,
        client_id=client_id,
    )
    if pause:
        input("Review restored available state, then press Enter to inspect...")
    after_restored_snap = _settled_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    after_restored_labels = _row_label_counter(after_restored_snap)
    restored_probe = _run_availability_probe(agent, candidate, step_delay_seconds, client_id=client_id)

    # Counter subtraction preserves duplicate labels such as the two DM "??" rows.
    disappeared_counter = before_labels - after_unavailable_labels
    appeared_counter = after_restored_labels - after_unavailable_labels
    disappeared = sorted(disappeared_counter.elements())
    appeared = sorted(appeared_counter.elements())

    target_label = str(candidate.get("item_label") or "").strip()
    target_in_disappeared = bool(target_label and disappeared_counter.get(target_label, 0) > 0)
    target_in_appeared = bool(target_label and appeared_counter.get(target_label, 0) > 0)

    condition_error = available_error or unavailable_error or restored_error
    condition_skipped = available_skipped or unavailable_skipped or restored_skipped

    if _has_availability_probe(candidate):
        observation_value = _availability_input_observation_value(
            available_probe,
            unavailable_probe,
            restored_probe,
            condition_error,
            condition_skipped,
        )
    elif condition_error:
        observation_value = "blocked"
    elif condition_skipped:
        observation_value = "skipped"
    elif target_in_disappeared or target_in_appeared:
        observation_value = "availability_changed"
    elif disappeared or appeared:
        observation_value = "availability_changed_label_mismatch"
    else:
        observation_value = "availability_not_changed"

    result_value = _result_value(candidate.get("Expected Result"), observation_value)

    print("before_row_count:", sum(before_labels.values()))
    print("disappeared_labels:", disappeared)
    print("appeared_labels:", appeared)
    print("target_label:", target_label)
    print("target_in_disappeared:", target_in_disappeared)
    print("target_in_appeared:", target_in_appeared)
    print("availability_step_error:", condition_error or "")
    print("observed_input_capability:", _availability_input_capability_state(available_probe, unavailable_probe, restored_probe))
    print("actual_observation:", observation_value)
    print("Result:", result_value)

    return {
        "DVS ID": candidate.get("DVS ID") or candidate.get("name"),
        "page_id": page_id,
        "page_label": after_restored_snap.page_label,
        "visit_id": visit_id,
        "item_id": candidate.get("item_id") or "",
        "item_label": target_label,
        "DVS Type": "availability",
        "Availability Category": candidate.get("Availability Category") or candidate.get("availability_category") or "field_availability",
        "Availability Condition Type": candidate.get("Availability Condition Type") or candidate.get("availability_condition_type") or "single",
        "Availability Input Type": candidate.get("Availability Input Type") or candidate.get("availability_input_type") or "",
        "Query Category": "",
        "Condition Type": "none",
        "rule_type": "availability",
        "availability_category": candidate.get("availability_category") or candidate.get("Availability Category") or "field_availability",
        "availability_condition_type": candidate.get("availability_condition_type") or candidate.get("Availability Condition Type") or "single",
        "availability_input_type": candidate.get("availability_input_type") or candidate.get("Availability Input Type") or "",
        "query_category": "",
        "condition_type": "none",
        "prerequisite_shape": "none",
        "rule_source": candidate.get("rule_source") or "Unknown",
        "Specification": candidate.get("Specification") or "",
        "Test Script": test_script_text(candidate),
        "Expected Result": candidate.get("Expected Result") or "availability_changed",
        "observed_query_count": "",
        "observed_query_messages": "",
        "target_observed_query_count": "",
        "target_observed_query_messages": "",
        "before_availability": "in_rows" if before_labels.get(target_label, 0) > 0 else ("not_in_rows" if target_label else ""),
        "after_unavailable_availability": "not_in_rows" if after_unavailable_labels.get(target_label, 0) == 0 else "in_rows",
        "after_available_availability": "in_rows" if after_restored_labels.get(target_label, 0) > 0 else "not_in_rows",
        "after_initial_available_availability": "in_rows" if after_available_labels.get(target_label, 0) > 0 else "not_in_rows",
        "disappeared_labels": ", ".join(disappeared),
        "appeared_labels": ", ".join(appeared),
        "target_in_disappeared": target_in_disappeared,
        "target_in_appeared": target_in_appeared,
        "availability_step_error": condition_error or "",
        "observed_input_capability": _availability_input_capability_state(available_probe, unavailable_probe, restored_probe),
        "available_option_capabilities": available_probe.get("option_capabilities", ""),
        "unavailable_option_capabilities": unavailable_probe.get("option_capabilities", ""),
        "restored_option_capabilities": restored_probe.get("option_capabilities", ""),
        "available_probe_outcome": available_probe.get("outcome", ""),
        "unavailable_probe_outcome": unavailable_probe.get("outcome", ""),
        "restored_probe_outcome": restored_probe.get("outcome", ""),
        "observed_availability_state": f"disappeared={disappeared} / appeared={appeared}",
        "availability_target_state": f"disappeared={disappeared} / appeared={appeared}",
        "Result": result_value,
        "discovery_category": _availability_discovery_category(observation_value),
        "review_decision": "",
    }


def _availability_skipped_result(
    candidate: dict[str, Any],
    *,
    page_id: str,
    visit_id: str | None,
    reason: str,
) -> dict[str, Any]:
    expected = candidate.get("Expected Result") or "availability_changed"
    observation_value = "skipped"
    return {
        "DVS ID": candidate.get("DVS ID") or candidate.get("name"),
        "page_id": page_id,
        "page_label": "",
        "visit_id": visit_id,
        "item_id": candidate.get("item_id") or "",
        "item_label": candidate.get("item_label") or "",
        "DVS Type": "availability",
        "Availability Category": candidate.get("Availability Category") or candidate.get("availability_category") or "table_availability",
        "Availability Condition Type": candidate.get("Availability Condition Type") or candidate.get("availability_condition_type") or "single",
        "Availability Input Type": candidate.get("Availability Input Type") or candidate.get("availability_input_type") or "table_input",
        "Query Category": "",
        "Condition Type": "none",
        "rule_type": "availability",
        "availability_category": candidate.get("availability_category") or candidate.get("Availability Category") or "table_availability",
        "availability_condition_type": candidate.get("availability_condition_type") or candidate.get("Availability Condition Type") or "single",
        "availability_input_type": candidate.get("availability_input_type") or candidate.get("Availability Input Type") or "table_input",
        "query_category": "",
        "condition_type": "none",
        "prerequisite_shape": "none",
        "rule_source": candidate.get("rule_source") or "Unknown",
        "Specification": candidate.get("Specification") or "",
        "Test Script": test_script_text(candidate),
        "Expected Result": expected,
        "observed_query_count": "",
        "observed_query_messages": "",
        "target_observed_query_count": "",
        "target_observed_query_messages": "",
        "before_availability": "",
        "after_unavailable_availability": "",
        "after_available_availability": "",
        "after_initial_available_availability": "",
        "disappeared_labels": "",
        "appeared_labels": "",
        "target_in_disappeared": False,
        "target_in_appeared": False,
        "availability_step_error": reason,
        "observed_input_capability": "",
        "observed_availability_state": reason,
        "availability_target_state": reason,
        "Result": _result_value(expected, observation_value),
        "discovery_category": _availability_discovery_category(observation_value),
        "review_decision": "",
    }

def _availability_save(
    agent: Any,
    *,
    page_id: str,
    visit_id: str | None,
    client_id: str | None,
    delay_seconds: float = 1.0,
) -> str | None:
    """Click save and return an error string on failure, None on success."""
    try:
        if client_id:
            agent.click_save(page_id=page_id, visit_id=visit_id, client_id=client_id)
        else:
            agent.click_save(page_id=page_id, visit_id=visit_id)
    except Exception as exc:
        print("availability save error:", exc)
        return str(exc)
    if delay_seconds:
        time.sleep(delay_seconds)
    return None


def _row_label_counter(snapshot: Any) -> Counter[str]:
    """Return rowLabel counts from structured_rows, preserving duplicate labels."""
    rows = getattr(snapshot, "structured_rows", None) or []
    return Counter(
        str(row.get("rowLabel") or "").strip()
        for row in rows
        if row.get("rowLabel")
    )

def _run_availability_steps(
    agent: Any,
    steps: list[dict[str, Any]],
    delay_seconds: float,
    *,
    client_id: str | None,
) -> tuple[str | None, bool]:
    skipped = False
    for step in steps:
        try:
            result = _run_discovery_step(agent, step, client_id=client_id)
            outcome = _step_result_summary(result)
            skipped = skipped or outcome == "skipped"
            if outcome and outcome not in {"passed", "ok", "success", "succeeded", "skipped"}:
                return f"step outcome {outcome}: {step.get('method')} {step.get('args')}", skipped
            if delay_seconds:
                time.sleep(delay_seconds)
        except Exception as exc:
            print("step error:", step.get("method"), step.get("args"), exc)
            return str(exc), skipped
    return None, skipped


def _run_availability_probe(
    agent: Any,
    candidate: dict[str, Any],
    delay_seconds: float,
    *,
    client_id: str | None,
) -> dict[str, str]:
    steps = _candidate_availability_probe_steps(candidate)
    if len(steps) > 1:
        observations = [
            _run_single_availability_probe(agent, candidate, step, delay_seconds, client_id=client_id)
            for step in steps
        ]
        capabilities = [item.get("capability") for item in observations]
        if all(capability == "capable" for capability in capabilities):
            aggregate = "capable"
        elif all(capability == "blocked" for capability in capabilities):
            aggregate = "blocked"
        elif all(capability == "not_tested" for capability in capabilities):
            aggregate = "not_tested"
        else:
            aggregate = "partial"
        return {
            "capability": aggregate,
            "outcome": ",".join(str(item.get("outcome") or "") for item in observations),
            "error": "; ".join(str(item.get("error") or "") for item in observations if item.get("error")),
            "option_capabilities": ", ".join(
                f"{item.get('option_label', '')}:{item.get('capability', '')}" for item in observations
            ),
        }
    if not steps:
        return {"capability": "not_tested", "outcome": "no_probe", "error": ""}
    return _run_single_availability_probe(agent, candidate, steps[0], delay_seconds, client_id=client_id)


def _run_single_availability_probe(
    agent: Any,
    candidate: dict[str, Any],
    step: dict[str, Any],
    delay_seconds: float,
    *,
    client_id: str | None,
) -> dict[str, str]:
    if not isinstance(step, dict):
        return {"capability": "not_tested", "outcome": "no_probe", "error": ""}
    try:
        executable_step = _availability_probe_executable_step(step, candidate)
        result = _run_discovery_step(agent, executable_step, client_id=client_id)
        outcome = _step_result_summary(result) or ""
        if delay_seconds:
            time.sleep(delay_seconds)
        record = _availability_probe_record(result, executable_step)
        if record and step.get("method") == "probe_radio":
            checked = record.get("checked")
            row_availability = str(record.get("row_availability") or "")
            row_disability = str(record.get("row_disability") or "")
            if row_availability in {"unavailable", "not_found"} or row_disability == "locked":
                return {
                    "capability": "blocked",
                    "outcome": str(record.get("outcome") or outcome or "unknown"),
                    "error": "",
                    "checked": str(checked),
                    "option_label": str(record.get("optionLabel") or _probe_option_label(step)),
                }
            if isinstance(checked, bool):
                return {
                    "capability": "capable" if checked else "blocked",
                    "outcome": str(record.get("outcome") or outcome or "unknown"),
                    "error": "",
                    "checked": str(checked),
                    "option_label": str(record.get("optionLabel") or _probe_option_label(step)),
                }
        if outcome in {"passed", "ok", "success", "succeeded"}:
            return {"capability": "capable", "outcome": outcome, "error": "", "option_label": _probe_option_label(step)}
        return {"capability": "blocked", "outcome": outcome or "unknown", "error": "", "option_label": _probe_option_label(step)}
    except Exception as exc:
        print("probe error:", step.get("method"), step.get("args"), exc)
        return {"capability": "blocked", "outcome": "exception", "error": str(exc), "option_label": _probe_option_label(step)}


def _candidate_availability_probe_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    steps = candidate.get("availability_probe_steps")
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    step = candidate.get("availability_probe_step")
    return [step] if isinstance(step, dict) else []


def _probe_option_label(step: dict[str, Any]) -> str:
    args = step.get("args") or []
    return str(args[1]) if len(args) > 1 else ""


def _availability_probe_executable_step(step: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    executable = dict(step)
    if step.get("method") == "probe_radio":
        executable["method"] = "select_radio"
    kwargs = dict(executable.get("kwargs") or {})
    if "anchor_label" not in kwargs and candidate.get("control_label"):
        kwargs["anchor_label"] = candidate.get("control_label")
    if "row_label_occurrence" not in kwargs and candidate.get("row_label_occurrence"):
        kwargs["row_label_occurrence"] = candidate.get("row_label_occurrence")
    if executable.get("method") == "select_radio":
        kwargs["probe_only"] = True
    executable["kwargs"] = kwargs
    return executable


def _has_availability_probe(candidate: dict[str, Any]) -> bool:
    return bool(_candidate_availability_probe_steps(candidate))


def _availability_probe_record(result: Any, step: dict[str, Any]) -> dict[str, Any] | None:
    raw = getattr(result, "raw", None)
    if not isinstance(raw, dict):
        return None
    inputs = raw.get("inputs")
    if not isinstance(inputs, list):
        return None
    expected_action = _probe_action_name(step.get("method"))
    expected_label = ""
    args = step.get("args") or []
    if args:
        expected_label = str(args[0])
    for item in reversed(inputs):
        if not isinstance(item, dict):
            continue
        if expected_action and item.get("action") != expected_action:
            continue
        if expected_label and str(item.get("rowLabel") or "") != expected_label:
            continue
        return item
    return inputs[-1] if inputs else None


def _probe_action_name(method: Any) -> str:
    if method in {"probe_radio", "select_radio"}:
        return "selectRadio"
    return str(method or "")


def _row_state(snapshot: Any, candidate_or_label: Any) -> dict[str, Any]:
    if isinstance(candidate_or_label, dict):
        target_label = str(candidate_or_label.get("item_label") or "").strip()
        target_item_id = str(candidate_or_label.get("item_id") or "").strip()
    else:
        target_label = str(candidate_or_label or "").strip()
        target_item_id = ""
    if not target_label:
        return {}
    matched: list[dict[str, Any]] = []
    for row in getattr(snapshot, "structured_rows", []) or []:
        if str(row.get("rowLabel") or "").strip() == target_label:
            matched.append(
                {
                "rowLabel": row.get("rowLabel"),
                "item_id": target_item_id,
                "row_availability": row.get("row_availability"),
                "row_disability": row.get("row_disability"),
                "editable": row.get("editable"),
                "visible": row.get("visible"),
                "match_quality": "label_exact",
            }
            )
    if not matched:
        return {
            "rowLabel": target_label,
            "item_id": target_item_id,
            "row_availability": "not_found",
            "row_disability": "unknown",
            "editable": False,
            "visible": False,
            "match_quality": "not_found",
        }
    if len(matched) > 1:
        out = dict(matched[0])
        out["match_quality"] = "ambiguous_label"
        out["matched_rows_count"] = len(matched)
        return out
    return matched[0]


def _availability_observation_value(
    before: dict[str, Any],
    after_unavailable: dict[str, Any],
    after_available: dict[str, Any],
    error: str | None,
    skipped: bool,
) -> str:
    if error:
        return "blocked"
    if skipped:
        return "skipped"
    if not before or not after_unavailable or not after_available:
        return "target_row_not_found"
    unavailable = after_unavailable.get("row_availability")
    available = after_available.get("row_availability")
    if unavailable == "not_found" and available == "available":
        return "availability_changed"
    if unavailable == "unavailable" and available == "available":
        return "availability_changed"
    if unavailable != available:
        return "availability_changed"
    return "availability_not_changed"


def _availability_target_state(before: dict[str, Any], after_unavailable: dict[str, Any], after_available: dict[str, Any]) -> str:
    return " -> ".join(
        str(item.get("row_availability") or "")
        for item in (before, after_unavailable, after_available)
    )


def _availability_input_capability_state(available_probe: dict[str, str], unavailable_probe: dict[str, str], restored_probe: dict[str, str]) -> str:
    return " -> ".join(
        str(item.get("capability") or "")
        for item in (available_probe, unavailable_probe, restored_probe)
    )


def _availability_input_observation_value(
    available_probe: dict[str, str],
    unavailable_probe: dict[str, str],
    restored_probe: dict[str, str],
    error: str | None,
    skipped: bool,
) -> str:
    states = [
        available_probe.get("capability"),
        unavailable_probe.get("capability"),
        restored_probe.get("capability"),
    ]
    if states == ["capable", "blocked", "capable"]:
        return "availability_changed"
    if all(state == "not_tested" for state in states):
        if error:
            return "blocked"
        if skipped:
            return "skipped"
        return "probe_not_available"
    if error and all(not state for state in states):
        return "blocked"
    if skipped and all(not state for state in states):
        return "skipped"
    return "availability_not_changed"


def _availability_discovery_category(result_value: str) -> str:
    if result_value in {"blocked", "skipped"}:
        return "blocked_or_skipped"
    if result_value == "availability_changed":
        return "availability_changed"
    if result_value == "availability_changed_label_mismatch":
        return "label_mismatch"
    if result_value in {"availability_not_changed", "target_row_not_found", "manual_review"}:
        return "availability_not_changed_or_manual_review"
    return "manual_review_or_unknown"


def _legacy_display_rule_discovery_tables(rule_discovery_result: pd.DataFrame) -> None:
    print("전체 rule_discovery_result")
    display(rule_discovery_result)


def display_rule_discovery_tables(rule_discovery_result: pd.DataFrame) -> None:
    print("전체 rule_discovery_result")
    display(rule_discovery_result)


def export_rule_discovery_result(rule_discovery_result: pd.DataFrame, path: str | Path) -> None:
    if rule_discovery_result.empty:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rule_discovery_result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print("exported:", output_path)


def observed_query_rows_from_snapshot(snapshot: Any) -> list[str]:
    rows: list[str] = []
    for row in getattr(snapshot, "query_rows", []) or []:
        _append_query_text(rows, str(row))
    for row in snapshot.visible_rows or []:
        text = str(row)
        if "Query [" in text:
            _append_query_text(rows, text)
    for row in getattr(snapshot, "invalid_row_labels", []) or []:
        _append_query_text(rows, str(row))
    return rows


def _query_rows_diff(after_rows: list[str], before_rows: list[str]) -> list[str]:
    before_keys = {_normalize_query_row(row) for row in before_rows}
    diff: list[str] = []
    for row in after_rows:
        if _normalize_query_row(row) not in before_keys:
            _append_query_text(diff, row)
    return diff


def _observed_query_rows_for_mode(
    *,
    after_rows: list[str],
    before_rows: list[str],
    initial_rows: list[str],
    wait_query_rows: list[str],
    query_observation_mode: str,
) -> list[str]:
    if query_observation_mode == "sweep":
        observed_rows = _query_rows_diff(after_rows, initial_rows)
        for row in wait_query_rows:
            _append_query_text(observed_rows, row)
        return observed_rows

    observed_rows: list[str] = []
    for row in after_rows:
        _append_query_text(observed_rows, row)
    for row in wait_query_rows:
        _append_query_text(observed_rows, row)
    return observed_rows


def _normalize_query_row(row: Any) -> str:
    return _normalize_text(row)


def _append_query_text(rows: list[str], text: str) -> None:
    if not text:
        return
    messages = _extract_query_messages(text)
    if not messages and "Query [" in text:
        messages = [text.strip()]
    for message in messages:
        if message and message not in rows:
            rows.append(message)


def _extract_query_messages(text: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"Query \[", text)]
    messages: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        chunk = text[start:end].strip()
        for marker in ("· System", "- System"):
            marker_index = chunk.find(marker)
            if marker_index >= 0:
                chunk = chunk[: marker_index + len(marker)].strip()
                break
        if chunk and chunk not in messages:
            messages.append(chunk)
    return messages


def test_script_text(candidate: dict[str, Any]) -> str:
    if candidate.get("rule_type") == "availability":
        explicit = str(candidate.get("Test Script") or "").strip()
        if explicit:
            return explicit
        unavailable = "\n".join(_step_call_text(step) for step in (candidate.get("steps_to_make_unavailable") or []))
        available = "\n".join(_step_call_text(step) for step in (candidate.get("steps_to_make_available") or []))
        return "\n".join(part for part in (unavailable, available) if part)
    setup = "\n".join(_step_call_text(step) for step in _candidate_prerequisite_steps(candidate))
    main = "\n".join(_step_call_text(step) for step in _candidate_execution_steps(candidate))
    return "\n".join(part for part in (setup, main) if part)


def _candidate_execution_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("validation_steps", "condition_steps", "steps"):
        steps = candidate.get(key)
        if steps:
            return list(steps)
    return []


def _candidate_prerequisite_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return list(candidate.get("prerequisite_steps") or candidate.get("setup_steps") or [])


def _candidate_requires_prerequisite(candidate: dict[str, Any]) -> bool:
    if "requires_prerequisite" in candidate:
        return bool(candidate.get("requires_prerequisite"))
    if "requires_setup" in candidate:
        return bool(candidate.get("requires_setup"))
    return bool(_candidate_prerequisite_steps(candidate))


def _run_discovery_step(agent: Any, step: dict[str, Any], *, client_id: str | None = None) -> Any:
    method = step.get("method")
    args = step.get("args") or []
    kwargs = dict(step.get("kwargs") or {})
    if client_id and "client_id" not in kwargs:
        kwargs["client_id"] = client_id
    return getattr(agent, method)(*args, **kwargs)


def _clear_target_query_before_candidate(
    agent: Any,
    candidate: dict[str, Any],
    *,
    before_snap: Any,
    page_id: str,
    visit_id: str | None,
    client_id: str | None,
    stable_inspect_attempts: int,
    stable_inspect_delay_seconds: float,
) -> dict[str, Any]:
    before_rows = observed_query_rows_from_snapshot(before_snap)
    target_rows = _target_query_rows(before_rows, candidate)
    labels = _candidate_query_labels(candidate)
    result: dict[str, Any] = {
        "attempted": False,
        "failed": False,
        "before": before_rows,
        "after": before_rows,
        "cleared": [],
        "labels": labels,
        "snapshot": before_snap,
    }
    if not target_rows:
        return result
    if not hasattr(agent, "clear_query"):
        result["attempted"] = True
        result["failed"] = True
        result["error"] = "agent.clear_query is unavailable"
        return result

    clear_labels = _query_labels_from_rows(target_rows) or labels
    for label in clear_labels:
        try:
            kwargs: dict[str, Any] = {"page_id": page_id, "visit_id": visit_id}
            if client_id:
                kwargs["client_id"] = client_id
            agent.clear_query(label, **kwargs)
            result["attempted"] = True
            result["cleared"].append(label)
            if stable_inspect_delay_seconds:
                time.sleep(stable_inspect_delay_seconds)
        except Exception as exc:
            result["attempted"] = True
            result["error"] = str(exc)
            print("query clear error:", label, exc)

    after_snap = _settled_inspect(
        agent,
        page_id=page_id,
        client_id=client_id,
        attempts=stable_inspect_attempts,
        delay_seconds=stable_inspect_delay_seconds,
    )
    after_rows = observed_query_rows_from_snapshot(after_snap)
    remaining = _target_query_rows(after_rows, candidate)
    result["after"] = after_rows
    result["remaining"] = remaining
    result["snapshot"] = after_snap
    result["failed"] = bool(remaining)
    return result


def _query_labels_from_rows(rows: list[str]) -> list[str]:
    labels: list[str] = []
    for row in rows:
        for label in _extract_query_labels(row):
            if label and label not in labels:
                labels.append(label)
    return labels


def _stable_inspect(
    agent: Any,
    *,
    page_id: str | None,
    client_id: str | None,
    attempts: int,
    delay_seconds: float,
) -> Any:
    last_snapshot = None
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        snapshot = agent.inspect(client_id=client_id) if client_id else agent.inspect()
        last_snapshot = snapshot
        if _snapshot_matches_page(snapshot, page_id):
            return snapshot
        if attempt + 1 < attempts and delay_seconds:
            time.sleep(delay_seconds)
    return last_snapshot


def _settled_inspect(
    agent: Any,
    *,
    page_id: str | None,
    client_id: str | None,
    attempts: int,
    delay_seconds: float,
) -> Any:
    last_snapshot = None
    last_matching_snapshot = None
    attempts = max(1, int(attempts or 1))
    for attempt in range(attempts):
        snapshot = agent.inspect(client_id=client_id) if client_id else agent.inspect()
        last_snapshot = snapshot
        if _snapshot_matches_page(snapshot, page_id):
            last_matching_snapshot = snapshot
        if attempt + 1 < attempts and delay_seconds:
            time.sleep(delay_seconds)
    return last_matching_snapshot or last_snapshot


def _snapshot_matches_page(snapshot: Any, page_id: str | None) -> bool:
    label = str(getattr(snapshot, "page_label", "") or "").strip()
    if _is_unsupported_page_label(label):
        return False
    if not page_id:
        return bool(label)
    page_id = str(page_id)
    pathname = str(getattr(snapshot, "pathname", "") or "")
    if re.search(rf"(^|/){re.escape(page_id)}($|/)", pathname):
        return True
    return False


def _is_unsupported_page_label(label: Any) -> bool:
    return str(label or "").strip().lower() == "your browser is not supported"


def _step_call_text(step: dict[str, Any]) -> str:
    method = step.get("method")
    args = ", ".join(repr(arg) for arg in (step.get("args") or []))
    kwargs = ", ".join(f"{key}={value!r}" for key, value in (step.get("kwargs") or {}).items())
    joined = ", ".join(part for part in (args, kwargs) if part)
    return f"agent.{method}({joined})"


def _step_result_summary(result: Any) -> str | None:
    raw = getattr(result, "raw", None)
    if isinstance(raw, dict):
        return raw.get("outcome") or raw.get("status") or raw.get("result")
    return getattr(result, "outcome", None) or getattr(result, "status", None)


def _query_observation_value(query_count: int, step_results: list[dict[str, Any]], save_error: str | None) -> str:
    if save_error:
        return "blocked"
    if any(not item.get("ok", True) for item in step_results):
        return "blocked"
    if any(item.get("outcome") == "skipped" for item in step_results):
        return "skipped"
    return "query_observed" if query_count > 0 else "no_query_observed"


def _query_result_and_category(
    expected_result: Any,
    *,
    before_count: int,
    after_count: int,
    observed_count: int,
    step_results: list[dict[str, Any]],
    save_error: str | None,
) -> tuple[str, str]:
    if save_error or any(not item.get("ok", True) for item in step_results):
        return "REVIEW", "blocked_or_step_error"
    if any(item.get("outcome") == "skipped" for item in step_results):
        return "REVIEW", "skipped"

    expected = str(expected_result or "").strip()
    if expected == "query_expected":
        if after_count > 0 and before_count == 0:
            return "PASS", "newly_observed"
        if after_count > 0 and before_count > 0:
            return "PASS", "already_observed"
        if before_count > 0 and after_count == 0:
            return "REVIEW", "preexisting_query_not_visible_after_run"
        if observed_count > 0:
            return "PASS", "observed_by_event"
        return "FAIL", "expected_but_not_observed"

    if expected == "no_query_expected":
        if before_count > 0:
            return "REVIEW", "preexisting_query_blocks_negative_check"
        if after_count > 0 or observed_count > 0:
            return "FAIL", "not_expected_but_observed"
        return "PASS", "not_expected_and_not_observed"

    return "FAIL", "manual_review_or_unknown"


def _result_value(expected_result: Any, actual_observation: str) -> str:
    expected = str(expected_result or "").strip()
    if expected == "query_expected":
        return "PASS" if actual_observation == "query_observed" else "FAIL"
    if expected == "no_query_expected":
        return "PASS" if actual_observation == "no_query_observed" else "FAIL"
    if expected == "availability_changed":
        if actual_observation == "availability_changed":
            return "PASS"
        if actual_observation == "availability_changed_label_mismatch":
            return "LABEL_MISMATCH"
        return "FAIL"
    return "FAIL"


def _target_query_rows(observed_query_rows: list[str], candidate: dict[str, Any]) -> list[str]:
    labels = _candidate_query_labels(candidate)
    print("query_match_labels:", labels)
    if not labels:
        return []
    target_rows: list[str] = []
    for row in observed_query_rows:
        if any(_query_label_matches(row, label) for label in labels):
            target_rows.append(row)
    return target_rows


def _unique_query_rows(rows: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = _normalize_query_row(row)
        if key and key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _candidate_query_labels(candidate: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for value in _as_list(candidate.get("expected_query_message_labels")):
        text = str(value or "").strip()
        if text:
            labels.append(text)
    text = str(candidate.get("expected_query_message_label") or "").strip()
    if text:
        labels.append(text)
    for value in (candidate.get("item_label"),):
        text = str(value or "").strip()
        if text and text.lower() != "unknown":
            labels.append(text)

    main_step_labels: list[str] = []
    for step in _candidate_execution_steps(candidate):
        if str(step.get("note") or "").strip().upper() != "MAIN":
            continue
        args = step.get("args") or []
        if args:
            text = str(args[0]).strip()
            if text:
                main_step_labels.append(text)
                labels.append(text)

    for value in candidate.get("input_item_labels") or []:
        text = str(value or "").strip()
        if text and any(_normalize_text(text) == _normalize_text(label) for label in main_step_labels):
            labels.append(text)

    if not labels:
        item_id = str(candidate.get("item_id") or "").strip()
        if item_id and item_id.lower() != "unknown":
            labels.append(item_id)
        for step in _candidate_execution_steps(candidate):
            args = step.get("args") or []
            if args:
                text = str(args[0]).strip()
                if text:
                    labels.append(text)

    return _unique_normalized_labels(labels)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_normalized_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_labels: list[str] = []
    for label in labels:
        normalized = _normalize_text(label)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_labels.append(label)
    return unique_labels


def _query_label_matches(query_row: str, label: str) -> bool:
    normalized_label = _normalize_text(label)
    if not normalized_label:
        return False
    query_labels = _extract_query_labels(query_row)
    if query_labels:
        for query_label in query_labels:
            normalized_query_label = _normalize_text(query_label)
            if normalized_query_label == normalized_label:
                return True
            if _allow_contains_match(normalized_query_label, normalized_label):
                return True
        return False

    normalized_query_row = _normalize_text(query_row)
    return f"query[{normalized_label}]" in normalized_query_row or _allow_contains_match(
        normalized_query_row,
        normalized_label,
    )


def _extract_query_labels(text: str) -> list[str]:
    labels: list[str] = []
    marker = "Query ["
    start = 0
    while True:
        marker_index = text.find(marker, start)
        if marker_index < 0:
            break
        label_start = marker_index + len(marker)
        depth = 1
        index = label_start
        while index < len(text):
            char = text[index]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    label = text[label_start:index].strip()
                    if label:
                        labels.append(label)
                    start = index + 1
                    break
            index += 1
        else:
            break
    return labels


def _allow_contains_match(left: str, right: str) -> bool:
    if len(left) <= 2 or len(right) <= 2:
        return False
    return left in right or right in left


def _discovery_category(expected_result: Any, result_value: str) -> str:
    if result_value in {"blocked", "skipped"}:
        return "blocked_or_skipped"
    expected_has_query = _expected_has_query(expected_result)
    if expected_has_query is None:
        return "manual_review_or_unknown"
    actual_has_query = result_value == "query_observed"
    if expected_has_query and actual_has_query:
        return "expected_and_observed"
    if expected_has_query and not actual_has_query:
        return "expected_but_not_observed"
    if not expected_has_query and actual_has_query:
        return "not_expected_but_observed"
    return "not_expected_and_not_observed"


def _sweep_discovery_category(query_count: int, observed_query_rows: list[str]) -> str:
    if query_count > 0:
        return "matched"
    if observed_query_rows:
        return "ambiguous"
    return "unmatched"


def _expected_has_query(expected_result: Any) -> bool | None:
    value = str(expected_result or "").strip()
    if value == "query_expected":
        return True
    if value == "no_query_expected":
        return False
    return None


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    for marker in ("· System", "- System", "쨌 System"):
        text = text.replace(marker, "")
    text = re.sub(r"^query\s*\[", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", "", text.strip()).lower()
