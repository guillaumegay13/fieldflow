from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional, Type, cast

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from fieldflow.auth import (
    AuthProvider,
    EnvironmentAuthProvider,
    OpenAPISecurityProvider,
)
from fieldflow.config import settings
from fieldflow.field_query import (
    create_field_discovery_cache,
    create_field_query_resolver,
)
from fieldflow.openapi_loader import load_spec
from fieldflow.proxy import APIProxy
from fieldflow.spec_parser import EndpointOperation, OpenAPIParser, SchemaFactory
from fieldflow.tooling import (
    build_discovery_request_model,
    build_request_model,
    extract_parameters,
)
from fieldflow.utils import extract_base_url

INSTRUCTIONS = (
    "Tools in this server are generated dynamically from the supplied OpenAPI specification. "
    "Use `<tool>__discover_fields` to get candidate field selectors when you do not know exact field names. "
    "Then call `<tool>` with `fields` and the returned `discovery_id` for a cached, filtered response."
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

    env_auth_provider = EnvironmentAuthProvider()
    auth_provider: AuthProvider = env_auth_provider
    if parser.security_schemes:
        auth_provider = OpenAPISecurityProvider(
            parser.security_schemes, env_auth_provider
        )

    proxy = APIProxy(
        base_url,
        auth_provider=auth_provider,
        default_auth_config=settings.auth_config,
        field_query_resolver=create_field_query_resolver(settings.field_query_ai),
        field_discovery_cache=create_field_discovery_cache(settings.field_discovery),
    )
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
    request_param_map = getattr(request_model, "__mcp_param_map__")
    discovery_model = build_discovery_request_model(operation, schema_factory)
    discovery_param_map = getattr(discovery_model, "__mcp_param_map__")

    return_annotation = operation.response_model or Any
    structured_output = operation.response_model is not None

    async def tool_fn(**kwargs: Any) -> Any:
        payload = request_model(**kwargs)
        path_params = extract_parameters(payload, request_param_map["path"])
        query_params = extract_parameters(
            payload, request_param_map["query"], exclude_none=True
        )
        fields_name = request_param_map["fields"]
        requested_fields = getattr(payload, fields_name)
        field_query_name = request_param_map["field_query"]
        requested_field_query = getattr(payload, field_query_name)
        field_query_limit_name = request_param_map["field_query_limit"]
        field_query_limit = getattr(payload, field_query_limit_name)
        discovery_id_name = request_param_map["discovery_id"]
        discovery_id = getattr(payload, discovery_id_name)

        body_payload = _extract_body_payload(payload, request_param_map.get("body"))
        return await proxy.execute(
            operation=operation,
            path_params=path_params,
            query_params=query_params,
            body=body_payload,
            fields=requested_fields,
            field_query=requested_field_query,
            field_query_limit=field_query_limit,
            discovery_id=discovery_id,
            path_template=operation.path,
        )

    async def discover_tool_fn(**kwargs: Any) -> Any:
        payload = discovery_model(**kwargs)
        path_params = extract_parameters(payload, discovery_param_map["path"])
        query_params = extract_parameters(
            payload, discovery_param_map["query"], exclude_none=True
        )
        body_payload = _extract_body_payload(payload, discovery_param_map.get("body"))
        return await proxy.discover_fields(
            operation=operation,
            path_params=path_params,
            query_params=query_params,
            body=body_payload,
            path_template=operation.path,
        )

    description = operation.summary or f"{operation.method.upper()} {operation.path}"
    callable_tool = cast(Any, tool_fn)
    callable_tool.__name__ = f"{operation.name}_tool"
    callable_tool.__doc__ = description
    callable_tool.__signature__ = inspect.Signature(
        parameters=_build_signature_parameters(request_model),
        return_annotation=return_annotation,
    )
    server.add_tool(
        callable_tool,
        name=operation.name,
        title=description,
        description=description,
        structured_output=structured_output,
    )

    discover_name = f"{operation.name}__discover_fields"
    discover_description = f"Discover candidate field selectors for {description}"
    callable_discover_tool = cast(Any, discover_tool_fn)
    callable_discover_tool.__name__ = f"{discover_name}_tool"
    callable_discover_tool.__doc__ = discover_description
    callable_discover_tool.__signature__ = inspect.Signature(
        parameters=_build_signature_parameters(discovery_model),
        return_annotation=Dict[str, Any],
    )
    server.add_tool(
        callable_discover_tool,
        name=discover_name,
        title=discover_description,
        description=discover_description,
        structured_output=False,
    )


def _build_signature_parameters(model: Type[BaseModel]) -> List[inspect.Parameter]:
    parameters: List[inspect.Parameter] = []
    for field_name, field_info in model.model_fields.items():
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
    return parameters


def _extract_body_payload(
    payload: BaseModel,
    body_field_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not body_field_name:
        return None
    body_obj = getattr(payload, body_field_name)
    if body_obj is None:
        return None
    if isinstance(body_obj, BaseModel):
        return body_obj.model_dump(exclude_none=True, by_alias=True)
    if isinstance(body_obj, dict):
        return body_obj
    raise ValueError("Request body must be an object")


def run_stdio(name: Optional[str] = None, instructions: Optional[str] = None) -> None:
    server = create_mcp_server(name=name, instructions=instructions)
    server.run(transport="stdio")
