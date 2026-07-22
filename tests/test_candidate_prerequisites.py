from cdm_agent_client.crf.candidate_prerequisites import enrich_same_page_prerequisites
from cdm_agent_client.crf.models import FieldDef


class FakeRunner:
    def __init__(self):
        self._spec = {
            "pages": {
                "DM": [
                    {
                        "pageId": "DM",
                        "itemId": "BMLOC",
                        "label": "Location",
                        "availability": [
                            {
                                "left": {"itemId": "BMYN"},
                                "operator": "=",
                                "right": [1],
                            }
                        ],
                    },
                    {
                        "pageId": "DM",
                        "itemId": "BSLOC",
                        "label": "Location",
                        "availability": [
                            {
                                "left": {"itemId": "BSYN"},
                                "operator": "=",
                                "right": [1],
                            }
                        ],
                    },
                ]
            }
        }
        self._field_map = {
            "DM.BMYN": FieldDef(
                item_id="BMYN",
                label="Breast cancer history",
                field_type="SINGLE_SELECT",
                layout="RADIO",
                page_id="DM",
                section_id="DM2_BH",
                options=[{"uiVal": "Yes", "dbVal": 1}, {"uiVal": "No", "dbVal": 2}],
            ),
            "DM.BSYN": FieldDef(
                item_id="BSYN",
                label="Breast surgery history",
                field_type="SINGLE_SELECT",
                layout="RADIO",
                page_id="DM",
                section_id="DM3_BM",
                options=[{"uiVal": "Yes", "dbVal": 1}, {"uiVal": "No", "dbVal": 2}],
            ),
        }


def test_same_page_prerequisites_are_added_from_target_and_input_items():
    candidate = {
        "DVS ID": "D_DM_14_1",
        "item_id": "BSLOC",
        "input_item_ids": ["BMLOC", "BSLOC"],
        "steps": [{"method": "select_radio", "args": ["Location", "Left"], "kwargs": {"page_id": "DM", "visit_id": "V1"}}],
    }

    enriched = enrich_same_page_prerequisites(candidate, FakeRunner(), current_page_id="DM", visit_id="V1")

    assert enriched["requires_prerequisite"] is True
    assert enriched["prerequisite_item_ids"] == ["BSYN", "BMYN"]
    assert enriched["prerequisite_steps_count"] == 2
    assert enriched["prerequisite_reason"] == "same_page_availability"
    assert enriched["prerequisite_steps"][0]["args"] == ["Breast surgery history", "Yes"]
    assert enriched["prerequisite_steps"][1]["args"] == ["Breast cancer history", "Yes"]


def test_same_page_prerequisites_are_not_added_when_no_availability_spec():
    candidate = {"DVS ID": "D_DM_5", "item_id": "OPINDCR", "input_item_ids": ["OPINDCL", "OPINDCR"]}

    enriched = enrich_same_page_prerequisites(candidate, FakeRunner(), current_page_id="DM", visit_id="V1")

    assert enriched["requires_prerequisite"] is False
    assert "prerequisite_steps" not in enriched


def test_legacy_setup_steps_are_preserved_as_prerequisite_fallback():
    candidate = {
        "DVS ID": "LEGACY",
        "item_id": "OPINDCR",
        "input_item_ids": ["OPINDCR"],
        "setup_steps": [{"method": "select_radio", "args": ["Legacy", "Yes"], "kwargs": {"page_id": "DM"}}],
    }

    enriched = enrich_same_page_prerequisites(candidate, FakeRunner(), current_page_id="DM", visit_id="V1")

    assert enriched["requires_prerequisite"] is True
    assert enriched["prerequisite_steps_count"] == 1
    assert enriched["prerequisite_steps"] == candidate["setup_steps"]
