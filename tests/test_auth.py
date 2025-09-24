from __future__ import annotations


import pytest

from fieldflow.auth import (
    AuthConfig,
    EnvironmentAuthProvider,
    OpenAPISecurityProvider,
    get_auth_config_from_env,
)
from fieldflow.spec_parser import EndpointOperation


@pytest.fixture
def env_auth_provider():
    return EnvironmentAuthProvider()


@pytest.fixture
def sample_operation():
    return EndpointOperation(
        name="test_operation",
        method="get",
        path="/test",
        summary="Test operation",
    )


@pytest.fixture
def secure_operation():
    return EndpointOperation(
        name="secure_operation",
        method="get",
        path="/secure",
        summary="Secure operation",
        security_requirements=[{"BearerAuth": []}],
    )


class TestAuthConfig:
    def test_auth_config_env_var_name(self):
        config = AuthConfig(auth_type="bearer", header_name="Authorization")
        assert config.get_env_var_name() == "FIELDFLOW_AUTH_VALUE"

    def test_auth_config_env_var_name_with_identifier(self):
        config = AuthConfig(
            auth_type="bearer", header_name="Authorization", api_identifier="github"
        )
        assert config.get_env_var_name() == "FIELDFLOW_AUTH_GITHUB_VALUE"


class TestEnvironmentAuthProvider:
    def test_get_auth_headers_no_config(self, env_auth_provider, sample_operation):
        headers = env_auth_provider.get_auth_headers(sample_operation)
        assert headers == {}

    def test_get_auth_headers_no_env_value(
        self, env_auth_provider, sample_operation, monkeypatch
    ):
        monkeypatch.delenv("FIELDFLOW_AUTH_VALUE", raising=False)
        config = AuthConfig(auth_type="bearer", header_name="Authorization")
        headers = env_auth_provider.get_auth_headers(sample_operation, config)
        assert headers == {}

    def test_get_auth_headers_bearer(
        self, env_auth_provider, sample_operation, monkeypatch
    ):
        monkeypatch.setenv("FIELDFLOW_AUTH_VALUE", "test-token")
        config = AuthConfig(auth_type="bearer", header_name="Authorization")
        headers = env_auth_provider.get_auth_headers(sample_operation, config)
        assert headers == {"Authorization": "Bearer test-token"}

    def test_get_auth_headers_apikey(
        self, env_auth_provider, sample_operation, monkeypatch
    ):
        monkeypatch.setenv("FIELDFLOW_AUTH_VALUE", "test-api-key")
        config = AuthConfig(auth_type="apikey", header_name="X-API-Key")
        headers = env_auth_provider.get_auth_headers(sample_operation, config)
        assert headers == {"X-API-Key": "test-api-key"}

    def test_get_auth_headers_basic(
        self, env_auth_provider, sample_operation, monkeypatch
    ):
        monkeypatch.setenv("FIELDFLOW_AUTH_VALUE", "dXNlcjpwYXNz")
        config = AuthConfig(auth_type="basic", header_name="Authorization")
        headers = env_auth_provider.get_auth_headers(sample_operation, config)
        assert headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    def test_sanitize_headers(self, env_auth_provider):
        headers = {
            "Authorization": "Bearer secret-token",
            "X-API-Key": "secret-key",
            "Content-Type": "application/json",
            "X-Auth-Token": "auth-token",
        }
        sanitized = env_auth_provider.sanitize_headers(headers)
        assert sanitized == {
            "Authorization": "Bearer [REDACTED]",
            "X-API-Key": "[REDACTED]",
            "Content-Type": "application/json",
            "X-Auth-Token": "[REDACTED]",
        }

    def test_sanitize_headers_basic(self, env_auth_provider):
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        sanitized = env_auth_provider.sanitize_headers(headers)
        assert sanitized == {"Authorization": "Basic [REDACTED]"}


class TestOpenAPISecurityProvider:
    def test_no_security_requirements(
        self, env_auth_provider, sample_operation, monkeypatch
    ):
        monkeypatch.setenv("FIELDFLOW_AUTH_BEARERAUTH_VALUE", "test-token")
        security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer"}}
        provider = OpenAPISecurityProvider(security_schemes, env_auth_provider)
        headers = provider.get_auth_headers(sample_operation)
        assert headers == {}

    def test_bearer_auth_from_openapi(
        self, env_auth_provider, secure_operation, monkeypatch
    ):
        monkeypatch.setenv("FIELDFLOW_AUTH_BEARERAUTH_VALUE", "test-token")
        security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer"}}
        provider = OpenAPISecurityProvider(security_schemes, env_auth_provider)
        headers = provider.get_auth_headers(secure_operation)
        assert headers == {"Authorization": "Bearer test-token"}

    def test_api_key_auth_from_openapi(self, env_auth_provider, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_APIKEYAUTH_VALUE", "test-api-key")
        operation = EndpointOperation(
            name="api_key_operation",
            method="get",
            path="/api",
            summary="API key operation",
            security_requirements=[{"ApiKeyAuth": []}],
        )
        security_schemes = {
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        }
        provider = OpenAPISecurityProvider(security_schemes, env_auth_provider)
        headers = provider.get_auth_headers(operation)
        assert headers == {"X-API-Key": "test-api-key"}

    def test_basic_auth_from_openapi(self, env_auth_provider, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_BASICAUTH_VALUE", "dXNlcjpwYXNz")
        operation = EndpointOperation(
            name="basic_operation",
            method="get",
            path="/basic",
            summary="Basic auth operation",
            security_requirements=[{"BasicAuth": []}],
        )
        security_schemes = {"BasicAuth": {"type": "http", "scheme": "basic"}}
        provider = OpenAPISecurityProvider(security_schemes, env_auth_provider)
        headers = provider.get_auth_headers(operation)
        assert headers == {"Authorization": "Basic dXNlcjpwYXNz"}

    def test_multiple_security_options(self, env_auth_provider, monkeypatch):
        # Only provide API key, not bearer token
        monkeypatch.setenv("FIELDFLOW_AUTH_APIKEYAUTH_VALUE", "test-api-key")
        operation = EndpointOperation(
            name="multi_auth_operation",
            method="get",
            path="/multi",
            summary="Multi auth operation",
            security_requirements=[{"BearerAuth": []}, {"ApiKeyAuth": []}],
        )
        security_schemes = {
            "BearerAuth": {"type": "http", "scheme": "bearer"},
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        }
        provider = OpenAPISecurityProvider(security_schemes, env_auth_provider)
        headers = provider.get_auth_headers(operation)
        # Should use API key since bearer token is not available
        assert headers == {"X-API-Key": "test-api-key"}


class TestGetAuthConfigFromEnv:
    def test_no_auth_type(self, monkeypatch):
        monkeypatch.delenv("FIELDFLOW_AUTH_TYPE", raising=False)
        config = get_auth_config_from_env()
        assert config is None

    def test_bearer_auth_config(self, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_TYPE", "bearer")
        config = get_auth_config_from_env()
        assert config is not None
        assert config.auth_type == "bearer"
        assert config.header_name == "Authorization"
        assert config.api_identifier is None

    def test_apikey_auth_config(self, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_TYPE", "apikey")
        config = get_auth_config_from_env()
        assert config is not None
        assert config.auth_type == "apikey"
        assert config.header_name == "X-API-Key"

    def test_custom_header_name(self, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_TYPE", "apikey")
        monkeypatch.setenv("FIELDFLOW_AUTH_HEADER", "X-Custom-Key")
        config = get_auth_config_from_env()
        assert config is not None
        assert config.header_name == "X-Custom-Key"

    def test_api_identifier_config(self, monkeypatch):
        monkeypatch.setenv("FIELDFLOW_AUTH_GITHUB_TYPE", "bearer")
        config = get_auth_config_from_env("github")
        assert config is not None
        assert config.auth_type == "bearer"
        assert config.api_identifier == "github"
