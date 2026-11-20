"""Process-wide dependency-injection registry for cBioPortal service.

The running server registers a concrete :class:`CbioService` at startup; tests inject
one over a respx-mocked client. An unregistered service is an ``internal`` error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cbioportal_link.exceptions import InternalError

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from cbioportal_link.service import CbioService

_service: CbioService | None = None


def get_cbio_service() -> CbioService:
    """Return the registered :class:`CbioService` or raise ``InternalError``."""
    if _service is None:
        raise InternalError(
            "cBioPortal service is not initialised; the server must register it at startup.",
            recovery_action="switch_tool",
        )
    return _service


def set_cbio_service(service: CbioService | None) -> None:
    """Register (or clear) the process-wide service. Used by the server and tests."""
    global _service
    _service = service
