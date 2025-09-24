from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from pydantic import BaseModel, Field, create_model


@dataclass
class Parameter:
    name: str
    location: str
    required: bool
    schema: Dict[str, Any]
    description: Optional[str] = None


@dataclass
class EndpointOperation:
    name: str
    method: str
    path: str
    summary: Optional[str]
    path_params: List[Parameter] = field(default_factory=list)
    query_params: List[Parameter] = field(default_factory=list)
    request_body_model: Optional[Type[BaseModel]] = None
    request_body_required: bool = False
    response_model: Optional[Any] = None
    response_schema: Optional[Dict[str, Any]] = None
    raw_operation: Dict[str, Any] = field(default_factory=dict)
    security_requirements: List[Dict[str, List[str]]] = field(default_factory=list)


class SchemaFactory:
    """Build Pydantic models from OpenAPI schema definitions."""

    PRIMITIVE_TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }

    STRING_FORMAT_MAP = {
        "date": date,
        "date-time": datetime,
        "uuid": str,
        "email": str,
    }

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec
        self.components = spec.get("components", {})
        self.model_cache: Dict[str, Type[BaseModel]] = {}
        self._anonymous_index = 0

    def create_response_model(self, name: str, schema: Dict[str, Any]) -> Any:
        """Create a model to describe an operation response."""

        type_hint = self._schema_to_type(name, schema, force_optional=True)
        return type_hint

    def type_for_parameter(self, parameter: Parameter) -> Any:
        """Return a Python type annotation for a parameter."""

        name = f"param_{parameter.name}"
        return self._schema_to_type(name, parameter.schema, force_optional=False)

    def create_request_model(self, name: str, schema: Dict[str, Any]) -> Any:
        """Create a model for a request body."""

        return self._schema_to_type(name, schema, force_optional=False)

    def _schema_to_type(
        self, name: str, schema: Dict[str, Any], force_optional: bool
    ) -> Any:
        if "$ref" in schema:
            resolved_schema = self._resolve_ref(schema["$ref"])
            resolved_name = schema["$ref"].split("/")[-1]
            return self._schema_to_type(resolved_name, resolved_schema, force_optional)

        schema_type = schema.get("type")
        if not schema_type and "properties" in schema:
            schema_type = "object"
        if schema_type == "object":
            return self._build_model(name, schema, force_optional)
        if schema_type == "array":
            items = schema.get("items", {})
            item_type = self._schema_to_type(f"{name}Item", items, force_optional=False)
            from typing import List as TypingList

            return TypingList[item_type]
        if schema_type in self.PRIMITIVE_TYPE_MAP:
            python_type = self.PRIMITIVE_TYPE_MAP[schema_type]
            if schema_type == "string":
                fmt = schema.get("format")
                python_type = self.STRING_FORMAT_MAP.get(fmt, python_type)
            if schema.get("nullable") or force_optional:
                from typing import Optional as TypingOptional

                return TypingOptional[python_type]
            return python_type
        if "enum" in schema:
            return str
        if schema_type == "null":  # pragma: no cover - rare
            return type(None)
        return Any

    def _build_model(
        self, name: str, schema: Dict[str, Any], force_optional: bool
    ) -> Type[BaseModel]:
        cache_key = name
        if cache_key in self.model_cache:
            return self.model_cache[cache_key]

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        fields: Dict[str, Tuple[Any, Any]] = {}
        used_names: Set[str] = set()
        for field_name, field_schema in properties.items():
            nested_name = f"{name}_{field_name}".replace(" ", "_")
            field_type = self._schema_to_type(
                nested_name, field_schema, force_optional=False
            )
            is_required = (
                field_name in required
                and not force_optional
                and not field_schema.get("nullable")
            )
            if not is_required or force_optional:
                from typing import Optional as TypingOptional

                field_type = TypingOptional[field_type]
                default = None
            else:
                default = ...
            sanitized_name, alias = self._sanitize_field_name(field_name, used_names)
            field_description = field_schema.get("description")
            metadata = {}
            if alias:
                metadata["alias"] = alias
            if field_description:
                metadata["description"] = field_description
            if metadata:
                if default is ...:
                    value = Field(..., **metadata)
                else:
                    value = Field(default, **metadata)
            else:
                value = default
            fields[sanitized_name] = (field_type, value)

        if not fields:
            fields["value"] = (Optional[Any], None)

        model_name = self._canonical_model_name(name)
        model = create_model(model_name, **fields)  # type: ignore[arg-type]
        self.model_cache[cache_key] = model
        return model

    def _canonical_model_name(self, name: str) -> str:
        if not name:
            self._anonymous_index += 1
            return f"AnonymousModel{self._anonymous_index}"
        sanitized = "".join(ch if ch.isalnum() else "_" for ch in name.title())
        if sanitized and sanitized[0].isdigit():
            sanitized = f"Model_{sanitized}"
        if sanitized in self.model_cache:
            self._anonymous_index += 1
            sanitized = f"{sanitized}_{self._anonymous_index}"
        return sanitized or f"Model_{self._anonymous_index}"

    def _sanitize_field_name(
        self, name: str, used: Set[str]
    ) -> Tuple[str, Optional[str]]:
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

    def _resolve_ref(self, ref: str) -> Dict[str, Any]:
        parts = ref.split("/")
        if parts[:2] != ["#", "components"]:
            raise ValueError(f"Unsupported $ref path: {ref}")
        node: Any = self.components
        for part in parts[2:]:
            if part not in node:
                raise KeyError(f"Component {part} not found for ref {ref}")
            node = node[part]
        if not isinstance(node, dict):
            raise TypeError(f"Component for ref {ref} must be an object")
        return node


class OpenAPIParser:
    """Parse the loaded OpenAPI spec into structured operations."""

    def __init__(self, spec: Dict[str, Any]):
        if "paths" not in spec:
            raise ValueError("OpenAPI spec must define paths")
        self.spec = spec
        self.schema_factory = SchemaFactory(spec)
        # Parse security schemes if available
        self.security_schemes = self._parse_security_schemes()
        self.global_security = spec.get("security", [])

    def parse(self) -> List[EndpointOperation]:
        operations: List[EndpointOperation] = []
        paths: Dict[str, Any] = self.spec["paths"]

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            common_params = path_item.get("parameters", [])
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(operation, dict):
                    continue
                op_name = self._operation_name(method, path, operation)
                path_params, query_params = self._collect_parameters(
                    common_params, operation.get("parameters", [])
                )
                response_schema = self._extract_response_schema(operation)
                response_model = None
                if response_schema:
                    response_model = self.schema_factory.create_response_model(
                        f"{op_name}_response", response_schema
                    )

                request_body_schema, required_body = self._extract_request_body(
                    operation
                )
                request_body_model = None
                if request_body_schema:
                    request_body_model = self.schema_factory.create_request_model(
                        f"{op_name}_body", request_body_schema
                    )

                # Get security requirements for this operation
                security_requirements = operation.get("security", self.global_security)

                operations.append(
                    EndpointOperation(
                        name=op_name,
                        method=method.lower(),
                        path=path,
                        summary=operation.get("summary"),
                        path_params=path_params,
                        query_params=query_params,
                        request_body_model=request_body_model,
                        request_body_required=required_body,
                        response_model=response_model,
                        response_schema=response_schema,
                        raw_operation=operation,
                        security_requirements=security_requirements,
                    )
                )

        return operations

    def _collect_parameters(
        self, common_params: List[Any], operation_params: List[Any]
    ) -> Tuple[List[Parameter], List[Parameter]]:
        all_params = list(common_params) + list(operation_params)
        path_params: List[Parameter] = []
        query_params: List[Parameter] = []
        for param in all_params:
            if not isinstance(param, dict):
                continue
            location = param.get("in")
            if location not in {"path", "query"}:
                continue
            schema = param.get("schema") or {}
            resolved_schema = schema
            if "$ref" in schema:
                resolved_schema = self.schema_factory._resolve_ref(schema["$ref"])
            parameter = Parameter(
                name=param.get("name", "unknown"),
                location=location,
                required=bool(param.get("required")),
                schema=resolved_schema,
                description=param.get("description"),
            )
            if location == "path":
                path_params.append(parameter)
            else:
                query_params.append(parameter)
        return path_params, query_params

    def _extract_response_schema(
        self, operation: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        responses = operation.get("responses")
        if not isinstance(responses, dict):
            return None
        for status in ("200", "201", "202", "default"):
            response = responses.get(status)
            if not isinstance(response, dict):
                continue
            content = response.get("content")
            if not isinstance(content, dict):
                continue
            for mime, media in content.items():
                if mime not in {"application/json", "application/vnd.api+json"}:
                    continue
                schema = media.get("schema")
                if isinstance(schema, dict):
                    return schema
        return None

    def _extract_request_body(
        self, operation: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        request_body = operation.get("requestBody")
        if not isinstance(request_body, dict):
            return None, False
        required = bool(request_body.get("required"))
        content = request_body.get("content")
        if not isinstance(content, dict):
            return None, required
        for mime, media in content.items():
            if mime not in {"application/json", "application/vnd.api+json"}:
                continue
            schema = media.get("schema")
            if isinstance(schema, dict):
                return schema, required
        return None, required

    def _operation_name(self, method: str, path: str, operation: Dict[str, Any]) -> str:
        if "operationId" in operation:
            return self._to_identifier(operation["operationId"])
        parts = [method.lower()]
        for piece in path.strip("/").split("/"):
            if not piece:
                continue
            if piece.startswith("{") and piece.endswith("}"):
                parts.append("by")
                parts.append(piece[1:-1])
            else:
                parts.append(piece)
        return self._to_identifier("_".join(parts))

    def _to_identifier(self, raw: str) -> str:
        cleaned = [ch if ch.isalnum() else "_" for ch in raw]
        identifier = "".join(cleaned)
        while "__" in identifier:
            identifier = identifier.replace("__", "_")
        identifier = identifier.strip("_").lower()
        if identifier and identifier[0].isdigit():
            identifier = f"op_{identifier}"
        return identifier or "operation"

    def _parse_security_schemes(self) -> Dict[str, Dict[str, Any]]:
        """Parse security schemes from the OpenAPI components."""
        components = self.spec.get("components", {})
        return components.get("securitySchemes", {})
