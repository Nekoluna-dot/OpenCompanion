"""
toolregistry-server: Define custom tools and serve them via OpenAPI or MCP.

This package lets you register Python functions as tools and expose them
as services via OpenAPI (REST) and MCP (Model Context Protocol) interfaces.

Main Components:
    - RouteTable: Central routing layer that bridges ToolRegistry and protocol adapters
    - openapi: OpenAPI/REST adapter using FastAPI
    - mcp: MCP adapter for LLM integration
    - auth: Authentication utilities
    - cli: Command-line interface

Example:
    ```python
    from toolregistry import ToolRegistry
    from toolregistry_server import RouteTable

    registry = ToolRegistry()
    route_table = RouteTable(registry)
    for route in route_table.list_routes():
        print(route.path)
    ```
"""

__version__ = "0.1.3"

from .route_table import RouteEntry, RouteTable
from .session import SessionContext

__all__ = [
    "__version__",
    "RouteEntry",
    "RouteTable",
    "SessionContext",
]
