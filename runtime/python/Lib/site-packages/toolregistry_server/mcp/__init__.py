"""
MCP (Model Context Protocol) adapter for ToolRegistry.

This module provides functionality to expose ToolRegistry tools via
the Model Context Protocol for LLM integration.

Main Components:
    - route_table_to_mcp_server: Convert a RouteTable to an MCP low-level server
    - create_mcp_server: Alias for route_table_to_mcp_server
    - run_stdio: Run MCP server over stdio transport
    - run_sse: Run MCP server over SSE transport
    - run_streamable_http: Run MCP server over streamable HTTP transport

Example:
    ```python
    import asyncio
    from toolregistry import ToolRegistry
    from toolregistry_server import RouteTable
    from toolregistry_server.mcp import create_mcp_server, run_stdio

    registry = ToolRegistry()
    route_table = RouteTable(registry)
    server = create_mcp_server(route_table)
    asyncio.run(run_stdio(server))
    ```

Note:
    This module requires the 'mcp' extra to be installed:
    pip install toolregistry-server[mcp]
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server

    from ..route_table import RouteTable


def create_mcp_server(
    route_table: "RouteTable",
    name: str = "ToolRegistry-Server",
) -> "Server":
    """Create an MCP server from a RouteTable.

    This is an alias for route_table_to_mcp_server() for convenience.

    Args:
        route_table: The RouteTable to expose.
        name: Server name for MCP identification.

    Returns:
        A configured MCP Server instance.

    Raises:
        ImportError: If MCP SDK is not installed.
    """
    from .adapter import route_table_to_mcp_server

    return route_table_to_mcp_server(route_table, name)


def route_table_to_mcp_server(
    route_table: "RouteTable",
    name: str = "ToolRegistry-Server",
) -> "Server":
    """Create an MCP low-level server from a RouteTable.

    Registers list_tools and call_tool handlers that read directly
    from the route table, ensuring enable/disable state is always
    in sync (no drift).

    Args:
        route_table: The RouteTable to convert.
        name: Server name for MCP identification.

    Returns:
        A configured MCP Server instance.

    Raises:
        ImportError: If MCP SDK is not installed.
    """
    from .adapter import route_table_to_mcp_server as _route_table_to_mcp_server

    return _route_table_to_mcp_server(route_table, name)


async def run_stdio(server: "Server") -> None:
    """Run an MCP server over stdio transport.

    This is the simplest transport, suitable for local tool execution
    where the MCP client spawns the server as a subprocess.

    Args:
        server: The MCP Server instance to run.
    """
    from .server import run_stdio as _run_stdio

    await _run_stdio(server)


async def run_sse(
    server: "Server",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/sse",
) -> None:
    """Run an MCP server over SSE (Server-Sent Events) transport.

    This transport is suitable for web-based MCP clients that connect
    via HTTP and receive events through SSE.

    Args:
        server: The MCP Server instance to run.
        host: Host address to bind to.
        port: Port number to bind to.
        path: URL path for the SSE endpoint.
    """
    from .server import run_sse as _run_sse

    await _run_sse(server, host, port, path)


async def run_streamable_http(
    server: "Server",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
) -> None:
    """Run an MCP server over streamable HTTP transport.

    This is the recommended HTTP transport for production use,
    supporting bidirectional streaming over HTTP.

    Args:
        server: The MCP Server instance to run.
        host: Host address to bind to.
        port: Port number to bind to.
        path: URL path for the MCP endpoint.
    """
    from .server import run_streamable_http as _run_streamable_http

    await _run_streamable_http(server, host, port, path)


__all__ = [
    "create_mcp_server",
    "route_table_to_mcp_server",
    "run_stdio",
    "run_sse",
    "run_streamable_http",
]
