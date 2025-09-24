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
    """Create a FastAPI router that exposes MCP tools for each API endpoint."""

    router = APIRouter()
    for operation in operations:
        request_model = build_request_model(operation, schema_factory)
        response_model = operation.response_model or Dict[str, Any]
        endpoint_path = f"/tools/{operation.name}"
        summary = (
            operation.summary or f"{operation.method.upper()} {operation.path}".strip()
        )

        async def endpoint(
            payload: request_model = Body(...),
            __operation=operation,
            __request_model=request_model,
        ) -> Any:  # type: ignore[misc]
            param_map = getattr(__request_model, "__mcp_param_map__")
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
                        body_payload = body_obj.dict(exclude_none=True, by_alias=True)
                    elif isinstance(body_obj, dict):
                        body_payload = body_obj
                    else:
                        raise HTTPException(
                            status_code=400, detail="Request body must be an object"
                        )

            path_template = __operation.path
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

            return await proxy.execute(
                operation=__operation,
                path_params=path_params,
                query_params=query_params,
                body=body_payload,
                fields=requested_fields,
                path_template=path_template,
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

    return router


def build_request_model(
    operation: EndpointOperation, schema_factory: SchemaFactory
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

    fields_field_name, _ = _sanitize_name("fields", used_names)
    from typing import List as TypingList
    from typing import Optional as TypingOptional

    fields[fields_field_name] = (
        TypingOptional[TypingList[str]],
        Field(
            default=None,
            description="Subset of response properties to include in the result.",
        ),
    )

    model_name = f"{operation.name}_payload".replace("-", "_")
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
    )  # type: ignore[arg-type]
    setattr(
        request_model,
        "__mcp_param_map__",
        {
            "path": path_map,
            "query": query_map,
            "body": body_field_name,
            "fields": fields_field_name,
        },
    )
    request_model.model_rebuild()
    return request_model


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
