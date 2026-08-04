"""
OpenAPI server startup module.

This module provides functions to start an OpenAPI server from the CLI.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .._structlog import get_logger

logger = get_logger()

if TYPE_CHECKING:
    from toolregistry import ToolRegistry


def load_config(config_path: str | None) -> dict | None:
    """Load configuration from a JSON/JSONC file.

    Args:
        config_path: Path to the configuration file, or None.

    Returns:
        Parsed configuration dictionary, or None if no config specified.

    Raises:
        SystemExit: If the config file cannot be loaded.
    """
    if config_path is None:
        return None

    path = Path(config_path)
    if not path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    try:
        import json

        content = path.read_text(encoding="utf-8")

        # Handle JSONC (JSON with comments) by stripping comments
        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            # Skip full-line comments
            if stripped.startswith("//"):
                continue
            # Remove inline comments (simple approach)
            if "//" in line:
                # Be careful not to remove // inside strings
                # This is a simple heuristic that works for most cases
                in_string = False
                result = []
                i = 0
                while i < len(line):
                    if line[i] == '"' and (i == 0 or line[i - 1] != "\\"):
                        in_string = not in_string
                    if not in_string and line[i : i + 2] == "//":
                        break
                    result.append(line[i])
                    i += 1
                lines.append("".join(result))
            else:
                lines.append(line)

        clean_content = "\n".join(lines)
        return json.loads(clean_content)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load configuration file: {e}")
        sys.exit(1)


def load_tokens(tokens_path: str | None) -> list[str]:
    """Load authentication tokens from a file.

    Args:
        tokens_path: Path to the tokens file, or None.

    Returns:
        List of tokens, or empty list if no file specified.

    Raises:
        SystemExit: If the tokens file cannot be loaded.
    """
    if tokens_path is None:
        return []

    path = Path(tokens_path)
    if not path.exists():
        logger.error(f"Tokens file not found: {tokens_path}")
        sys.exit(1)

    try:
        content = path.read_text(encoding="utf-8")
        tokens = []
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith("#"):
                tokens.append(line)
        return tokens
    except Exception as e:
        logger.error(f"Failed to load tokens file: {e}")
        sys.exit(1)


def _ns_matches(tool_namespace: str, pattern: str) -> bool:
    """Check if a tool namespace matches a config pattern.

    Supports exact match and prefix match for hierarchical namespaces.
    For example, pattern ``"web"`` matches ``"web/brave_search"``.

    Args:
        tool_namespace: The tool's namespace (e.g. ``"web/brave_search"``).
        pattern: The config pattern (e.g. ``"web"`` or ``"web/brave_search"``).

    Returns:
        True if the namespace matches the pattern.
    """
    return tool_namespace == pattern or tool_namespace.startswith(pattern + "/")


def _should_load_tool(
    namespace: str | None,
    mode: str,
    disabled_namespaces: list[str],
    enabled_namespaces: list[str],
) -> bool:
    """Determine if a tool should be loaded based on mode and namespace lists.

    Args:
        namespace: The tool's namespace, or None if not specified.
        mode: Either "denylist" or "allowlist".
        disabled_namespaces: List of namespaces to disable (denylist mode).
        enabled_namespaces: List of namespaces to enable (allowlist mode).

    Returns:
        True if the tool should be loaded, False otherwise.
    """
    if namespace is None:
        # Tools without namespace are always loaded
        return True

    if mode == "denylist":
        # In denylist mode, load unless namespace is in disabled list
        for pattern in disabled_namespaces:
            if _ns_matches(namespace, pattern):
                return False
        return True
    else:
        # In allowlist mode, only load if namespace is in enabled list
        return any(_ns_matches(namespace, pattern) for pattern in enabled_namespaces)


def create_registry_from_config(config: dict | None) -> "ToolRegistry":
    """Create a ToolRegistry from configuration.

    Supports two modes:
    - **denylist** (default): Load all tools except those with namespaces
      listed in the "disabled" array.
    - **allowlist**: Only load tools with namespaces listed in the "enabled"
      array.

    Args:
        config: Configuration dictionary, or None for empty registry.

    Returns:
        Configured ToolRegistry instance.
    """
    from toolregistry import ToolRegistry

    registry = ToolRegistry()

    if config is None:
        logger.info("No configuration provided, starting with empty registry")
        return registry

    # Parse mode and namespace lists
    mode = config.get("mode", "denylist")
    if mode not in ("denylist", "allowlist"):
        logger.warning(f"Invalid mode '{mode}', defaulting to 'denylist'")
        mode = "denylist"

    disabled_namespaces = config.get("disabled", [])
    enabled_namespaces = config.get("enabled", [])

    if not isinstance(disabled_namespaces, list):
        logger.warning("'disabled' must be a list, ignoring")
        disabled_namespaces = []

    if not isinstance(enabled_namespaces, list):
        logger.warning("'enabled' must be a list, ignoring")
        enabled_namespaces = []

    # Process tools from config
    tools = config.get("tools", [])
    loaded_count = 0
    skipped_count = 0

    for tool_config in tools:
        # Tool configuration format:
        # Option 1 - Full class path:
        # {
        #     "class": "module.path.ClassName",
        #     "enabled": true,       # optional, default true
        #     "namespace": "ns"      # optional
        # }
        # Option 2 - Separate module and class:
        # {
        #     "module": "module.path",
        #     "class": "ClassName",  # optional
        #     "enabled": true,       # optional, default true
        #     "namespace": "ns"      # optional
        # }
        module_path = tool_config.get("module")
        class_name = tool_config.get("class")
        per_tool_enabled = tool_config.get("enabled", True)
        namespace = tool_config.get("namespace")

        # Skip tools with enabled=false at the tool level
        if not per_tool_enabled:
            logger.info(f"Skipping disabled tool: {class_name or module_path}")
            skipped_count += 1
            continue

        # Check if namespace should be loaded based on mode
        if not _should_load_tool(
            namespace, mode, disabled_namespaces, enabled_namespaces
        ):
            reason = "in disabled list" if mode == "denylist" else "not in enabled list"
            logger.info(f"Config {mode}: skipping namespace '{namespace}' ({reason})")
            skipped_count += 1
            continue

        # Support full class path in "class" field (e.g., "module.path.ClassName")
        if not module_path and class_name and "." in class_name:
            # Split the full class path into module and class name
            parts = class_name.rsplit(".", 1)
            module_path = parts[0]
            class_name = parts[1]

        if not module_path:
            logger.warning(f"Skipping tool config without module: {tool_config}")
            continue

        try:
            import importlib

            module = importlib.import_module(module_path)

            if class_name:
                # Register a class
                cls = getattr(module, class_name)
                instance = cls()
                # register_from_class uses with_namespace parameter
                # If namespace is provided, use it; otherwise use False (no namespace)
                registry.register_from_class(
                    instance, with_namespace=namespace if namespace else False
                )
            else:
                # Register all public functions from module
                for name in dir(module):
                    if not name.startswith("_"):
                        obj = getattr(module, name)
                        if callable(obj) and not isinstance(obj, type):
                            # register uses namespace parameter
                            registry.register(obj, namespace=namespace)

            logger.info(f"Loaded tools from {module_path}")
            loaded_count += 1
        except Exception as e:
            logger.warning(f"Failed to load tools from {module_path}: {e}")

    logger.info(
        f"Applied tool config (mode={mode}): "
        f"loaded {loaded_count}, skipped {skipped_count}"
    )

    return registry


def run_openapi_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    config_path: str | None = None,
    tokens_path: str | None = None,
    reload: bool = False,
) -> None:
    """Start the OpenAPI server.

    Args:
        host: Host to bind the server to.
        port: Port to bind the server to.
        config_path: Path to configuration file.
        tokens_path: Path to tokens file.
        reload: Enable auto-reload for development.
    """
    try:
        import uvicorn
    except ImportError as e:
        logger.error(f"OpenAPI server dependencies not installed: {e}")
        logger.info("Install with: pip install toolregistry-server[openapi]")
        sys.exit(1)

    try:
        from toolregistry_server import RouteTable
        from toolregistry_server.openapi import create_openapi_app
    except ImportError as e:
        logger.error(f"Failed to import server components: {e}")
        sys.exit(1)

    # Load configuration
    config = load_config(config_path)

    # Create registry from config
    registry = create_registry_from_config(config)

    # Create route table
    route_table = RouteTable(registry)

    # Load tokens for authentication
    tokens = load_tokens(tokens_path)

    # Create dependencies for authentication if tokens are provided
    dependencies = None
    if tokens:
        try:
            from fastapi import Depends

            from toolregistry_server.auth import (
                BearerTokenAuth,
                create_bearer_dependency,
            )

            auth = BearerTokenAuth(tokens=tokens)
            dependencies = [Depends(create_bearer_dependency(auth))]
            logger.info(f"Authentication enabled with {len(tokens)} token(s)")
        except ImportError as e:
            logger.warning(f"Failed to setup authentication: {e}")

    # Create the FastAPI app
    app = create_openapi_app(
        route_table,
        title="ToolRegistry Server",
        version="1.0.0",
        description="OpenAPI server for ToolRegistry tools",
        dependencies=dependencies,
    )

    # Log startup info
    logger.info(f"Starting OpenAPI server on {host}:{port}")
    logger.info(f"Registered {len(route_table.list_routes())} tool(s)")

    # Run the server
    if reload:
        logger.warning("Reload mode is not fully supported with dynamic configuration")

    uvicorn.run(app, host=host, port=port, reload=reload)
