from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PageSnapshot:
    """Current state of the active CDMS browser page."""

    connected: bool
    client_id: str | None = None
    url: str | None = None
    pathname: str | None = None
    page_label: str | None = None
    raw_page_label: str | None = None
    page_status: dict[str, Any] = field(default_factory=dict)
    visible_rows: list[str] = field(default_factory=list)
    structured_rows: list[dict[str, Any]] = field(default_factory=list)
    enabled_actions: list[str] = field(default_factory=list)
    invalid_row_labels: list[str] = field(default_factory=list)
    invalid_count: int = 0
    query_rows: list[str] = field(default_factory=list)
    query_count: int = 0
    timestamp: str | None = None
    error: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "PageSnapshot":
        snap = data.get("snapshot") or {}
        return cls(
            connected=bool(data.get("connected")),
            client_id=data.get("clientId"),
            url=snap.get("url"),
            pathname=snap.get("pathname"),
            page_label=snap.get("pageLabel"),
            raw_page_label=snap.get("rawPageLabel"),
            page_status=snap.get("pageStatus") or {},
            visible_rows=snap.get("visibleRows") or [],
            structured_rows=snap.get("structuredRows") or [],
            enabled_actions=snap.get("enabledActions") or [],
            invalid_row_labels=snap.get("invalidRowLabels") or [],
            invalid_count=snap.get("invalidCount") or 0,
            query_rows=snap.get("queryRows") or [],
            query_count=snap.get("queryCount") or len(snap.get("queryRows") or []),
            timestamp=snap.get("timestamp"),
            error=snap.get("error"),
        )

    # ------------------------------------------------------------------
    # Jupyter / IPython rich display
    # ------------------------------------------------------------------

    def _repr_html_(self) -> str:
        status_color = "#2ecc71" if self.connected else "#e74c3c"
        status_label = "Connected" if self.connected else "Disconnected"

        rows_html = "".join(f"<li>{r}</li>" for r in self.visible_rows) or "<li><em>(none)</em></li>"
        structured_html = (
            "".join(
                f"<li>{r.get('rowLabel', '')} "
                f"({'editable' if r.get('editable') else 'disabled' if r.get('disabled') else 'read-only'})</li>"
                for r in self.structured_rows[:20]
            )
            or "<li><em>(none)</em></li>"
        )
        actions_html = "".join(f"<li>{a}</li>" for a in self.enabled_actions) or "<li><em>(none)</em></li>"
        query_html = (
            "".join(f"<li style='color:#e74c3c'>{r}</li>" for r in (self.query_rows or self.invalid_row_labels))
            or "<li><em>(none)</em></li>"
        )

        error_section = (
            f"<tr><td><b>Error</b></td><td style='color:#e74c3c'>{self.error}</td></tr>"
            if self.error
            else ""
        )

        return f"""
        <div style="font-family:sans-serif;border:1px solid #ddd;border-radius:6px;padding:12px;max-width:640px">
          <h3 style="margin:0 0 8px">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                         background:{status_color};margin-right:6px"></span>
            CDM Agent — Page Snapshot
          </h3>
          <table style="border-collapse:collapse;width:100%">
            <tr><td style="width:140px"><b>Status</b></td>
                <td style="color:{status_color}">{status_label}</td></tr>
            <tr><td><b>Client ID</b></td><td>{self.client_id or "—"}</td></tr>
            <tr><td><b>Page</b></td><td>{self.page_label or "—"}</td></tr>
            <tr><td><b>Raw page</b></td><td>{self.raw_page_label or "—"}</td></tr>
            <tr><td><b>URL</b></td><td style="word-break:break-all">{self.url or "—"}</td></tr>
            <tr><td><b>Page status</b></td><td>{self.page_status or "—"}</td></tr>
            <tr><td><b>Query count</b></td><td>{self.query_count}</td></tr>
            <tr><td><b>Invalid rows</b></td><td>{self.invalid_count}</td></tr>
            {error_section}
          </table>
          <div style="display:flex;gap:24px;margin-top:10px">
            <div style="flex:1">
              <b>Visible rows</b>
              <ul style="margin:4px 0;padding-left:18px">{rows_html}</ul>
            </div>
            <div style="flex:1">
              <b>Structured rows</b>
              <ul style="margin:4px 0;padding-left:18px">{structured_html}</ul>
            </div>
            <div style="flex:1">
              <b>Enabled actions</b>
              <ul style="margin:4px 0;padding-left:18px">{actions_html}</ul>
            </div>
            <div style="flex:1">
              <b>Query rows</b>
              <ul style="margin:4px 0;padding-left:18px">{query_html}</ul>
            </div>
          </div>
          <p style="color:#999;font-size:11px;margin:8px 0 0">{self.timestamp or ""}</p>
        </div>
        """

    def __repr__(self) -> str:
        return (
            f"PageSnapshot(connected={self.connected}, page_label={self.page_label!r}, "
            f"visible_rows={len(self.visible_rows)}, structured_rows={len(self.structured_rows)}, "
            f"invalid_count={self.invalid_count})"
        )


@dataclass
class PageList:
    """List of CRF pages from the sidebar, displayed as a table in Jupyter."""

    pages: list[dict]

    def _repr_html_(self) -> str:
        if not self.pages:
            return "<p><em>No pages found. Make sure you are on a CRF page.</em></p>"
        rows = "".join(
            f"<tr><td style='padding:4px 12px;font-weight:bold'>{p.get('pageId','')}</td>"
            f"<td style='padding:4px 12px'>{p.get('label','')}</td></tr>"
            for p in self.pages
        )
        return (
            "<table style='border-collapse:collapse;font-family:sans-serif'>"
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:4px 12px;text-align:left'>pageId</th>"
            "<th style='padding:4px 12px;text-align:left'>Label</th>"
            "</tr>"
            f"{rows}</table>"
        )

    def __repr__(self) -> str:
        return "\n".join(f"{p.get('pageId'):10} {p.get('label','')}" for p in self.pages)

    def __iter__(self):
        return iter(self.pages)

    def __len__(self):
        return len(self.pages)


@dataclass
class StepResult:
    """Result from a single browser step (run_case execution)."""

    outcome: str          # "passed" | "failed" | "blocked" | "skipped"
    run_id: str | None = None
    case_id: str | None = None
    page_before: str | None = None
    page_after: str | None = None
    failure_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "StepResult":
        return cls(
            outcome=data.get("outcome", "unknown"),
            run_id=data.get("runId"),
            case_id=data.get("caseId"),
            page_before=data.get("pageBefore"),
            page_after=data.get("pageAfter"),
            failure_reason=data.get("failureReason"),
            started_at=data.get("startedAt"),
            finished_at=data.get("finishedAt"),
            raw=data,
        )

    @property
    def ok(self) -> bool:
        return self.outcome in ("passed", "blocked")

    def _repr_html_(self) -> str:
        color = "#2ecc71" if self.ok else "#e74c3c"
        icon = "✓" if self.ok else "✗"
        reason = (
            f"<tr><td><b>Reason</b></td><td style='color:#e74c3c'>{self.failure_reason}</td></tr>"
            if self.failure_reason
            else ""
        )
        return f"""
        <div style="font-family:sans-serif;border:1px solid #ddd;border-radius:6px;padding:12px;max-width:640px">
          <h3 style="margin:0 0 8px">
            <span style="color:{color}">{icon}</span> Step Result — <span style="color:{color}">{self.outcome.upper()}</span>
          </h3>
          <table style="border-collapse:collapse;width:100%">
            <tr><td style="width:140px"><b>Run ID</b></td><td>{self.run_id or "—"}</td></tr>
            <tr><td><b>Case ID</b></td><td>{self.case_id or "—"}</td></tr>
            <tr><td><b>Page before</b></td><td>{self.page_before or "—"}</td></tr>
            <tr><td><b>Page after</b></td><td>{self.page_after or "—"}</td></tr>
            {reason}
            <tr><td><b>Started</b></td><td>{self.started_at or "—"}</td></tr>
            <tr><td><b>Finished</b></td><td>{self.finished_at or "—"}</td></tr>
          </table>
        </div>
        """

    def __repr__(self) -> str:
        return f"StepResult(outcome={self.outcome!r}, run_id={self.run_id!r}, page_after={self.page_after!r})"
