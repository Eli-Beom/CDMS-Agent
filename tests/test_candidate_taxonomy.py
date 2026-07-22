from cdm_agent_client.crf.taxonomy import enrich_candidate_taxonomy, enrich_limitation_taxonomy


def test_age_candidate_taxonomy():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "D_DM_1_2",
            "item_id": "AGE",
            "item_label": "Age",
            "rule_type": "range_query",
            "Specification": "AGE<22",
            "Expected Result": "query_expected",
            "steps": [{"method": "set_date", "args": ["Birth date", "2003-01-02"], "kwargs": {"page_id": "DM"}}],
        },
        current_page_id="DM",
    )

    assert candidate["validation_category"] == "query"
    assert candidate["query_subtype"] == "range_age"
    assert candidate["calculation_subtype"] == "age"
    assert candidate["automation_scope"] == "current_page_only"
    assert candidate["expected_query_message_label"] == "Age"


def test_height_candidate_taxonomy():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "D_PY_3",
            "item_id": "HEIGHT",
            "item_label": "Height",
            "rule_type": "range_query",
            "Specification": "HEIGHT < 120 OR > 200",
            "Expected Result": "query_expected",
            "steps": [{"method": "set_text", "args": ["Height", "119"], "kwargs": {"page_id": "PE"}}],
        },
        current_page_id="PE",
    )

    assert candidate["validation_category"] == "query"
    assert candidate["query_subtype"] == "range_numeric"
    assert candidate["query_category"] == "range_query"
    assert candidate["condition_type"] == "none"
    assert candidate["automation_scope"] == "current_page_only"


def test_multi_condition_candidate_category():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "D_DM_5",
            "item_id": "OPINDCR",
            "item_label": "[Right breast] Surgery purpose",
            "rule_type": "query",
            "Specification": "OPINDCL=3 AND OPINDCR=3",
            "Expected Result": "query_expected",
            "condition_items": [
                {"item_id": "OPINDCL", "item_label": "[Left breast] Surgery purpose", "page_id": "DM"},
                {"item_id": "OPINDCR", "item_label": "[Right breast] Surgery purpose", "page_id": "DM"},
            ],
            "steps": [{"method": "select_radio", "args": ["[Left breast] Surgery purpose", "None"], "kwargs": {"page_id": "DM"}}],
        },
        current_page_id="DM",
    )

    assert candidate["query_category"] == "condition_query"
    assert candidate["condition_type"] == "multi"
    assert candidate["condition_steps"] == candidate["steps"]


def test_date_window_cross_page_candidate_taxonomy():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "D_BU_2",
            "item_id": "BUDAT",
            "item_label": "Exam date",
            "rule_type": "query",
            "Specification": "BUDAT - SVDAT < -28 OR > 0",
            "Expected Result": "query_expected",
            "steps": [
                {"method": "set_date", "args": ["Visit date", "2024-01-01"], "kwargs": {"page_id": "SV"}},
                {"method": "set_date", "args": ["Exam date", "2023-12-03"], "kwargs": {"page_id": "BU"}},
            ],
        },
        current_page_id="BU",
    )

    assert candidate["query_subtype"] == "date_window"
    assert candidate["automation_scope"] == "browser_assisted_cross_page"


def test_trigger_reference_sets_cross_page_scope_even_when_steps_are_current_page_only():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "D_BU_2",
            "item_id": "BUDAT",
            "item_label": "Exam date",
            "rule_type": "query",
            "Specification": "BUDAT - SVDAT < -28 OR > 0",
            "Expected Result": "query_expected",
            "steps": [{"method": "set_date", "args": ["Exam date", "2023-12-03"], "kwargs": {"page_id": "BU"}}],
        },
        current_page_id="BU",
        trigger={
            "id": "D_BU_2",
            "pageId": "BU",
            "conditional": {
                "left": {
                    "valAs": "DAYS",
                    "left": {"itemId": "BUDAT", "crfPageId": "BU"},
                    "right": {"itemId": "SVDAT", "crfPageId": "SV"},
                },
                "operator": "<",
                "right": -28,
            },
        },
    )

    assert candidate["automation_scope"] == "browser_assisted_cross_page"
    assert "SVDAT" in candidate["depends_on_item_id"]


def test_availability_candidate_taxonomy():
    candidate = enrich_candidate_taxonomy(
        {
            "DVS ID": "AVAIL_PE_HEIGHT",
            "item_id": "HEIGHT",
            "item_label": "Height",
            "rule_type": "availability",
            "Expected Result": "availability_changed",
            "steps_to_make_unavailable": [
                {"method": "select_radio", "args": ["Not done", "Yes"], "kwargs": {"page_id": "PE"}}
            ],
        },
        current_page_id="PE",
    )

    assert candidate["validation_category"] == "availability"
    assert candidate["query_subtype"] == ""
    assert candidate["automation_scope"] == "current_page_only"


def test_limitation_reason_codes():
    assert (
        enrich_limitation_taxonomy({"rule_type": "query", "reason": "appendable table required"})[
            "limitation_reason"
        ]
        == "appendable_table_required"
    )
    assert (
        enrich_limitation_taxonomy({"rule_type": "query", "reason": "Field not found: SV.SVDTC"})[
            "limitation_reason"
        ]
        == "target_row_not_found"
    )
