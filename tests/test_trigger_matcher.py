from cdm_agent_client.crf.trigger_matcher import condition_branches, condition_comparisons


def test_condition_comparisons_extract_simple_and_leaves():
    trigger = {
        "id": "D_DM_5",
        "conditional": {
            "operator": "AND",
            "expr": [
                {
                    "left": {"crfPageId": "DM", "visitId": "V1", "sectionId": "DM", "itemId": "OPINDCL"},
                    "operator": "=",
                    "right": 3,
                },
                {
                    "left": {"crfPageId": "DM", "visitId": "V1", "sectionId": "DM", "itemId": "OPINDCR"},
                    "operator": "=",
                    "right": 3,
                },
            ],
        },
    }

    assert condition_comparisons(trigger) == [
        {
            "item_id": "OPINDCL",
            "operator": "=",
            "value": 3,
            "page_id": "DM",
            "visit_id": "V1",
            "section_id": "DM",
        },
        {
            "item_id": "OPINDCR",
            "operator": "=",
            "value": 3,
            "page_id": "DM",
            "visit_id": "V1",
            "section_id": "DM",
        },
    ]


def test_condition_comparisons_skip_item_to_item_conditions():
    trigger = {
        "conditional": {
            "left": {"itemId": "A"},
            "operator": "=",
            "right": {"itemId": "B"},
        }
    }

    assert condition_comparisons(trigger) == []


def test_condition_branches_expand_or_inside_and():
    trigger = {
        "conditional": {
            "operator": "AND",
            "expr": [
                {
                    "operator": "OR",
                    "expr": [
                        {"left": {"crfPageId": "DM", "itemId": "OPINDCL"}, "operator": "=", "right": 2},
                        {"left": {"crfPageId": "DM", "itemId": "OPINDCR"}, "operator": "=", "right": 2},
                    ],
                },
                {"operator": "AND", "expr": [{"left": {"crfPageId": "DM", "itemId": "BMYN"}, "operator": "=", "right": 2}]},
            ],
        }
    }

    assert condition_branches(trigger) == [
        [
            {"item_id": "OPINDCL", "operator": "=", "value": 2, "page_id": "DM", "visit_id": "", "section_id": ""},
            {"item_id": "BMYN", "operator": "=", "value": 2, "page_id": "DM", "visit_id": "", "section_id": ""},
        ],
        [
            {"item_id": "OPINDCR", "operator": "=", "value": 2, "page_id": "DM", "visit_id": "", "section_id": ""},
            {"item_id": "BMYN", "operator": "=", "value": 2, "page_id": "DM", "visit_id": "", "section_id": ""},
        ],
    ]
