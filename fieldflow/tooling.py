from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple, Type

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field, create_model

from .proxy import APIProxy
from .spec_parser import EndpointOperation, Parameter, SchemaFactory


def create_tools_router(
    operations: List[EndpointOperation],
    schema_factory: SchemaFactory,
    proxy: APIProxy,
) -> APIRouter:
    """Create a FastAPI router that exposes generated operation and discovery endpoints."""

    router = APIRouter()
    for operation in operations:
        request_model = build_request_model(operation, schema_factory)
        discovery_model = build_discovery_request_model(operation, schema_factory)
        response_model = operation.response_model or Dict[str, Any]
        endpoint_path = f"/tools/{operation.name}"
        discovery_endpoint_path = f"/tools/{operation.name}/discover-fields"
        summary = (
            operation.summary or f"{operation.method.upper()} {operation.path}".strip()
        )

        async def endpoint(
            payload: Any = Body(...),
            __operation=operation,
            __request_model=request_model,
        ) -> Any:  # type: ignore[misc]
            param_map = getattr(__request_model, "__mcp_param_map__")
            path_params, query_params, body_payload = _extract_proxy_payload(
                payload, param_map
            )
            fields_name = param_map["fields"]
            requested_fields = getattr(payload, fields_name)
            field_query_name = param_map["field_query"]
            requested_field_query = getattr(payload, field_query_name)
            field_query_limit_name = param_map["field_query_limit"]
            field_query_limit = getattr(payload, field_query_limit_name)
            discovery_id_name = param_map["discovery_id"]
            discovery_id = getattr(payload, discovery_id_name)

            return await proxy.execute(
                operation=__operation,
                path_params=path_params,
                query_params=query_params,
                body=body_payload,
                fields=requested_fields,
                field_query=requested_field_query,
                field_query_limit=field_query_limit,
                discovery_id=discovery_id,
                path_template=__operation.path,
            )

        async def discover_endpoint(
            payload: Any = Body(...),
            __operation=operation,
            __request_model=discovery_model,
        ) -> Any:  # type: ignore[misc]
            param_map = getattr(__request_model, "__mcp_param_map__")
            path_params, query_params, body_payload = _extract_proxy_payload(
                payload, param_map
            )
            return await proxy.discover_fields(
                operation=__operation,
                path_params=path_params,
                query_params=query_params,
                body=body_payload,
                path_template=__operation.path,
            )

        request_model.model_rebuild()
        endpoint.__annotations__["payload"] = request_model
        router.post(
            endpoint_path,
            response_model=response_model,
            response_model_exclude_none=True,
            summary=summary,
            name=operation.name,
        )(endpoint)

        discovery_model.model_rebuild()
        discover_endpoint.__annotations__["payload"] = discovery_model
        router.post(
            discovery_endpoint_path,
            response_model=Dict[str, Any],
            response_model_exclude_none=True,
            summary=f"Discover fields for {summary}",
            name=f"{operation.name}__discover_fields",
        )(discover_endpoint)

    return router


def build_request_model(
    operation: EndpointOperation, schema_factory: SchemaFactory
) -> Type[BaseModel]:
    return _build_operation_payload_model(
        operation,
        schema_factory,
        include_response_controls=True,
    )


def build_discovery_request_model(
    operation: EndpointOperation, schema_factory: SchemaFactory
) -> Type[BaseModel]:
    return _build_operation_payload_model(
        operation,
        schema_factory,
        include_response_controls=False,
    )


def _build_operation_payload_model(
    operation: EndpointOperation,
    schema_factory: SchemaFactory,
    *,
    include_response_controls: bool,
) -> Type[BaseModel]:
    fields: Dict[str, Tuple[Any, Any]] = {}
    used_names: Set[str] = set()
    path_map: Dict[str, str] = {}
    query_map: Dict[str, str] = {}

    for param in operation.path_params:
        sanitized, alias = _sanitize_name(param.name, used_names)
        field_type, default = _parameter_type_and_default(param, schema_factory)
        path_map[param.name] = sanitized
        fields[sanitized] = (
            field_type,
            _field_value(default, alias=alias, description=param.description),
        )

    for param in operation.query_params:
        sanitized, alias = _sanitize_name(param.name, used_names)
        field_type, default = _parameter_type_and_default(param, schema_factory)
        query_map[param.name] = sanitized
        fields[sanitized] = (
            field_type,
            _field_value(default, alias=alias, description=param.description),
        )

    body_field_name: Optional[str] = None
    if operation.request_body_model:
        sanitized, _ = _sanitize_name("body", used_names)
        body_field_name = sanitized
        body_type: Any = operation.request_body_model
        default = ... if operation.request_body_required else None
        if not operation.request_body_required:
            from typing import Optional as TypingOptional

            body_type = TypingOptional[body_type]
        fields[sanitized] = (
            body_type,
            _field_value(default, description="JSON request body"),
        )

    param_map: Dict[str, Any] = {
        "path": path_map,
        "query": query_map,
        "body": body_field_name,
    }

    if include_response_controls:
        fields_field_name, _ = _sanitize_name("fields", used_names)
        field_query_name, _ = _sanitize_name("field_query", used_names)
        field_query_limit_name, _ = _sanitize_name("field_query_limit", used_names)
        discovery_id_name, _ = _sanitize_name("discovery_id", used_names)
        from typing import List as TypingList
        from typing import Optional as TypingOptional

        fields[fields_field_name] = (
            TypingOptional[TypingList[str]],
            Field(
                default=None,
                description="Subset of response properties to include in the result.",
            ),
        )
        fields[field_query_name] = (
            TypingOptional[str],
            Field(
                default=None,
                description=(
                    "Natural-language/fuzzy field query. Used only when `fields` is not provided."
                ),
            ),
        )
        fields[field_query_limit_name] = (
            int,
            Field(
                default=8,
                ge=1,
                le=50,
                description="Maximum number of fields selected from `field_query`.",
            ),
        )
        fields[discovery_id_name] = (
            TypingOptional[str],
            Field(
                default=None,
                description=(
                    "Cache key returned by the discovery endpoint. When provided, "
                    "FieldFlow reuses cached payload data instead of calling the "
                    "upstream API again."
                ),
            ),
        )
        param_map.update(
            {
                "fields": fields_field_name,
                "field_query": field_query_name,
                "field_query_limit": field_query_limit_name,
                "discovery_id": discovery_id_name,
            }
        )

    model_name_suffix = "payload" if include_response_controls else "discovery_payload"
    model_name = f"{operation.name}_{model_name_suffix}".replace("-", "_")
    base_model = type(
        f"{model_name.title()}Base",
        (BaseModel,),
        {"model_config": ConfigDict(populate_by_name=True)},
    )
    request_model = create_model(
        model_name,
        __base__=base_model,
        __module__=__name__,
        **fields,
    )  # type: ignore[call-overload]
    setattr(request_model, "__mcp_param_map__", param_map)
    request_model.model_rebuild()
    return request_model


def _extract_proxy_payload(
    payload: BaseModel,
    param_map: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    path_params = extract_parameters(payload, param_map["path"])
    missing = [
        name
        for name, attr in param_map["path"].items()
        if getattr(payload, attr) is None
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required path parameters: {missing}",
        )
    query_params = extract_parameters(payload, param_map["query"], exclude_none=True)
    body_payload = _extract_body_payload(payload, param_map.get("body"))
    return path_params, query_params, body_payload


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
    raise HTTPException(status_code=400, detail="Request body must be an object")


def _parameter_type_and_default(
    param: Parameter, schema_factory: SchemaFactory
) -> Tuple[Any, Any]:
    python_type = schema_factory.type_for_parameter(param)
    has_default = "default" in param.schema
    default_value = param.schema.get("default") if has_default else None
    if param.required:
        default = default_value if has_default else ...
    else:
        default = default_value if has_default else None
        from typing import Optional as TypingOptional

        python_type = TypingOptional[python_type]
    return python_type, default


def _sanitize_name(name: str, used: Set[str]) -> Tuple[str, Optional[str]]:
    sanitized = (
        "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name) or "field"
    )
    if sanitized[0].isdigit():
        sanitized = f"field_{sanitized}"
    candidate = sanitized
    index = 1
    while candidate in used:
        index += 1
        candidate = f"{sanitized}_{index}"
    alias = None if candidate == name else name
    used.add(candidate)
    return candidate, alias


def _field_value(
    default: Any, *, alias: Optional[str] = None, description: Optional[str] = None
) -> Any:
    metadata: Dict[str, Any] = {}
    if alias:
        metadata["alias"] = alias
    if description:
        metadata["description"] = description
    if metadata:
        if default is ...:
            return Field(..., **metadata)
        return Field(default, **metadata)
    return default


def extract_parameters(
    payload: BaseModel,
    mapping: Dict[str, str],
    *,
    exclude_none: bool = False,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for original, attr in mapping.items():
        value = getattr(payload, attr)
        if exclude_none and value is None:
            continue
        result[original] = value
    return result
