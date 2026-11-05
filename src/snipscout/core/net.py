"""Network policy. With ``SNIPSCOUT_OFFLINE=1`` every non-loopback connection fails with ``OfflineError``.

``enforce_offline_if_requested()`` is called by every entry point (CLI, server). It patches the
socket layer process-wide, so third-party libraries (huggingface_hub, httpx, urllib) are covered too.
Loopback stays allowed because the UI talks to the local server on 127.0.0.1.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from typing import Any

from snipscout.config import is_offline
from snipscout.core.errors import OfflineError

_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_installed = False


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _blocked(host: object) -> OfflineError:
    return OfflineError(
        "Network access is disabled (SNIPSCOUT_OFFLINE=1).", details=f"blocked connection to {host!r}"
    )


def _guard_connect(original: Callable[..., Any]) -> Callable[..., Any]:
    def connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else address
            if not _is_loopback(host):
                raise _blocked(host)
        return original(self, address)

    return connect


def _guard_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if host is not None and not _is_loopback(host if isinstance(host, str) else str(host)):
        raise _blocked(host)
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def install_offline_guard() -> None:
    global _installed
    if _installed:
        return
    socket.socket.connect = _guard_connect(_ORIGINAL_CONNECT)  # type: ignore[method-assign]
    socket.socket.connect_ex = _guard_connect(_ORIGINAL_CONNECT_EX)  # type: ignore[method-assign]
    socket.getaddrinfo = _guard_getaddrinfo
    # Libraries with their own offline switches: make them fail fast and locally.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    _installed = True


def uninstall_offline_guard() -> None:
    """For tests only."""
    global _installed
    socket.socket.connect = _ORIGINAL_CONNECT  # type: ignore[method-assign]
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX  # type: ignore[method-assign]
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO
    _installed = False


def enforce_offline_if_requested() -> bool:
    if is_offline():
        install_offline_guard()
        return True
    return False


def require_network(purpose: str) -> None:
    """Call before any intentional download so the user gets a clear error instead of a socket error."""
    if is_offline():
        raise OfflineError(f"Network access is disabled (SNIPSCOUT_OFFLINE=1); cannot {purpose}.")
