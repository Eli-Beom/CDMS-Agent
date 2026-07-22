from cdm_agent_client.crf.availability_discovery import (
    _parse_simple_availability_rules,
    _value_for_rule,
    build_browser_availability_discovery_candidates,
)
from cdm_agent_client.crf.availability_discovery_runtime import _observation_result
from cdm_agent_client.crf.models import FieldDef


class FakeRunner:
    def __init__(self):
        self._spec = {
            "pages": {
                "DM": [
                {
                    "pageId": "DM",
                    "itemId": "PGNREAS",
                    "label": "비가임 사유",
                    "availability": [
                        {
                            "left": {"itemId": "PGYN"},
                            "operator": "=",
                            "right": [2],
                        }
                    ],
                }
                ]
            }
        }
        self._field_map = {
            "DM.PGYN": FieldDef(
                item_id="PGYN",
                label="가임 여부",
                field_type="SINGLE_SELECT",
                layout="RADIO",
                page_id="DM",
                section_id="DM",
                options=[{"uiVal": "예", "dbVal": 1}, {"uiVal": "아니요", "dbVal": 2}],
            )
        }


def test_parse_operand_style_availability_rule():
    rules = _parse_simple_availability_rules(
        [{"left": {"itemId": "PGYN"}, "operator": "=", "right": [2]}]
    )

    assert rules == [{"control_item_id": "PGYN", "condition": "=", "operand": 2}]


def test_availability_value_toggle_for_equals_rule():
    rule = {"control_item_id": "PGYN", "condition": "=", "operand": 2}

    assert _value_for_rule(rule, make_available=True) == 2
    assert _value_for_rule(rule, make_available=False) == 1


def test_build_candidates_maps_control_steps():
    context = {
        "page_id": "DM",
        "pathname": "/s/study/subjects/subject/NV/V1/1/DM/1",
        "structured_rows": [{"rowLabel": "비가임 사유", "editable": True, "visible": True}],
    }

    candidates = build_browser_availability_discovery_candidates(FakeRunner(), context)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["target_item_id"] == "PGNREAS"
    assert candidate["control_item_id"] == "PGYN"
    assert candidate["steps_to_make_unavailable"][0]["args"] == ["가임 여부", "예"]
    assert candidate["steps_to_make_available"][0]["args"] == ["가임 여부", "아니요"]


def test_observation_result_detects_expected_change():
    before = {"row_availability": "available"}
    after_unavailable = {"row_availability": "unavailable"}
    after_available = {"row_availability": "available"}

    assert (
        _observation_result(before, after_unavailable, after_available, None)
        == "availability_changed_as_expected"
    )
