"""
Central Router Table for ToolRegistry.

This module provides the RouteTable class that bridges ToolRegistry and
protocol adapters (OpenAPI, MCP, etc.).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from toolregistry import ToolRegistry
from toolregistry.events import ChangeEvent, ChangeEventType
from toolregistry.tool import Tool


@dataclass
class RouteEntry:
    """A single route entry in the central router table.

    Attributes:
        tool_name: Full tool name (e.g., "calculator-evaluate")
        namespace: Tool namespace (e.g., "calculator")
        method_name: Method name within namespace (e.g., "evaluate")
        path: HTTP path for the route (e.g., "/tools/calculator/evaluate")
        description: Tool description
        parameters_schema: JSON Schema for tool parameters
        handler: The actual tool callable
        is_async: Whether the handler is async
        enabled: Whether the tool is currently enabled
        disable_reason: Reason for disabling, if disabled
    """

    # Tool identity
    tool_name: str
    namespace: str
    method_name: str

    # Route metadata
    path: str
    description: str
    parameters_schema: dict[str, Any]

    # Execution
    handler: Callable[..., Any]
    is_async: bool

    # Validation
    parameters_model: Any | None = None

    # Session-scoped handler factory (optional)
    handler_factory: Callable[..., Callable[..., Any]] | None = None

    # State
    enabled: bool = True
    disable_reason: str | None = None


@dataclass
class RouteTable:
    """Central router table that bridges ToolRegistry and protocol adapters.

    The RouteTable provides a unified view of all registered tools and their
    routing information. It supports:

    - Querying routes by name or listing all routes
    - Enabling/disabling tools dynamically
    - Observer pattern for change notifications
    - ETag generation for cache validation

    Example:
        ```python
        from toolregistry import ToolRegistry
        from toolregistry_server import RouteTable

        registry = ToolRegistry()

        @registry.register
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        route_table = RouteTable(registry)
        routes = route_table.list_routes()
        print(routes[0].path)
        # /tools/default/greet
        ```
    """

    _registry: ToolRegistry
    _routes: dict[str, RouteEntry] = field(default_factory=dict, init=False)
    _listeners: list[Callable[[str, str], None]] = field(
        default_factory=list, init=False
    )
    _version: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Initialize the route table from the registry."""
        self._rebuild()
        self._registry.on_change(self._on_registry_change)

    def _on_registry_change(self, event: ChangeEvent) -> None:
        """Handle change events from the underlying ToolRegistry.

        Keeps the RouteTable in sync when tools are enabled/disabled/registered
        externally (e.g. via the admin panel).  Handles both tool-level and
        namespace-level enable/disable events.
        """
        if event.event_type in (ChangeEventType.ENABLE, ChangeEventType.DISABLE):
            if event.tool_name:
                if event.tool_name in self._routes:
                    # Direct tool-level change
                    self.refresh(event.tool_name)
                    self._notify_listeners(event.tool_name, event.event_type.value)
                else:
                    # Namespace-level change — refresh all tools in that namespace
                    for route in self._routes.values():
                        if route.namespace == event.tool_name:
                            self.refresh(route.tool_name)
                    self._notify_listeners(event.tool_name, event.event_type.value)
        elif event.event_type in (
            ChangeEventType.REGISTER,
            ChangeEventType.UNREGISTER,
            ChangeEventType.REFRESH_ALL,
        ):
            self.refresh_all()

    def _rebuild(self) -> None:
        """Rebuild route table from registry."""
        self._routes.clear()
        for tool_name, tool in self._registry._tools.items():
            self._routes[tool_name] = self._tool_to_route(tool)

    def _tool_to_route(self, tool: Tool) -> RouteEntry:
        """Convert a Tool to a RouteEntry.

        Args:
            tool: The Tool instance to convert.

        Returns:
            A RouteEntry representing the tool.
        """
        namespace = getattr(tool, "namespace", None) or "default"
        method_name = getattr(tool, "method_name", None) or tool.name

        return RouteEntry(
            tool_name=tool.name,
            namespace=namespace,
            method_name=method_name,
            path=f"/tools/{namespace}/{method_name}",
            description=tool.description or "",
            parameters_schema=tool.parameters,
            handler=tool.callable,
            is_async=tool.is_async,
            parameters_model=getattr(tool, "parameters_model", None),
            enabled=self._registry.is_enabled(tool.name),
            disable_reason=self._registry.get_disable_reason(tool.name),
        )

    # ============== Query API ==============

    def list_routes(self, enabled_only: bool = True) -> list[RouteEntry]:
        """List all routes, optionally filtering by enabled state.

        Args:
            enabled_only: If True, only return enabled routes.

        Returns:
            List of RouteEntry objects.
        """
        if enabled_only:
            return [r for r in self._routes.values() if r.enabled]
        return list(self._routes.values())

    def get_route(self, tool_name: str) -> RouteEntry | None:
        """Get a specific route by tool name.

        Args:
            tool_name: The name of the tool.

        Returns:
            The RouteEntry if found, None otherwise.
        """
        return self._routes.get(tool_name)

    @property
    def etag(self) -> str:
        """Get ETag for cache validation.

        Returns:
            An ETag string based on the current version.
        """
        return f'"{self._version}"'

    @property
    def version(self) -> int:
        """Get the current version number.

        Returns:
            The version number, incremented on each change.
        """
        return self._version

    # ============== State Change API ==============

    def enable(self, tool_name: str) -> None:
        """Enable a tool.

        The route table is automatically refreshed via the registry change
        callback.

        Args:
            tool_name: The name of the tool to enable.

        Raises:
            KeyError: If the tool is not found.
        """
        self._registry.enable(tool_name)

    def disable(self, tool_name: str, reason: str = "") -> None:
        """Disable a tool.

        The route table is automatically refreshed via the registry change
        callback.

        Args:
            tool_name: The name of the tool to disable.
            reason: Optional reason for disabling.

        Raises:
            KeyError: If the tool is not found.
        """
        self._registry.disable(tool_name, reason)

    def refresh(self, tool_name: str) -> None:
        """Refresh a single route's state from registry.

        Args:
            tool_name: The name of the tool to refresh.
        """
        tool = self._registry.get_tool(tool_name)
        if tool:
            self._routes[tool_name] = self._tool_to_route(tool)

    def refresh_all(self) -> None:
        """Refresh all routes from registry."""
        self._rebuild()
        self._notify_listeners("*", "refresh_all")

    # ============== Observer Pattern ==============

    def add_listener(self, callback: Callable[[str, str], None]) -> None:
        """Add a listener for route changes.

        The callback will be invoked with (tool_name, event) whenever
        a route changes. Events include: "enable", "disable", "refresh",
        "refresh_all".

        Args:
            callback: Function to call on changes.
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, str], None]) -> None:
        """Remove a listener.

        Args:
            callback: The callback to remove.

        Raises:
            ValueError: If the callback is not found.
        """
        self._listeners.remove(callback)

    def _notify_listeners(self, tool_name: str, event: str) -> None:
        """Notify all listeners of a change.

        Args:
            tool_name: The tool that changed, or "*" for all.
            event: The type of event.
        """
        self._version += 1
        for listener in self._listeners:
            listener(tool_name, event)
