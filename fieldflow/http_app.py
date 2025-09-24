from __future__ import annotations

from typing import List

from fastapi import FastAPI

from .auth import EnvironmentAuthProvider, OpenAPISecurityProvider
from .config import settings
from .openapi_loader import load_spec
from .proxy import APIProxy
from .spec_parser import OpenAPIParser
from .tooling import create_tools_router
from .utils import extract_base_url


def create_fastapi_app() -> FastAPI:
    spec = load_spec(settings.openapi_spec_path)
    parser = OpenAPIParser(spec)
    operations = parser.parse()

    base_url = settings.target_api_base_url or extract_base_url(spec)
    if not base_url:
        raise RuntimeError(
            "The upstream API base URL could not be determined. Provide FIELD_FLOW_TARGET_API_BASE_URL or define a server in the spec."
        )

    # Set up authentication providers
    env_auth_provider = EnvironmentAuthProvider()
    auth_provider = env_auth_provider

    # If OpenAPI spec has security schemes, use OpenAPISecurityProvider
    if parser.security_schemes:
        auth_provider = OpenAPISecurityProvider(
            parser.security_schemes, env_auth_provider
        )

    proxy = APIProxy(base_url, auth_provider=auth_provider)
    app = FastAPI(
        title="FieldFlow API",
        description="Expose REST API endpoints as FieldFlow tools generated from an OpenAPI specification.",
        version="0.1.0",
    )

    app.include_router(create_tools_router(operations, parser.schema_factory, proxy))

    @app.get("/", summary="Service information")
    async def info() -> dict:
        return {
            "tool_count": len(operations),
            "spec_path": str(settings.openapi_spec_path),
            "base_url": base_url,
        }

    @app.get("/tools", summary="List generated tool endpoints")
    async def list_tools() -> List[dict]:
        return [
            {
                "name": op.name,
                "method": op.method.upper(),
                "path": op.path,
                "summary": op.summary,
            }
            for op in operations
        ]

    return app


app = create_fastapi_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fieldflow.http_app:app", host="0.0.0.0", port=8000, reload=True)
