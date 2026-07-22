from __future__ import annotations

import uuid
from typing import Any

import requests

from .exceptions import CDMAgentError, DaemonNotRunningError, NoBrowserClientError
from .models import PageList, PageSnapshot, StepResult

_DEFAULT_URL = "http://127.0.0.1:3200"


class CDMSAgent:
    """Python client for the CDM Agent daemon.

    Wraps the daemon's HTTP API so CDMS browser sessions can be driven from
    Jupyter notebooks or plain Python scripts without touching the runner code
    directly.

    Parameters
    ----------
    base_url:
        Base URL of the running daemon (default ``http://127.0.0.1:3200``).
    study_id:
        Optional study identifier forwarded with every request so the daemon
        can persist session state and link executions to the correct study.
    timeout:
        HTTP request timeout in seconds (default 30).  ``run_case`` calls use
        ``run_timeout`` instead, which defaults to 120 s.
    run_timeout:
        Timeout for ``run_case``-based calls (``set_date``, ``click_save_next``).
        These block until the browser step completes.
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
        runner: str = "extension",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.study_id = study_id
        self.timeout = timeout
        self.run_timeout = run_timeout
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
        anchor_label: str | None = None,
        row_label_occurrence: int | None = None,
        probe_only: bool = False,
        client_id: str | None = None,
    ) -> StepResult:
        """Select a radio button option."""
        step: dict[str, Any] = {"action": "selectRadio", "rowLabel": row_label, "optionLabel": option_label}
        if anchor_label:
            step["anchorLabel"] = anchor_label
        if row_label_occurrence:
            step["rowLabelOccurrence"] = row_label_occurrence
        if probe_only:
            step["probeOnly"] = True
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": f"Select radio: {row_label} = {option_label}",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [step],
            "expected": {},
        }
        return self._run_case(case, client_id=client_id)

    def probe_radio(
        self,
        row_label: str,
        option_label: str,
        *,
        page_id: str | None = None,
        visit_id: str | None = None,
        anchor_label: str | None = None,
        row_label_occurrence: int | None = None,
        client_id: str | None = None,
    ) -> StepResult:
        """Try selecting a radio-like option and report whether it became checked."""
        step: dict[str, Any] = {"action": "probeRadio", "rowLabel": row_label, "optionLabel": option_label}
        if anchor_label:
            step["anchorLabel"] = anchor_label
        if row_label_occurrence:
            step["rowLabelOccurrence"] = row_label_occurrence
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": f"Probe radio: {row_label} = {option_label}",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [step],
            "expected": {},
        }
        return self._run_case(case, client_id=client_id)

    def click_save(
        self,
        *,
        client_id: str | None = None,
        page_id: str | None = None,
        visit_id: str | None = None,
    ) -> StepResult:
        """Click the Save button (pages that have Save only, not Save & Next)."""
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": "Click Save",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [{"action": "clickSave"}],
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

    def go_to_page(
        self,
        segment: str,
        *,
        client_id: str | None = None,
    ) -> StepResult:
        """Navigate to a CRF page using a URL segment, staying on the same subject.

        Reads the current pathname from an ``inspect()`` snapshot and replaces
        only the segments you specify — no full URL needed.

        Parameters
        ----------
        segment:
            ``"DM"``        → change page only  (same visit)
            ``"V2/DM"``     → change visit + page
            ``"V2/DM/2"``   → change visit + page + page instance

        Examples
        --------
        >>> agent.go_to_page("DM")      # → .../NV/V1/1/DM/1
        >>> agent.go_to_page("V2/DM")   # → .../NV/V2/1/DM/1
        >>> agent.go_to_page("VS")      # → .../NV/V1/1/VS/1
        """
        snap = self.inspect(client_id=client_id)
        if not snap.pathname:
            raise CDMAgentError("Cannot resolve current pathname from snapshot.")

        # Pathname: /s/{study}/subjects/{subject}/NV/{visitId}/{visitNum}/{pageId}/{pageNum}
        # indices:   0  1       2         3         4   5         6         7        8  (after split)
        parts = snap.pathname.rstrip("/").split("/")
        tokens = segment.strip("/").split("/")

        if len(parts) >= 9 and parts[-5] == "EN":
            parts[-5] = "NV"

        if len(tokens) == 1:
            # "DM" → replace pageId, reset pageNum to 1
            parts[-2], parts[-1] = tokens[0], "1"
        elif len(tokens) == 2:
            # "V2/DM" → replace visitId + pageId, reset both instance nums to 1
            parts[-4], parts[-3] = tokens[0], "1"
            parts[-2], parts[-1] = tokens[1], "1"
        else:
            # "V2/DM/2" → replace visitId + pageId + pageNum
            parts[-4], parts[-3] = tokens[0], "1"
            parts[-2], parts[-1] = tokens[1], tokens[2]

        return self.navigate_to("/".join(parts), client_id=client_id)

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

    def wait_query(
        self,
        labels: list[str] | tuple[str, ...] | None = None,
        *,
        timeout_ms: int = 3000,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait in the browser extension until matching Query messages appear.

        This uses an extension-side MutationObserver instead of repeated Python
        inspect polling. If no matching query appears before ``timeout_ms``, the
        daemon returns ``{"outcome": "no_query_observed"}``.
        """
        body: dict[str, Any] = {
            "labels": list(labels or []),
            "timeout_ms": timeout_ms,
        }
        if client_id:
            body["client_id"] = client_id
        return self._post("/api/cdm-agent/wait-query", body, timeout=max(self.timeout, int(timeout_ms / 1000) + 5))

    def clear_query(
        self,
        label: str,
        *,
        action: str = "cancel",
        client_id: str | None = None,
        page_id: str | None = None,
        visit_id: str | None = None,
    ) -> StepResult:
        """Click a visible action on the Query row matching *label*.

        The default action is ``cancel`` because Rule Discovery uses this only
        to remove stale query rows before the next candidate observation.
        """
        case = {
            "id": f"py:{uuid.uuid4()}",
            "studyId": self.study_id or "unknown",
            "source": "python_client",
            "kind": "status_expected",
            "title": f"Clear query {label}",
            "pageId": page_id,
            "visitId": visit_id,
            "preconditions": [],
            "steps": [{"action": "clickQueryAction", "queryLabel": label, "queryAction": action}],
            "expected": {},
        }
        return self._run_case(case, client_id=client_id)

    def list_pages(self, *, client_id: str | None = None) -> "PageList":
        """Return the CRF pages available in the current visit sidebar.

        Displays as a table in Jupyter. Use pageId values with ``go_to_page()``.

        Example
        -------
        >>> agent.list_pages()          # shows table in Jupyter
        >>> agent.go_to_page("DM")      # navigate using pageId
        """
        params: dict[str, str] = {}
        if client_id:
            params["clientId"] = client_id
        data = self._get("/api/cdm-agent/nav-pages", params=params)
        return PageList(data.get("pages") or [])

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
        return f"CDMSAgent(base_url={self.base_url!r}, study_id={self.study_id!r}, runner={self.runner!r})"


# Backward-compatible alias for notebooks/scripts created before the rename.
CDMAgent = CDMSAgent


def _raise_for_status(resp: requests.Response, path: str) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json()
    except Exception:
        detail = resp.text
    raise CDMAgentError(f"Daemon returned HTTP {resp.status_code} for {path}: {detail}")
