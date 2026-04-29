class CDMAgentError(Exception):
    """Base exception for CDM Agent client errors."""


class DaemonNotRunningError(CDMAgentError):
    """Raised when the daemon cannot be reached at the configured URL."""

    def __init__(self, base_url: str) -> None:
        super().__init__(
            f"CDM Agent daemon is not reachable at {base_url}. "
            "Make sure 'npm run dev' is running in the cdm-agent-platform directory."
        )


class NoBrowserClientError(CDMAgentError):
    """Raised when no browser extension client is connected to the daemon."""

    def __init__(self) -> None:
        super().__init__(
            "No browser client is connected to the daemon. "
            "Install the CDM Agent Chrome extension and navigate to a CDMS page."
        )


class StepFailedError(CDMAgentError):
    """Raised when a browser step returns outcome 'failed' or 'blocked'."""

    def __init__(self, outcome: str, reason: str | None = None) -> None:
        self.outcome = outcome
        self.reason = reason
        msg = f"Step outcome: {outcome}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)
