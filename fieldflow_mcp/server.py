from __future__ import annotations

import inspect
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from fieldflow.auth import EnvironmentAuthProvider, OpenAPISecurityProvider
from fieldflow.config import settings
from fieldflow.openapi_loader import load_spec
from fieldflow.proxy import APIProxy
from fieldflow.spec_parser import EndpointOperation, OpenAPIParser, SchemaFactory
from fieldflow.tooling import build_request_model, extract_parameters
from fieldflow.utils import extract_base_url

INSTRUCTIONS = (
    "Tools in this server are generated dynamically from the supplied OpenAPI specification. "
    "Provide the required parameters and include a `fields` list whenever you only need part of the response."
)


def create_mcp_server(
    *,
    name: Optional[str] = None,
    instructions: Optional[str] = None,
) -> FastMCP:
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
    server = FastMCP(
        name=name or "fieldflow-mcp",
        instructions=instructions or INSTRUCTIONS,
    )

    for operation in operations:
        _register_operation(server, proxy, operation, parser.schema_factory)

    return server


def _register_operation(
    server: FastMCP,
    proxy: APIProxy,
    operation: EndpointOperation,
    schema_factory: SchemaFactory,
) -> None:
    request_model = build_request_model(operation, schema_factory)
    param_map = getattr(request_model, "__mcp_param_map__")

    parameters = []
    for field_name, field_info in request_model.model_fields.items():
        annotation = field_info.annotation or Any
        default = field_info.default
        if default is PydanticUndefined or field_info.is_required():
            default = inspect._empty
        parameter = inspect.Parameter(
            field_name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=default,
            annotation=annotation,
        )
        parameters.append(parameter)

    return_annotation = operation.response_model or Any
    structured_output = operation.response_model is not None

    async def tool_fn(**kwargs: Any) -> Any:
        payload = request_model(**kwargs)

        path_params = extract_parameters(payload, param_map["path"])
        query_params = extract_parameters(
            payload, param_map["query"], exclude_none=True
        )
        fields_name = param_map["fields"]
        requested_fields = getattr(payload, fields_name)

        body_field = param_map.get("body")
        body_payload = None
        if body_field:
            body_obj = getattr(payload, body_field)
            if body_obj is not None:
                if isinstance(body_obj, BaseModel):
                    body_payload = body_obj.model_dump(exclude_none=True, by_alias=True)
                elif isinstance(body_obj, dict):
                    body_payload = body_obj
                else:
                    raise ValueError("Request body must be an object")

        return await proxy.execute(
            operation=operation,
            path_params=path_params,
            query_params=query_params,
            body=body_payload,
            fields=requested_fields,
            path_template=operation.path,
        )

    description = operation.summary or f"{operation.method.upper()} {operation.path}"
    tool_fn.__name__ = f"{operation.name}_tool"
    tool_fn.__doc__ = description
    tool_fn.__signature__ = inspect.Signature(
        parameters=parameters, return_annotation=return_annotation
    )

    server.add_tool(
        tool_fn,
        name=operation.name,
        title=description,
        description=description,
        structured_output=structured_output,
    )


def run_stdio(name: Optional[str] = None, instructions: Optional[str] = None) -> None:
    server = create_mcp_server(name=name, instructions=instructions)
    server.run(transport="stdio")
