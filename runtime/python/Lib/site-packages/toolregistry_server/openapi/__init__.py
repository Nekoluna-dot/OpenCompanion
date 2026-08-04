"""
OpenAPI adapter for ToolRegistry.

This module provides functionality to expose ToolRegistry tools as
RESTful HTTP endpoints using FastAPI.

Main Components:
    - create_openapi_app: Create a FastAPI application from a RouteTable
    - route_table_to_router: Convert a RouteTable to a FastAPI router
    - setup_dynamic_openapi: Configure dynamic OpenAPI schema generation
    - ETagMiddleware: Middleware for ETag-based cache validation
    - add_tools_endpoint: Add /tools endpoint for listing available tools

Example:
    ```python
    from toolregistry import ToolRegistry
    from toolregistry_server import RouteTable
    from toolregistry_server.openapi import create_openapi_app

    registry = ToolRegistry()
    route_table = RouteTable(registry)
    app = create_openapi_app(route_table)
    ```

Note:
    This module requires the 'openapi' extra to be installed:
    pip install toolregistry-server[openapi]
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import FastAPI

    from ..route_table import RouteTable


def create_openapi_app(
    route_table: "RouteTable",
    title: str = "ToolRegistry Server",
    version: str = "1.0.0",
    description: str = "OpenAPI server for ToolRegistry tools",
    dependencies: "Sequence[Any] | None" = None,
    enable_etag: bool = True,
) -> "FastAPI":
    """Create a FastAPI application from a RouteTable.

    Args:
        route_table: The RouteTable to expose.
        title: API title for OpenAPI schema.
        version: API version for OpenAPI schema.
        description: API description for OpenAPI schema.
        dependencies: Optional list of global dependencies (e.g., authentication).
        enable_etag: Whether to enable ETag middleware for cache validation.
            Defaults to True.

    Returns:
        A configured FastAPI application with:
        - Tool routes from the RouteTable
        - /tools endpoint for listing available tools
        - ETag middleware for cache validation (if enabled)
        - Dynamic OpenAPI schema that filters disabled tools

    Raises:
        ImportError: If FastAPI is not installed.
    """
    try:
        from fastapi import FastAPI
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for OpenAPI support. "
            "Install with: pip install toolregistry-server[openapi]"
        ) from e

    from .adapter import (
        add_tools_endpoint,
        route_table_to_router,
        setup_dynamic_openapi,
    )
    from .middleware import add_etag_middleware

    # Create app with optional global dependencies
    if dependencies:
        app = FastAPI(
            title=title,
            version=version,
            description=description,
            dependencies=list(dependencies),
        )
    else:
        app = FastAPI(
            title=title,
            version=version,
            description=description,
        )

    # Add ETag middleware for cache validation
    if enable_etag:
        add_etag_middleware(app, route_table)

    # Add /tools endpoint for listing available tools
    add_tools_endpoint(app, route_table)

    # Add routes from route table
    router = route_table_to_router(route_table)
    app.include_router(router)

    # Setup dynamic OpenAPI schema that filters disabled tools
    setup_dynamic_openapi(app, route_table)

    return app


__all__ = [
    "create_openapi_app",
]
