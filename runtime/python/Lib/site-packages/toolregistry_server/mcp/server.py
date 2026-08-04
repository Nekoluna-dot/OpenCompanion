"""MCP server runner functions.

This module provides functions to run an MCP server with different transports:
- stdio: Standard input/output transport
- SSE: Server-Sent Events over HTTP
- streamable-http: Streamable HTTP transport

The server should be created using route_table_to_mcp_server() from adapter.py,
then run using the functions in this module.

Example:
    ```python
    from toolregistry import ToolRegistry
    from toolregistry_server import RouteTable
    from toolregistry_server.mcp import route_table_to_mcp_server, run_stdio

    registry = ToolRegistry()
    route_table = RouteTable(registry)
    server = route_table_to_mcp_server(route_table)
    asyncio.run(run_stdio(server))
    ```
"""

import asyncio
from typing import TYPE_CHECKING

from .._structlog import get_logger

logger = get_logger()

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server


async def run_stdio(server: "Server") -> None:
    """Run an MCP server over stdio transport.

    This is the simplest transport, suitable for local tool execution
    where the MCP client spawns the server as a subprocess.

    Args:
        server: The MCP Server instance to run.
    """
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as e:
        raise ImportError(
            "MCP SDK is required for MCP support. "
            "Install with: pip install toolregistry-server[mcp]"
        ) from e

    logger.info("Starting MCP server with stdio transport")
    try:
        async with stdio_server() as (read, write):
            await server.run(
                read,
                write,
                server.create_initialization_options(),
            )
    except KeyboardInterrupt:
        logger.info("MCP stdio server shutdown requested (KeyboardInterrupt)")
    except asyncio.CancelledError:
        logger.info("MCP stdio server shutdown requested (CancelledError)")


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
    try:
        import uvicorn
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Mount, Route
    except ImportError as e:
        raise ImportError(
            "MCP SDK and Starlette are required for SSE transport. "
            "Install with: pip install toolregistry-server[mcp] starlette uvicorn"
        ) from e

    logger.info(f"Starting MCP server with SSE transport on {host}:{port}{path}")

    # Create SSE transport
    sse = SseServerTransport(f"{path}/messages/")

    # SSE endpoint handler - must accept Request and return Response
    # See MCP SDK documentation for the correct pattern
    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
        # Return empty response to avoid NoneType error when client disconnects
        return Response()

    # Create Starlette app
    routes = [
        Route(path, endpoint=handle_sse, methods=["GET"]),
        Mount(f"{path}/messages/", app=sse.handle_post_message),
    ]
    app = Starlette(routes=routes)

    # Run with uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)

    try:
        await uvicorn_server.serve()
    except KeyboardInterrupt:
        logger.info("MCP SSE server shutdown requested (KeyboardInterrupt)")
    except asyncio.CancelledError:
        logger.info("MCP SSE server shutdown requested (CancelledError)")


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
    try:
        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.types import Receive, Scope, Send
    except ImportError as e:
        raise ImportError(
            "MCP SDK and Starlette are required for streamable HTTP transport. "
            "Install with: pip install toolregistry-server[mcp] starlette uvicorn"
        ) from e

    logger.info(
        f"Starting MCP server with streamable HTTP transport on {host}:{port}{path}"
    )

    # Create session manager
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,
    )

    # Create ASGI application class for StreamableHTTP
    # This is necessary because Starlette Route treats ASGI apps differently
    # from regular endpoint functions - ASGI apps receive all HTTP methods
    class StreamableHTTPASGIApp:
        """ASGI application wrapper for StreamableHTTP session manager."""

        def __init__(self, manager: StreamableHTTPSessionManager):
            self.manager = manager

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            await self.manager.handle_request(scope, receive, send)

    streamable_http_app = StreamableHTTPASGIApp(session_manager)

    # Create Starlette app with lifespan
    routes = [Route(path, endpoint=streamable_http_app)]
    app = Starlette(
        routes=routes,
        lifespan=lambda app: session_manager.run(),
    )

    # Run with uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)

    try:
        await uvicorn_server.serve()
    except KeyboardInterrupt:
        logger.info("MCP streamable HTTP server shutdown requested (KeyboardInterrupt)")
    except asyncio.CancelledError:
        logger.info("MCP streamable HTTP server shutdown requested (CancelledError)")
