from cdm_agent_client.crf.discovery.rule_discovery_runtime import (
    _availability_input_observation_value,
    _availability_probe_record,
    _candidate_availability_probe_steps,
    _availability_observation_value,
    _candidate_query_labels,
    _discovery_category,
    _extract_query_labels,
    _observed_query_rows_for_mode,
    _query_rows_diff,
    _query_observation_value,
    _result_value,
    _row_label_counter,
    _row_state,
    _target_query_rows,
    test_script_text as rule_test_script_text,
)


def test_step_error_is_blocked():
    result = _query_observation_value(
        0,
        [{"method": "set_date", "ok": False, "error": "No connected browser client"}],
        None,
    )

    assert result == "blocked"


def test_discovery_category_expected_but_not_observed():
    assert _discovery_category("query_expected", "no_query_observed") == "expected_but_not_observed"


def test_discovery_category_not_expected_but_observed():
    assert _discovery_category("no_query_expected", "query_observed") == "not_expected_but_observed"


def test_target_query_rows_match_candidate_label():
    rows = [
        "Query [Age] subject must be at least 22 years old. · System",
        "Query [Sex] missing input · System",
    ]
    candidate = {
        "item_label": "Age",
        "item_id": "AGE",
        "steps": [{"args": ["Birth date", "2005-01-01"]}],
    }

    assert _target_query_rows(rows, candidate) == [rows[0]]


def test_query_rows_diff_returns_new_queries_only():
    before = ["Query [Age] old message 쨌 System"]
    after = [
        "Query [Age] old message 쨌 System",
        "Query [Sex] new message 쨌 System",
    ]

    assert _query_rows_diff(after, before) == ["Query [Sex] new message 쨌 System"]


def test_per_candidate_observation_uses_after_snapshot_not_diff():
    before = ["Query [Age] old message 쨌 System"]
    after = ["Query [Age] old message 쨌 System"]

    observed = _observed_query_rows_for_mode(
        after_rows=after,
        before_rows=before,
        initial_rows=before,
        wait_query_rows=[],
        query_observation_mode="per_candidate",
    )

    assert observed == after


def test_sweep_observation_still_uses_initial_diff():
    initial = ["Query [Age] old message 쨌 System"]
    after = [
        "Query [Age] old message 쨌 System",
        "Query [Sex] new message 쨌 System",
    ]

    observed = _observed_query_rows_for_mode(
        after_rows=after,
        before_rows=initial,
        initial_rows=initial,
        wait_query_rows=[],
        query_observation_mode="sweep",
    )

    assert observed == ["Query [Sex] new message 쨌 System"]


def test_candidate_query_labels_include_expected_item_and_main_step_labels():
    candidate = {
        "item_label": "[Left breast] Surgery purpose",
        "item_id": "OPINDCL",
        "expected_query_message_label": "[Right breast] Surgery purpose",
        "steps": [{"note": "MAIN", "args": ["[Left breast] Surgery purpose", "None"]}],
    }

    assert _candidate_query_labels(candidate) == [
        "[Right breast] Surgery purpose",
        "[Left breast] Surgery purpose",
    ]


def test_extract_query_labels_handles_nested_brackets():
    row = "Query [[우측 유방] 수술 목적] 입력 누락 · System"

    assert _extract_query_labels(row) == ["[우측 유방] 수술 목적"]


def test_target_query_rows_match_nested_query_label():
    rows = ["Query [[우측 유방] 수술 목적] 입력 누락 · System"]
    candidate = {"expected_query_message_label": "[우측 유방] 수술 목적"}

    assert _target_query_rows(rows, candidate) == rows


def test_candidate_query_labels_include_main_steps_but_not_precond_steps():
    candidate = {
        "item_label": "수유 여부",
        "steps": [
            {"note": "PRECOND", "args": ["생년월일", "2005-01-01"]},
            {"note": "MAIN", "args": ["수유 여부", "예"]},
        ],
    }

    labels = _candidate_query_labels(candidate)

    assert "수유 여부" in labels
    assert "생년월일" not in labels


def test_target_query_rows_match_main_step_when_item_label_differs():
    rows = ["Query [수유 여부] 입력 누락 · System"]
    candidate = {
        "expected_query_message_label": "다른 라벨",
        "item_label": "다른 라벨",
        "steps": [{"note": "MAIN", "args": ["수유 여부", "예"]}],
    }

    assert _target_query_rows(rows, candidate) == rows


def test_target_query_rows_do_not_match_precond_only_label():
    rows = ["Query [생년월일] 입력 누락 · System"]
    candidate = {
        "item_label": "수유 여부",
        "steps": [
            {"note": "PRECOND", "args": ["생년월일", "2005-01-01"]},
            {"note": "MAIN", "args": ["수유 여부", "예"]},
        ],
    }

    assert _target_query_rows(rows, candidate) == []


def test_availability_result_changed():
    assert (
        _availability_observation_value(
            {"row_availability": "available"},
            {"row_availability": "unavailable"},
            {"row_availability": "available"},
            None,
            False,
        )
        == "availability_changed"
    )


def test_availability_result_changed_when_unavailable_row_disappears():
    assert (
        _availability_observation_value(
            {"row_availability": "available"},
            {"row_availability": "not_found"},
            {"row_availability": "available"},
            None,
            False,
        )
        == "availability_changed"
    )


def test_row_state_returns_not_found_state_for_missing_target():
    class Snapshot:
        structured_rows = [{"rowLabel": "Other", "row_availability": "available"}]

    state = _row_state(Snapshot(), {"item_id": "TARGET", "item_label": "Target"})

    assert state["row_availability"] == "not_found"
    assert state["visible"] is False
    assert state["match_quality"] == "not_found"


def test_row_label_counter_preserves_duplicate_labels():
    class Snapshot:
        structured_rows = [
            {"rowLabel": "부위"},
            {"rowLabel": "부위"},
            {"rowLabel": "나이"},
        ]

    counts = _row_label_counter(Snapshot())

    assert counts["부위"] == 2
    assert counts["나이"] == 1


def test_result_value_is_pass_fail():
    assert _result_value("query_expected", "query_observed") == "PASS"
    assert _result_value("query_expected", "no_query_observed") == "FAIL"
    assert _result_value("availability_changed", "availability_changed") == "PASS"
    assert _result_value("availability_changed", "availability_not_changed") == "FAIL"


def test_availability_input_probe_changed_pattern_passes():
    assert (
        _availability_input_observation_value(
            {"capability": "capable"},
            {"capability": "blocked"},
            {"capability": "capable"},
            "step outcome failed",
            False,
        )
        == "availability_changed"
    )
    assert (
        _availability_input_observation_value(
            {"capability": "not_tested"},
            {"capability": "not_tested"},
            {"capability": "not_tested"},
            "step outcome failed",
            False,
        )
        == "blocked"
    )
    assert (
        _availability_input_observation_value(
            {"capability": "capable"},
            {"capability": "blocked"},
            {"capability": "capable"},
            None,
            False,
        )
        == "availability_changed"
    )
    assert (
        _availability_input_observation_value(
            {"capability": "capable"},
            {"capability": "capable"},
            {"capability": "capable"},
            None,
            False,
        )
        == "availability_not_changed"
    )
    assert (
        _availability_input_observation_value(
            {"capability": "not_tested"},
            {"capability": "not_tested"},
            {"capability": "not_tested"},
            None,
            False,
        )
        == "probe_not_available"
    )


def test_availability_probe_record_uses_probe_radio_checked_state():
    class Result:
        raw = {
            "outcome": "passed",
            "inputs": [
                {
                    "action": "selectRadio",
                    "rowLabel": "부위",
                    "optionLabel": "좌",
                    "outcome": "failed",
                    "checked": False,
                }
            ],
        }

    record = _availability_probe_record(Result(), {"method": "probe_radio", "args": ["부위", "좌"]})

    assert record["checked"] is False
    assert record["outcome"] == "failed"


def test_candidate_availability_probe_steps_prefers_multi_step_list():
    candidate = {
        "availability_probe_step": {"method": "probe_radio", "args": ["부위", "좌"]},
        "availability_probe_steps": [
            {"method": "probe_radio", "args": ["부위", "좌"]},
            {"method": "probe_radio", "args": ["부위", "우"]},
            {"method": "probe_radio", "args": ["부위", "좌&우"]},
        ],
    }

    steps = _candidate_availability_probe_steps(candidate)

    assert [step["args"][1] for step in steps] == ["좌", "우", "좌&우"]


def test_availability_test_script_uses_availability_steps():
    candidate = {
        "rule_type": "availability",
        "steps_to_make_unavailable": [{"method": "select_radio", "args": ["Available?", "Yes"], "kwargs": {}}],
        "steps_to_make_available": [{"method": "select_radio", "args": ["Available?", "No"], "kwargs": {}}],
    }

    script = rule_test_script_text(candidate)

    assert "agent.select_radio('Available?', 'Yes')" in script
    assert "agent.select_radio('Available?', 'No')" in script
