"""
Command-line interface for ToolRegistry Server.

This module provides the CLI entry point for running ToolRegistry servers
with support for both OpenAPI and MCP protocols.

Usage:
    toolregistry-server openapi [OPTIONS]
    toolregistry-server mcp [OPTIONS]
    toolregistry-server --help

Example:
    # Start OpenAPI server on port 8000
    $ toolregistry-server openapi --port 8000

    # Start MCP server with stdio transport
    $ toolregistry-server mcp --transport stdio

    # Start MCP server with SSE transport
    $ toolregistry-server mcp --transport sse --port 8000

    # With configuration file
    $ toolregistry-server openapi --config tools.jsonc

    # With custom .env file
    $ toolregistry-server openapi --env /path/to/.env

    # Skip loading .env file
    $ toolregistry-server openapi --no-env
"""

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from .._structlog import get_logger

logger = get_logger()

# Default ASCII art banner for ToolRegistry Server
DEFAULT_BANNER_ART = """
░▀█▀░█▀█░█▀█░█░░░█▀▄░█▀▀░█▀▀░▀█▀░█▀▀░▀█▀░█▀▄░█░█░░░░░█▀▀░█▀▀░█▀▄░█░█░█▀▀░█▀▄
░░█░░█░█░█░█░█░░░█▀▄░█▀▀░█░█░░█░░▀▀█░░█░░█▀▄░░█░░▄▄▄░▀▀█░█▀▀░█▀▄░▀▄▀░█▀▀░█▀▄
░░▀░░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀▀▀░▀▀▀░░▀░░▀░▀░░▀░░░░░░▀▀▀░▀▀▀░▀░▀░░▀░░▀▀▀░▀░▀
""".strip()


def load_env_file(env_path: str | None = None, no_env: bool = False) -> None:
    """Load environment variables from .env file.

    Args:
        env_path: Path to .env file. If None, uses current directory's .env
        no_env: If True, skip loading .env file
    """
    if no_env:
        return

    from .._dotenv import load_dotenv

    path = Path(env_path) if env_path else Path.cwd() / ".env"

    if path.exists():
        load_dotenv(path)
        logger.info(f"Loaded environment from {path}")
    elif env_path:
        # User explicitly specified a path but file doesn't exist
        logger.warning(f"Environment file not found: {path}")


def print_banner(
    version: str | None = None,
    banner_art: str | None = None,
    extra_lines: list[str] | None = None,
) -> None:
    """Print the ToolRegistry Server banner with centered content and border.

    This function can be used by downstream packages (e.g., toolregistry-hub)
    to display a customized banner with their own version and art.

    Args:
        version: Version string to display. If None, uses toolregistry-server version.
        banner_art: Custom ASCII art to display. If None, uses default banner.
        extra_lines: Additional lines to display after the version (e.g., update info).
    """
    if version is None:
        from toolregistry_server import __version__

        version = __version__

    if banner_art is None:
        banner_art = DEFAULT_BANNER_ART

    width = 80
    border_char = "·"

    # Split banner art into lines
    art_lines = banner_art.split("\n")

    # Build the banner
    lines = []

    # Top border
    lines.append(border_char * width)

    # Empty line
    lines.append(f": {' ' * (width - 4)} :")

    # Art lines - center each line
    for line in art_lines:
        centered = line.center(width - 4)
        lines.append(f": {centered} :")

    # Empty line
    lines.append(f": {' ' * (width - 4)} :")

    # Version information
    version_line = f"Version {version}"
    centered_version = version_line.center(width - 4)
    lines.append(f": {centered_version} :")

    # Extra lines (e.g., update available info)
    if extra_lines:
        for extra in extra_lines:
            centered_extra = extra.center(width - 4)
            lines.append(f": {centered_extra} :")

    # Empty line
    lines.append(f": {' ' * (width - 4)} :")

    # Bottom border
    lines.append(border_char * width)

    # Print the banner
    print("\n".join(lines))


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        Configured ArgumentParser instance with subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="toolregistry-server",
        description="Define custom tools and serve them via OpenAPI or MCP interfaces",
    )

    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help="Show version and exit",
    )

    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Disable the startup banner",
    )

    # Create subparsers for openapi and mcp commands
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available server modes",
        metavar="{openapi,mcp}",
    )

    # OpenAPI subcommand
    openapi_parser = subparsers.add_parser(
        "openapi",
        help="Start OpenAPI (REST) server",
        description="Start an OpenAPI server exposing tools as REST endpoints",
    )
    _add_openapi_arguments(openapi_parser)

    # MCP subcommand
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start MCP server",
        description="Start an MCP server for LLM tool integration",
    )
    _add_mcp_arguments(mcp_parser)

    return parser


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common arguments shared by all subcommands.

    Args:
        parser: The ArgumentParser to add arguments to.
    """
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to .env file. Default: .env in current directory",
    )
    parser.add_argument(
        "--no-env",
        action="store_true",
        help="Skip loading .env file",
    )


def _add_openapi_arguments(parser: argparse.ArgumentParser) -> None:
    """Add OpenAPI-specific arguments to the parser.

    Args:
        parser: The ArgumentParser to add arguments to.
    """
    _add_common_arguments(parser)
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a JSON/JSONC configuration file for tools",
    )
    parser.add_argument(
        "--tokens",
        type=str,
        default=None,
        help="Path to a file containing authentication tokens (one per line)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development mode",
    )


def _add_mcp_arguments(parser: argparse.ArgumentParser) -> None:
    """Add MCP-specific arguments to the parser.

    Args:
        parser: The ArgumentParser to add arguments to.
    """
    _add_common_arguments(parser)
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport type: stdio, sse, or streamable-http (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for SSE/HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE/HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a JSON/JSONC configuration file for tools",
    )


def main(args: list[str] | None = None) -> NoReturn | None:
    """Main entry point for the CLI.

    Args:
        args: Command-line arguments. If None, uses sys.argv.

    Returns:
        None on success, or exits with error code.
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    # Handle version flag
    if parsed.version:
        from toolregistry_server import __version__

        print(f"toolregistry-server {__version__}")
        sys.exit(0)

    # If no command specified, show help
    if parsed.command is None:
        parser.print_help()
        sys.exit(0)

    # Load environment variables from .env file
    load_env_file(
        env_path=getattr(parsed, "env", None),
        no_env=getattr(parsed, "no_env", False),
    )

    # Print banner unless disabled
    if not parsed.no_banner:
        print_banner()

    # Dispatch to appropriate command handler
    if parsed.command == "openapi":
        from .openapi import run_openapi_server

        run_openapi_server(
            host=parsed.host,
            port=parsed.port,
            config_path=parsed.config,
            tokens_path=parsed.tokens,
            reload=parsed.reload,
        )
    elif parsed.command == "mcp":
        from .mcp import run_mcp_server

        run_mcp_server(
            transport=parsed.transport,
            host=parsed.host,
            port=parsed.port,
            config_path=parsed.config,
        )

    return None


__all__ = [
    "main",
    "create_parser",
    "print_banner",
    "load_env_file",
    "DEFAULT_BANNER_ART",
]
