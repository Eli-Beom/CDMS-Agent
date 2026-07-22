"""cdm-agent-client — control a CDMS browser session from Python or Jupyter."""

from .client import CDMAgent, CDMSAgent
from .exceptions import CDMAgentError, DaemonNotRunningError, NoBrowserClientError, StepFailedError
from .models import PageSnapshot, StepResult

__all__ = [
    # Main client
    "CDMSAgent",
    "CDMAgent",
    # Models
    "PageSnapshot",
    "StepResult",
    # Exceptions
    "CDMAgentError",
    "DaemonNotRunningError",
    "NoBrowserClientError",
    "StepFailedError",
]
