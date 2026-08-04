"""
MCP server startup module.

This module provides functions to start an MCP server from the CLI.
"""

import asyncio
import sys
from typing import TYPE_CHECKING

from .._structlog import get_logger

logger = get_logger()

if TYPE_CHECKING:
    from toolregistry import ToolRegistry


def create_registry_from_config(config: dict | None) -> "ToolRegistry":
    """Create a ToolRegistry from configuration.

    Args:
        config: Configuration dictionary, or None for empty registry.

    Returns:
        Configured ToolRegistry instance.
    """
    # Import the shared implementation from openapi module
    from .openapi import create_registry_from_config as _create_registry

    return _create_registry(config)


def load_config(config_path: str | None) -> dict | None:
    """Load configuration from a JSON/JSONC file.

    Args:
        config_path: Path to the configuration file, or None.

    Returns:
        Parsed configuration dictionary, or None if no config specified.
    """
    # Import the shared implementation from openapi module
    from .openapi import load_config as _load_config

    return _load_config(config_path)


def run_mcp_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    config_path: str | None = None,
) -> None:
    """Start the MCP server.

    Args:
        transport: Transport type: stdio, sse, or streamable-http.
        host: Host for SSE/HTTP transport.
        port: Port for SSE/HTTP transport.
        config_path: Path to configuration file.
    """
    try:
        from toolregistry_server import RouteTable
        from toolregistry_server.mcp import route_table_to_mcp_server
        from toolregistry_server.mcp.server import (
            run_sse,
            run_stdio,
            run_streamable_http,
        )
    except ImportError as e:
        logger.error(f"MCP server dependencies not installed: {e}")
        logger.info("Install with: pip install toolregistry-server[mcp]")
        sys.exit(1)

    # Load configuration
    config = load_config(config_path)

    # Create registry from config
    registry = create_registry_from_config(config)

    # Create route table
    route_table = RouteTable(registry)

    # Create MCP server
    mcp_server = route_table_to_mcp_server(route_table)

    # Log startup info
    logger.info(f"Starting MCP server with {transport} transport")
    logger.info(f"Registered {len(route_table.list_routes())} tool(s)")

    # Run the appropriate transport
    if transport == "stdio":
        asyncio.run(run_stdio(mcp_server))
    elif transport == "sse":
        logger.info(f"SSE endpoint: http://{host}:{port}/sse")
        asyncio.run(run_sse(mcp_server, host=host, port=port))
    elif transport == "streamable-http":
        logger.info(f"HTTP endpoint: http://{host}:{port}/mcp")
        asyncio.run(run_streamable_http(mcp_server, host=host, port=port))
    else:
        logger.error(f"Unknown transport type: {transport}")
        sys.exit(1)
