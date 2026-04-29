from __future__ import annotations

import uuid
from typing import Any

import requests

from .exceptions import CDMAgentError, DaemonNotRunningError, NoBrowserClientError, StepFailedError
from .models import PageSnapshot, StepResult

_DEFAULT_URL = "http://127.0.0.1:3100"


class CDMAgent:
    """Python client for the CDM Agent daemon.

    Wraps the daemon's HTTP API so CDMS browser sessions can be driven from
    Jupyter notebooks or plain Python scripts without touching the runner code
    directly.

    Parameters
    ----------
    base_url:
        Base URL of the running daemon (default ``http://127.0.0.1:3100``).
    study_id:
        Optional study identifier forwarded with every request so the daemon
        can persist session state and link executions to the correct study.
    timeout:
        HTTP request timeout in seconds (default 30).  ``run_case`` calls use
        ``run_timeout`` instead, which defaults to 120 s.
    run_timeout:
        Timeout for ``run_case``-based calls (``set_date``, ``click_save_next``).
        These block until the browser step completes.
    raise_on_failure:
        When ``True`` (default), steps that return outcome ``failed`` or
        ``blocked`` raise :class:`StepFailedError`.  Set to ``False`` to get
        the :class:`StepResult` back regardless.
    runner:
        Browser runner type registered with the daemon.  Chrome extension
        clients register as ``"extension"`` (default).  Tampermonkey-based
        clients register as ``"tm"``.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_URL,
        *,
        study_id: str | None = None,
        timeout: int = 30,
        run_timeout: int = 120,
        raise_on_failure: bool = True,
        runner: str = "extension",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.study_id = study_id
        self.timeout = timeout
        self.run_timeout = run_timeout
        self.raise_on_failure = raise_on_failure
        self.runner = runner
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect(self, *, client_id: str | None = None) -> PageSnapshot:
        """Capture a snapshot of the currently open CDMS page.

        Returns a :class:`PageSnapshot` which renders as a rich HTML table in
        Jupyter.

        Parameters
        ----------
        client_id:
            Target a specific browser client by ID.  Leave ``None`` to let the
            daemon pick the most recently active client.
        """
        params: dict[str, str] = {}
        if self.study_id:
            params["studyId"] = self.study_id
        if client_id:
            params["clientId"] = client_id

        data = self._get("/api/cdm-agent/inspect-active-page", params=params)
        snap = PageSnapshot.from_api(data)

        if not snap.connected:
            raise NoBrowserClientError()

        if snap.error:
            raise CDMAgentError(f"Runner error on page: {snap.error}")

        return snap

    def set_date(
        self,
        row_label: str,
        value: str,
        *,
        page_id: str | None = None,
        visit_id: str | None = None,
        client_id: str | None = None,
    ) -> StepResult:
        """Type a date value into a labelled field on the current CDMS page.

        The runner finds the field by its visible row label (e.g.
        ``"Visit date"``), clears any existing value, and enters the new one.

        Parameters
        ----------
        row_label:
            The visible text label of the target field row.
        value:
            Date string in any format the CDMS form accepts (e.g.
            ``"2025-01-15"`` or ``"15-Jan-2025"``).
        page_id:
            CRF page identifier, forwarded to the daemon for session tracking.
        visit_id:
            Visit identifier, forwarded to the daemon for session tracking.
        client_id:
            Target a specific browser client by ID.
        """
        case = self._build_set_field_case(
            row_label=row_label,
            value=value,
            title=f"Set date: {row_label} = {value}",
            page_id=page_id,
            visit_id=visit_id,
        )
        return self._run_case(case, client_id=client_id)

    def set_text(
        self,
        row_label: str,
        value: str,
        *,
        page_id: str | None = None,
        visit_id: str | None = None,
        client_id: str | None = None,
    ) -> StepResult:
        """Type a plain text or numeric value into a labelled field.

        Use this for non-date fields (e.g. weight, subject ID).
        For date fields with a calendar picker, use :meth:`set_date` instead.
        """
        case = self._build_set_text_case(
            row_label=row_label,
            value=value,
            title=f"Set text: {row_label} = {value}",
            page_id=page_id,
            visit_id=visit_id,
        )
        return self._run_case(case, client_id=client_id)

    def select_option(
        self,
        row_label: str,
        option_label: str,
        *,
        page_id: str | None = None,
        visit_id: str | None = None,
        client_id: str | None = None,
    ) -> StepResult:
        """Select an option from a combobox / dropdown field."""
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": f"Select option: {row_label} = {option_label}",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [{"action": "selectComboboxOption", "rowLabel": row_label, "optionLabel": option_label}],
            "expected": {},
        }
        return self._run_case(case, client_id=client_id)

    def select_radio(
        self,
        row_label: str,
        option_label: str,
        *,
        page_id: str | None = None,
        visit_id: str | None = None,
        client_id: str | None = None,
    ) -> StepResult:
        """Select a radio button option."""
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": f"Select radio: {row_label} = {option_label}",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [{"action": "selectRadio", "rowLabel": row_label, "optionLabel": option_label}],
            "expected": {},
        }
        return self._run_case(case, client_id=client_id)

    def click_save_next(
        self,
        *,
        client_id: str | None = None,
        page_id: str | None = None,
        visit_id: str | None = None,
    ) -> StepResult:
        """Click the primary Save & Next button on the current CDMS page.

        The runner looks for any visible button whose label contains "Save" or
        "Next" (case-insensitive) and is not disabled.

        Parameters
        ----------
        client_id:
            Target a specific browser client by ID.
        page_id:
            CRF page identifier, forwarded for session tracking.
        visit_id:
            Visit identifier, forwarded for session tracking.
        """
        case = self._build_click_save_next_case(page_id=page_id, visit_id=visit_id)
        return self._run_case(case, client_id=client_id)

    # ------------------------------------------------------------------
    # Lower-level helpers (useful from scripts/notebooks)
    # ------------------------------------------------------------------

    def go_back(self, *, client_id: str | None = None) -> StepResult:
        """Navigate to the previous page using browser history (history.back()).

        Equivalent to clicking the browser Back button.
        """
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "positive_navigation",
            "title": "Go back",
            "preconditions": [],
            "steps": [{"action": "goBack"}],
            "expected": {"navigation": {"shouldMove": True}},
        }
        return self._run_case(case, client_id=client_id)

    def navigate_to(self, url: str, *, client_id: str | None = None) -> StepResult:
        """Navigate the browser directly to *url*.

        Useful for jumping to a specific CRF page whose URL you already know
        (e.g. from a previous ``inspect()`` snapshot).

        Parameters
        ----------
        url:
            Full URL **or** pathname.  If a pathname is given (starts with
            ``/``), it is resolved against the daemon's base URL automatically
            by the runner.
        """
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "positive_navigation",
            "title": f"Navigate to {url}",
            "preconditions": [],
            "steps": [{"action": "navigateToUrl", "url": url}],
            "expected": {"navigation": {"shouldMove": True}},
        }
        return self._run_case(case, client_id=client_id)

    def run_case(self, case_payload: dict[str, Any], *, client_id: str | None = None) -> StepResult:
        """Send an arbitrary TestCase payload to the daemon and execute it.

        Use this when you need full control over the case structure.  For
        common operations prefer :meth:`set_date` and :meth:`click_save_next`.
        """
        return self._run_case(case_payload, client_id=client_id)

    def clients(self) -> list[dict[str, Any]]:
        """Return the list of browser clients currently registered with the daemon."""
        data = self._get("/api/cdm-agent/browser/clients")
        return data.get("clients") or []

    def ping(self) -> bool:
        """Return ``True`` if the daemon is reachable."""
        try:
            self._get("/api/health")
            return True
        except CDMAgentError:
            return False

    def has_query(self, *, client_id: str | None = None) -> bool:
        """Return True if any validation query message is currently visible on the page.

        CDMS surfaces query messages as rows containing text like "쿼리" or
        field-level alert text.  This checks ``invalidRowLabels`` and
        ``invalidCount`` from the active-page snapshot.
        """
        snap = self.inspect(client_id=client_id)
        return snap.invalid_count > 0 or len(snap.invalid_row_labels) > 0

    def check_result(
        self,
        expected: str,
        *,
        client_id: str | None = None,
    ) -> str:
        """Compare the current page state against a DVS expected result string.

        Parameters
        ----------
        expected:
            ``"Query"`` or ``"No Query"`` (case-insensitive, as written in DVS).

        Returns
        -------
        ``"PASS"`` or ``"FAIL"``
        """
        snap = self.inspect(client_id=client_id)
        query_present = snap.invalid_count > 0 or len(snap.invalid_row_labels) > 0
        expects_query = expected.strip().lower() not in ("no query", "no_query", "nq")
        return "PASS" if query_present == expects_query else "FAIL"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_set_field_case(
        self,
        row_label: str,
        value: str,
        title: str,
        page_id: str | None,
        visit_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": title,
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [
                {
                    # Runner action: setDateViaCalendarPopup handles calendar icon +
                    # fallback direct input. Use setText for plain text/number fields.
                    "action": "setDateViaCalendarPopup",
                    "rowLabel": row_label,
                    "value": value,
                }
            ],
            "expected": {},
        }

    def _build_set_text_case(
        self,
        row_label: str,
        value: str,
        title: str,
        page_id: str | None,
        visit_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": title,
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [
                {
                    "action": "setText",
                    "rowLabel": row_label,
                    "value": value,
                }
            ],
            "expected": {},
        }

    def _build_click_save_next_case(
        self,
        page_id: str | None,
        visit_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "positive_navigation",
            "title": "Click Save & Next",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [
                {
                    "action": "clickSaveNext",
                }
            ],
            "expected": {
                "navigation": {"shouldMove": True},
            },
        }

    def _run_case(self, case_payload: dict[str, Any], *, client_id: str | None = None) -> StepResult:
        body: dict[str, Any] = {"case_payload": case_payload, "runner": self.runner}
        if client_id:
            body["client_id"] = client_id

        data = self._post("/api/cdm-agent/run-case", body, timeout=self.run_timeout)
        result = StepResult.from_api(data)

        if self.raise_on_failure and not result.ok:
            raise StepFailedError(result.outcome, result.failure_reason)

        return result

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            resp = self._session.get(self.base_url + path, params=params, timeout=self.timeout)
        except requests.exceptions.ConnectionError:
            raise DaemonNotRunningError(self.base_url)
        except requests.exceptions.Timeout:
            raise CDMAgentError(f"Request to {path} timed out after {self.timeout}s.")
        _raise_for_status(resp, path)
        return resp.json()

    def _post(self, path: str, body: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = self._session.post(self.base_url + path, json=body, timeout=effective_timeout)
        except requests.exceptions.ConnectionError:
            raise DaemonNotRunningError(self.base_url)
        except requests.exceptions.Timeout:
            raise CDMAgentError(f"Request to {path} timed out after {effective_timeout}s.")
        _raise_for_status(resp, path)
        return resp.json()

    def __repr__(self) -> str:
        return f"CDMAgent(base_url={self.base_url!r}, study_id={self.study_id!r}, runner={self.runner!r})"


def _raise_for_status(resp: requests.Response, path: str) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    raise CDMAgentError(f"Daemon returned HTTP {resp.status_code} for {path}: {detail}")
