from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

from .spec_parser import EndpointOperation


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration for an API."""

    auth_type: str
    header_name: str
    api_identifier: Optional[str] = None

    def get_env_var_name(self) -> str:
        """Get the environment variable name for the credential value."""
        prefix = "FIELDFLOW_AUTH"
        if self.api_identifier:
            return f"{prefix}_{self.api_identifier.upper()}_VALUE"
        return f"{prefix}_VALUE"


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @abstractmethod
    def get_auth_headers(
        self, operation: EndpointOperation, auth_config: Optional[AuthConfig] = None
    ) -> Dict[str, str]:
        """Get authentication headers for a request."""
        pass

    @abstractmethod
    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Remove or mask sensitive authentication data from headers."""
        pass


class EnvironmentAuthProvider(AuthProvider):
    """Authentication provider that reads credentials from environment variables."""

    def get_auth_headers(
        self, operation: EndpointOperation, auth_config: Optional[AuthConfig] = None
    ) -> Dict[str, str]:
        """Get authentication headers from environment variables."""
        if not auth_config:
            return {}

        credential_value = os.getenv(auth_config.get_env_var_name())
        if not credential_value:
            return {}

        headers = {}
        if auth_config.auth_type == "bearer":
            headers[auth_config.header_name] = f"Bearer {credential_value}"
        elif auth_config.auth_type in ("apikey", "api-key", "api_key"):
            headers[auth_config.header_name] = credential_value
        elif auth_config.auth_type == "basic":
            headers[auth_config.header_name] = f"Basic {credential_value}"

        # Clear credential from local scope
        del credential_value
        return headers

    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Remove or mask sensitive authentication data from headers."""
        sensitive_headers = {
            "authorization",
            "x-api-key",
            "api-key",
            "x-auth-token",
            "x-access-token",
        }

        sanitized = {}
        for key, value in headers.items():
            if key.lower() in sensitive_headers:
                # Mask the value but show the type
                if value.lower().startswith("bearer "):
                    sanitized[key] = "Bearer [REDACTED]"
                elif value.lower().startswith("basic "):
                    sanitized[key] = "Basic [REDACTED]"
                else:
                    sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value

        return sanitized


class OpenAPISecurityProvider(AuthProvider):
    """Authentication provider based on OpenAPI security schemes."""

    def __init__(
        self,
        security_schemes: Dict[str, Dict],
        env_auth_provider: EnvironmentAuthProvider,
    ):
        self.security_schemes = security_schemes
        self.env_provider = env_auth_provider

    def get_auth_headers(
        self, operation: EndpointOperation, auth_config: Optional[AuthConfig] = None
    ) -> Dict[str, str]:
        """Get authentication headers based on OpenAPI security requirements."""
        if not operation.security_requirements:
            return {}

        # Try each security requirement until we find one with available credentials
        for requirement in operation.security_requirements:
            headers = self._try_security_requirement(requirement, operation)
            if headers:
                return headers

        return {}

    def _try_security_requirement(
        self, requirement: Dict[str, List[str]], operation: EndpointOperation
    ) -> Dict[str, str]:
        """Try to fulfill a single security requirement."""
        for scheme_name in requirement.keys():
            scheme = self.security_schemes.get(scheme_name)
            if not scheme:
                continue

            auth_config = self._scheme_to_auth_config(scheme, scheme_name)
            if auth_config:
                headers = self.env_provider.get_auth_headers(operation, auth_config)
                if headers:
                    return headers

        return {}

    def _scheme_to_auth_config(
        self, scheme: Dict, scheme_name: str
    ) -> Optional[AuthConfig]:
        """Convert OpenAPI security scheme to AuthConfig."""
        scheme_type = scheme.get("type")

        if scheme_type == "apiKey" and scheme.get("in") == "header":
            return AuthConfig(
                auth_type="apikey",
                header_name=scheme.get("name", "X-API-Key"),
                api_identifier=scheme_name,
            )
        elif scheme_type == "http":
            http_scheme = scheme.get("scheme", "").lower()
            if http_scheme == "bearer":
                return AuthConfig(
                    auth_type="bearer",
                    header_name="Authorization",
                    api_identifier=scheme_name,
                )
            elif http_scheme == "basic":
                return AuthConfig(
                    auth_type="basic",
                    header_name="Authorization",
                    api_identifier=scheme_name,
                )

        return None

    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Delegate to environment provider for header sanitization."""
        return self.env_provider.sanitize_headers(headers)


def get_auth_config_from_env(
    api_identifier: Optional[str] = None,
) -> Optional[AuthConfig]:
    """Load authentication configuration from environment variables."""
    prefix = "FIELDFLOW_AUTH"
    if api_identifier:
        prefix = f"{prefix}_{api_identifier.upper()}"

    auth_type = os.getenv(f"{prefix}_TYPE", "").lower()
    if not auth_type:
        return None

    # Default header names based on auth type
    default_headers = {
        "bearer": "Authorization",
        "basic": "Authorization",
        "apikey": "X-API-Key",
        "api-key": "X-API-Key",
        "api_key": "X-API-Key",
    }

    header_name = os.getenv(
        f"{prefix}_HEADER", default_headers.get(auth_type, "Authorization")
    )

    return AuthConfig(
        auth_type=auth_type, header_name=header_name, api_identifier=api_identifier
    )
