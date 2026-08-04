"""
Authentication module for ToolRegistry Server.

This module provides authentication utilities for securing
ToolRegistry server endpoints.

Main Components:
    - BearerTokenAuth: Bearer token authentication for FastAPI
    - verify_token: Token verification utility
    - create_bearer_dependency: Create a FastAPI dependency for Bearer auth

Example:
    ```python
    from toolregistry_server.auth import BearerTokenAuth, create_bearer_dependency

    auth = BearerTokenAuth(tokens=["secret-token"])
    # Use with FastAPI dependency injection
    dependency = create_bearer_dependency(auth)
    ```
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import Any


class BearerTokenAuth:
    """Bearer token authentication handler.

    This class provides Bearer token authentication for FastAPI endpoints.
    It supports multiple valid tokens and can be used as a FastAPI dependency.

    Attributes:
        tokens: Set of valid tokens.

    Example:
        ```python
        auth = BearerTokenAuth(tokens=["token1", "token2"])
        auth.verify("token1")   # True
        auth.verify("invalid")  # False
        ```
    """

    def __init__(self, tokens: "Sequence[str] | None" = None) -> None:
        """Initialize the authentication handler.

        Args:
            tokens: List of valid tokens. If None or empty, authentication
                   is disabled (all requests pass).
        """
        self._tokens: set[str] = set(tokens) if tokens else set()
        self._enabled = bool(self._tokens)

    @property
    def enabled(self) -> bool:
        """Check if authentication is enabled.

        Returns:
            True if at least one token is configured.
        """
        return self._enabled

    @property
    def tokens(self) -> set[str]:
        """Get the set of valid tokens.

        Returns:
            Set of valid tokens.
        """
        return self._tokens.copy()

    def verify(self, token: str) -> bool:
        """Verify a token.

        Args:
            token: The token to verify.

        Returns:
            True if the token is valid or auth is disabled.
        """
        if not self._enabled:
            return True
        return token in self._tokens

    def add_token(self, token: str) -> None:
        """Add a valid token.

        Args:
            token: The token to add.
        """
        self._tokens.add(token)
        self._enabled = True

    def remove_token(self, token: str) -> None:
        """Remove a token.

        Args:
            token: The token to remove.
        """
        self._tokens.discard(token)
        self._enabled = bool(self._tokens)


def verify_token(token: str, valid_tokens: "Sequence[str]") -> bool:
    """Verify a token against a list of valid tokens.

    Args:
        token: The token to verify.
        valid_tokens: List of valid tokens.

    Returns:
        True if the token is in the valid tokens list.
    """
    return token in valid_tokens


def create_bearer_dependency(auth: BearerTokenAuth) -> "Callable[..., Any]":
    """Create a FastAPI dependency for Bearer token authentication.

    This function creates a dependency that can be used with FastAPI's
    dependency injection system to protect endpoints with Bearer token
    authentication.

    Args:
        auth: The BearerTokenAuth instance to use for verification.

    Returns:
        A FastAPI dependency function.

    Raises:
        ImportError: If FastAPI is not installed.

    Example:
        ```python
        from fastapi import FastAPI, Depends
        from toolregistry_server.auth import BearerTokenAuth, create_bearer_dependency

        auth = BearerTokenAuth(tokens=["secret-token"])
        dependency = create_bearer_dependency(auth)

        app = FastAPI(dependencies=[Depends(dependency)])
        ```
    """
    try:
        from typing import Annotated

        from fastapi import Depends, HTTPException, status
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for authentication dependencies. "
            "Install with: pip install toolregistry-server[openapi]"
        ) from e

    security = HTTPBearer()

    async def verify_bearer_token(
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    ) -> str:
        """Verify Bearer token from Authorization header.

        Args:
            credentials: HTTP Bearer credentials from the Authorization header

        Returns:
            The verified token string

        Raises:
            HTTPException: If token is invalid or missing when required
        """
        # If no tokens configured, disable verification
        if not auth.enabled:
            return ""

        # Extract token from credentials
        token = credentials.credentials

        if not auth.verify(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return token

    return verify_bearer_token


__all__ = [
    "BearerTokenAuth",
    "create_bearer_dependency",
    "verify_token",
]
