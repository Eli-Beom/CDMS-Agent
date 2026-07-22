from types import SimpleNamespace

from cdm_agent_client.crf.audit import audit_phase0, audit_query_cases, collect_calculation_items
from cdm_agent_client.crf.models import CRFCase, Step


class FakeRunner:
    def __init__(self):
        self._spec = {
            "triggers": [
                {
                    "id": "D_OK",
                    "type": "QUERY",
                    "pageId": "DM",
                    "issue": {"itemId": ["AGE"]},
                },
                {
                    "id": "D_FAIL",
                    "type": "QUERY",
                    "pageId": "PE",
                    "issue": {"itemId": "HEIGHT"},
                },
            ],
            "pages": {
                "DM": [
                    {
                        "itemId": "AGE",
                        "label": "Age",
                        "type": "AUTO_TEXT",
                        "calculate": {"operator": "AGE", "left": {"itemId": "BRTHDAT"}},
                    }
                ],
                "BQ": [
                    {
                        "itemId": "BQTOT",
                        "label": "Total",
                        "type": "AUTO_TEXT",
                        "calculate": {"operator": "SUM", "items": ["BQ01", "BQ02"]},
                    }
                ],
            },
        }

    def build_query_cases_for_trigger(self, trigger, *, expect_query):
        if trigger["id"] == "D_FAIL":
            case = CRFCase(kind="query_expected", id=trigger["id"], page=trigger["pageId"])
            case.errors.append("Could not generate input values from trigger conditional.")
            return [case]
        return [
            CRFCase(
                kind="query_expected" if expect_query else "no_query_expected",
                id=trigger["id"],
                page=trigger["pageId"],
                steps=[
                    Step("go_to_page", ["V1/DM"]),
                    Step("set_date", ["Birth date", "2003-01-02"], {"page_id": "DM", "visit_id": "V1"}),
                ],
            )
        ]


def test_audit_query_cases_reports_generation_status():
    rows = audit_query_cases(FakeRunner(), target_dvs_ids=["D_OK", "D_FAIL", "D_MISSING"])
    by_key = {(row["dvs_id"], row["expected_result"]): row for row in rows}

    assert by_key[("D_OK", "query_expected")]["generation_status"] == "generated"
    assert by_key[("D_OK", "query_expected")]["runnable_count"] == 1
    assert by_key[("D_FAIL", "query_expected")]["generation_status"] == "generation_failed"
    assert by_key[("D_MISSING", "query_expected")]["generation_status"] == "trigger_not_found"


def test_collect_calculation_items_classifies_calculations():
    rows = collect_calculation_items(FakeRunner())
    by_item = {row["item_id"]: row for row in rows}

    assert by_item["AGE"]["calculation_subtype"] == "age"
    assert by_item["BQTOT"]["calculation_subtype"] == "sum_score"


def test_audit_phase0_returns_query_and_calculation_sections():
    result = audit_phase0(FakeRunner(), target_dvs_ids=["D_OK"], calculation_item_ids=["AGE"])

    assert set(result) == {"query_case_audit", "calculation_item_audit"}
    assert result["query_case_audit"][0]["dvs_id"] == "D_OK"
    assert result["calculation_item_audit"][0]["item_id"] == "AGE"
