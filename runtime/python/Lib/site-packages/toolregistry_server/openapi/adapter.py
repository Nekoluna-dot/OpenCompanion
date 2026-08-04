"""Automatic route generation from a RouteTable.

Converts a :class:`~toolregistry_server.RouteTable` into a FastAPI
:class:`~fastapi.APIRouter` by introspecting each registered route
and dynamically creating Pydantic request models and route handlers.
"""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, create_model

from ..route_table import RouteEntry, RouteTable

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

# ---------------------------------------------------------------------------
# JSON Schema type → Python type mapping
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


# ---------------------------------------------------------------------------
# Helper: resolve a single field schema to a Python type
# ---------------------------------------------------------------------------


def _resolve_type(field_schema: dict[str, Any]) -> type:
    """Resolve a JSON Schema field description to a Python type.

    Handles basic types, ``array`` with ``items``, nested ``object`` with
    ``properties`` (recursively creates a Pydantic model), ``enum`` via
    ``Literal``, and falls back to ``Any`` for unknown schemas.

    Args:
        field_schema: A single-field JSON Schema dict (e.g.
            ``{"type": "string"}`` or ``{"type": "array", "items": {...}}``).

    Returns:
        The resolved Python type suitable for use in a Pydantic model field.
    """
    # Handle enum → Literal
    if "enum" in field_schema:
        from typing import Literal  # noqa: UP035 – needed at runtime

        values = tuple(field_schema["enum"])
        return Literal[values]  # ty: ignore[invalid-type-form]

    json_type = field_schema.get("type")

    if json_type == "array":
        items_schema = field_schema.get("items")
        if items_schema:
            inner = _resolve_type(items_schema)
            return list[inner]  # ty: ignore[invalid-type-form]
        return list

    if json_type == "object" and "properties" in field_schema:
        # Recursively build a nested Pydantic model
        return _schema_to_pydantic("NestedModel", field_schema)

    if json_type is not None:
        return _JSON_TYPE_MAP.get(json_type, Any)

    # anyOf / oneOf patterns (e.g. Optional fields from toolregistry)
    any_of = field_schema.get("anyOf") or field_schema.get("oneOf")
    if any_of:
        non_null = [s for s in any_of if s.get("type") != "null"]
        if len(non_null) == 1:
            return _resolve_type(non_null[0])

    return Any


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic model
# ---------------------------------------------------------------------------


def _schema_to_pydantic(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Convert a JSON Schema ``object`` definition into a dynamic Pydantic model.

    Args:
        name: The class name for the generated model.
        schema: A JSON Schema dict with ``properties`` (and optionally
            ``required``).

    Returns:
        A dynamically created :class:`pydantic.BaseModel` subclass whose
        fields mirror the schema properties.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    if not properties:
        # Return an empty model when there are no properties
        return create_model(name)

    required_fields: list[str] = schema.get("required", [])
    field_definitions: dict[str, tuple[type, Any]] = {}

    for field_name, field_schema in properties.items():
        py_type = _resolve_type(field_schema)
        description = field_schema.get("description")

        is_required = field_name in required_fields
        default_value = field_schema.get("default", ... if is_required else None)

        field_kwargs: dict[str, Any] = {}
        if description:
            field_kwargs["description"] = description

        if default_value is ...:
            field_definitions[field_name] = (py_type, Field(**field_kwargs))
        else:
            field_definitions[field_name] = (
                py_type,
                Field(default=default_value, **field_kwargs),
            )

    return create_model(name, **field_definitions)  # ty: ignore[no-matching-overload]


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------


def _coerce_arguments(raw: dict[str, Any], route: RouteEntry) -> dict[str, Any]:
    """Validate and coerce request arguments through the tool's parameters model.

    When a ``parameters_model`` is available on the route, the raw arguments
    are validated through it and dumped via ``model_dump_one_level()``.  This
    strips framework-injected fields (e.g. ``thought`` from think-augmented
    tool calling) that the handler does not accept, and coerces types
    (e.g. string ``"8"`` to int ``8``).

    Args:
        raw: The raw arguments from the request body.
        route: The RouteEntry for the tool being called.

    Returns:
        A dict of arguments suitable for passing to the handler.
    """
    if isinstance(route.parameters_model, type) and issubclass(
        route.parameters_model, BaseModel
    ):
        model = route.parameters_model(**raw)
        return model.model_dump_one_level()
    return raw


# ---------------------------------------------------------------------------
# Route generation
# ---------------------------------------------------------------------------


def _add_route_from_entry(
    router: "APIRouter",
    route: RouteEntry,
    route_table: RouteTable,
) -> None:
    """Create and register a POST route for a single RouteEntry.

    The route path is taken from the RouteEntry.path attribute.

    For async tools the handler is an ``async def``; for sync tools a plain
    ``def`` is used. A closure is used to correctly capture the loop
    variable.

    Each endpoint checks at request time whether the tool is still enabled
    via ``route_table.get_route()``. If the tool has been disabled at runtime,
    the endpoint returns HTTP 503 Service Unavailable.

    Args:
        router: The :class:`~fastapi.APIRouter` to add the route to.
        route: The :class:`~toolregistry_server.RouteEntry` to expose.
        route_table: The :class:`~toolregistry_server.RouteTable` used for
            runtime enable/disable checks.
    """
    from fastapi import HTTPException

    # Determine request model from parameters schema
    model_name = f"{route.tool_name.replace('-', '_').title().replace('_', '')}Request"
    request_model = _schema_to_pydantic(model_name, route.parameters_schema)

    summary = (route.description or "")[:120]
    # Use the top-level segment of the namespace as the tag for grouping
    # e.g. "web/brave_search" → tag "web", "calculator" → tag "calculator"
    namespace = route.namespace
    tags: list[str] = []
    if namespace:
        tags = [namespace.split("/")[0]]

    # Capture tool_name as a string to avoid closure-over-loop-variable issues.
    tool_name = route.tool_name
    handler = route.handler

    # Use factory functions to capture route, RequestModel, route_table, and
    # tool_name per iteration via closure.

    if route.is_async:

        def _make_async_endpoint(
            h: Any = handler,
            model: type[BaseModel] = request_model,
            rt: RouteTable = route_table,
            tname: str = tool_name,
        ):
            async def _endpoint(data: Any) -> Any:
                current_route = rt.get_route(tname)
                if current_route is None or not current_route.enabled:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Tool '{tname}' is currently disabled",
                    )
                arguments = _coerce_arguments(data.model_dump(), current_route)
                return await h(**arguments)

            # Patch annotations so FastAPI/Pydantic sees the concrete model
            _endpoint.__annotations__["data"] = model
            return _endpoint

        router.add_api_route(
            route.path,
            _make_async_endpoint(),
            methods=["POST"],
            operation_id=route.tool_name,
            summary=summary,
            tags=tags,  # ty: ignore[invalid-argument-type]
        )
    else:

        def _make_sync_endpoint(
            h: Any = handler,
            model: type[BaseModel] = request_model,
            rt: RouteTable = route_table,
            tname: str = tool_name,
        ):
            def _endpoint(data: Any) -> Any:
                current_route = rt.get_route(tname)
                if current_route is None or not current_route.enabled:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Tool '{tname}' is currently disabled",
                    )
                arguments = _coerce_arguments(data.model_dump(), current_route)
                return h(**arguments)

            # Patch annotations so FastAPI/Pydantic sees the concrete model
            _endpoint.__annotations__["data"] = model
            return _endpoint

        router.add_api_route(
            route.path,
            _make_sync_endpoint(),
            methods=["POST"],
            operation_id=route.tool_name,
            summary=summary,
            tags=tags,  # ty: ignore[invalid-argument-type]
        )


def route_table_to_router(
    route_table: RouteTable,
    prefix: str = "",
) -> "APIRouter":
    """Convert a :class:`~toolregistry_server.RouteTable` into a FastAPI router.

    Routes are generated for **all** registered tools regardless of their
    current enabled/disabled state. Each endpoint checks the route's enabled
    state at request time and returns HTTP 503 if the tool has been disabled,
    allowing runtime enable/disable without restarting the server.

    Args:
        route_table: The route table to convert.
        prefix: URL prefix for all generated routes.

    Returns:
        A :class:`~fastapi.APIRouter` with one POST route per registered tool.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    try:
        from fastapi import APIRouter
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for OpenAPI support. "
            "Install with: pip install toolregistry-server[openapi]"
        ) from e

    router = APIRouter(prefix=prefix)

    for route in route_table.list_routes(enabled_only=False):
        _add_route_from_entry(router, route, route_table)

    return router


# ---------------------------------------------------------------------------
# Tools list endpoint
# ---------------------------------------------------------------------------


def add_tools_endpoint(app: "FastAPI", route_table: RouteTable) -> None:
    """Add a /tools endpoint that returns the list of available tools.

    This endpoint supports ETag-based cache validation. The response includes
    the current ETag in both the response body and headers.

    Args:
        app: The FastAPI application instance.
        route_table: The RouteTable to query for tools.

    Example:
        ```python
        from fastapi import FastAPI
        from toolregistry_server import RouteTable
        from toolregistry_server.openapi.adapter import add_tools_endpoint

        app = FastAPI()
        route_table = RouteTable(registry)
        add_tools_endpoint(app, route_table)
        ```
    """
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for OpenAPI support. "
            "Install with: pip install toolregistry-server[openapi]"
        ) from e

    @app.get("/tools", tags=["meta"])
    async def list_tools(request: Request):
        """List all available tools with their metadata.

        Returns a JSON object containing:
        - tools: List of tool information (name, namespace, method, path, description)
        - etag: Current ETag for cache validation

        Supports conditional requests via If-None-Match header.
        Returns 304 Not Modified if the ETag matches.
        """
        # Check If-None-Match header
        if_none_match = request.headers.get("If-None-Match")
        current_etag = route_table.etag

        if if_none_match and if_none_match == current_etag:
            return JSONResponse(
                content=None,
                status_code=304,
                headers={"ETag": current_etag},
            )

        # Build tools list
        tools = []
        for route in route_table.list_routes(enabled_only=True):
            tools.append(
                {
                    "name": route.tool_name,
                    "namespace": route.namespace,
                    "method": route.method_name,
                    "path": route.path,
                    "description": route.description,
                }
            )

        return JSONResponse(
            content={"tools": tools, "etag": current_etag},
            headers={"ETag": current_etag},
        )


# ---------------------------------------------------------------------------
# Dynamic OpenAPI schema generation
# ---------------------------------------------------------------------------


def setup_dynamic_openapi(app: "FastAPI", route_table: RouteTable) -> None:
    """Configure dynamic OpenAPI schema generation that filters out disabled tools.

    This replaces FastAPI's default cached OpenAPI schema with a dynamic one
    that checks tool enable/disable status on every request to ``/openapi.json``.
    Disabled tools are excluded from the schema so they do not appear in
    ``/docs`` or ``/openapi.json``, and re-enabling them makes them visible
    again immediately.

    Args:
        app: The FastAPI application instance.
        route_table: The route table used for enable/disable status checks.
    """
    try:
        from fastapi.openapi.utils import get_openapi
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for OpenAPI support. "
            "Install with: pip install toolregistry-server[openapi]"
        ) from e

    def custom_openapi() -> dict[str, Any]:
        # Generate a fresh OpenAPI schema on every call (no caching)
        # so it always reflects the current enable/disable state.
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        # Collect operation_ids of disabled tools
        disabled_operation_ids: set[str] = set()
        for route in route_table.list_routes(enabled_only=False):
            if not route.enabled:
                disabled_operation_ids.add(route.tool_name)

        # Filter out paths whose operations correspond to disabled tools
        if disabled_operation_ids and "paths" in openapi_schema:
            filtered_paths: dict[str, Any] = {}
            for path, path_item in openapi_schema["paths"].items():
                filtered_methods: dict[str, Any] = {}
                for method, operation in path_item.items():
                    if isinstance(operation, dict):
                        op_id = operation.get("operationId", "")
                        if op_id not in disabled_operation_ids:
                            filtered_methods[method] = operation
                    else:
                        filtered_methods[method] = operation
                if filtered_methods:
                    filtered_paths[path] = filtered_methods
            openapi_schema["paths"] = filtered_paths

        # Do NOT cache (app.openapi_schema is not set) so the schema
        # is regenerated on every request, reflecting runtime changes.
        return openapi_schema

    app.openapi = custom_openapi  # ty: ignore[invalid-assignment]
