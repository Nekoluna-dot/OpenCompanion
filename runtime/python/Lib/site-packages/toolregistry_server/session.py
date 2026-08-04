"""Transport-agnostic session context for tool handlers.

Provides :class:`SessionContext` for per-session state,
:func:`should_inject_session` for opt-in parameter detection,
and :class:`SessionManager` for session lifecycle management.

Usage in tool handlers (opt-in via ``_session`` parameter)::

    from toolregistry_server import SessionContext

    def my_tool(x: int, _session: SessionContext) -> str:
        count = _session.get("call_count", 0) + 1
        _session.set("call_count", count)
        return f"Call #{count} in session {_session.session_id}"
"""

from __future__ import annotations

import contextvars
import inspect
import time
import uuid
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SessionContext",
    "SessionManager",
    "session_context_var",
    "should_inject_session",
]


# ---------------------------------------------------------------------------
# Session context
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Per-session state container injected into tool handlers.

    Args:
        session_id: Stable identifier for this session.
        transport: Transport type (``"stdio"``, ``"sse"``,
            ``"streamable-http"``, ``"openapi"``).
        created_at: Monotonic timestamp of session creation.
    """

    session_id: str
    transport: str
    created_at: float = field(default_factory=time.monotonic)
    _data: dict[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from session data.

        Args:
            key: The key to look up.
            default: Value to return if key is absent.

        Returns:
            The stored value, or *default*.
        """
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a value in session data.

        Args:
            key: The key to store under.
            value: The value to store.
        """
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data


# ---------------------------------------------------------------------------
# Context variable (secondary access for library code)
# ---------------------------------------------------------------------------

session_context_var: contextvars.ContextVar[SessionContext] = contextvars.ContextVar(
    "session_context"
)
"""Contextvar holding the current :class:`SessionContext`.

Set by the adapter before handler invocation, reset afterward.
Useful for library code that cannot use parameter injection.
"""


# ---------------------------------------------------------------------------
# Opt-in parameter detection
# ---------------------------------------------------------------------------


def should_inject_session(fn: Callable) -> bool:
    """Check if *fn* has a ``_session`` parameter for session injection.

    The parameter must be named ``_session``.  If a type annotation is
    present it must be (or contain the string) ``SessionContext``; an
    untyped ``_session`` parameter also matches.

    Args:
        fn: The callable to inspect.

    Returns:
        ``True`` if the function accepts a ``_session`` parameter
        compatible with :class:`SessionContext`.
    """
    try:
        sig = inspect.signature(fn)
        if "_session" not in sig.parameters:
            return False
        param = sig.parameters["_session"]
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            return True
        if annotation is SessionContext:
            return True
        return isinstance(annotation, str) and "SessionContext" in annotation
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages session lifecycle and per-session handler caching.

    Transport-agnostic: callers supply a *factory* to
    :meth:`get_or_create` that builds the :class:`SessionContext`.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, SessionContext] = {}
        self._session_handlers: dict[str, dict[str, Callable]] = {}
        self._finalizers: dict[int, weakref.finalize] = {}

    # -- session lifecycle ---------------------------------------------------

    def get_or_create(
        self,
        session_key: int,
        factory: Callable[[], SessionContext],
    ) -> SessionContext:
        """Return existing session or create one via *factory*.

        Args:
            session_key: Unique key identifying the session object
                (typically ``id(session_object)``).
            factory: Zero-argument callable that creates a new
                :class:`SessionContext` if one does not exist yet.

        Returns:
            The :class:`SessionContext` for *session_key*.
        """
        ctx = self._sessions.get(session_key)
        if ctx is not None:
            return ctx
        ctx = factory()
        self._sessions[session_key] = ctx
        return ctx

    def register_finalizer(self, session_obj: Any, session_key: int) -> None:
        """Register a weak-reference clean-up for *session_obj*.

        When the MCP SDK's ``ServerSession`` is garbage-collected the
        associated session data is automatically removed.

        Args:
            session_obj: The object whose lifetime bounds the session.
            session_key: The key used in :meth:`get_or_create`.
        """
        if session_key not in self._finalizers:
            self._finalizers[session_key] = weakref.finalize(
                session_obj,
                self._remove_session,
                session_key,
            )

    def remove_session(self, session_key: int) -> None:
        """Explicitly remove a session (public API).

        Args:
            session_key: The key used in :meth:`get_or_create`.
        """
        self._remove_session(session_key)

    def _remove_session(self, session_key: int) -> None:
        """Internal clean-up for a session."""
        ctx = self._sessions.pop(session_key, None)
        if ctx is not None:
            self._session_handlers.pop(ctx.session_id, None)
        self._finalizers.pop(session_key, None)

    # -- per-session handler caching -----------------------------------------

    def get_session_handler(
        self,
        session_id: str,
        route: Any,
    ) -> Callable:
        """Return a per-session handler, creating one if needed.

        If ``route.handler_factory`` is set, the factory is called once
        per session to produce a handler; subsequent calls return the
        cached result.  When no factory is set, ``route.handler`` is
        returned directly.

        Args:
            session_id: The session identifier.
            route: A :class:`~toolregistry_server.route_table.RouteEntry`.

        Returns:
            The handler callable.
        """
        if route.handler_factory is None:
            return route.handler

        handlers = self._session_handlers.setdefault(session_id, {})
        handler = handlers.get(route.tool_name)
        if handler is None:
            handler = route.handler_factory(self._sessions_by_id().get(session_id))
            handlers[route.tool_name] = handler
        return handler

    def _sessions_by_id(self) -> dict[str, SessionContext]:
        """Build a reverse index from session_id → SessionContext."""
        return {ctx.session_id: ctx for ctx in self._sessions.values()}

    # -- introspection -------------------------------------------------------

    @property
    def active_session_count(self) -> int:
        """Number of currently tracked sessions."""
        return len(self._sessions)

    @staticmethod
    def new_session_id() -> str:
        """Generate a new random session identifier."""
        return uuid.uuid4().hex
