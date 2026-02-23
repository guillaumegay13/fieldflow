from __future__ import annotations

from typing import get_args, get_origin

from fieldflow.spec_parser import OpenAPIParser, Parameter, SchemaFactory


def test_schema_factory_handles_nullable_union_string() -> None:
    factory = SchemaFactory(spec={})
    param = Parameter(
        name="test",
        location="query",
        required=False,
        schema={"type": ["string", "null"]},
    )

    type_hint = factory.type_for_parameter(param)

    origin = get_origin(type_hint)
    args = get_args(type_hint)

    assert origin is not None
    assert type(None) in args
    assert str in args


def test_parser_resolves_parameter_ref() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Ref API", "version": "1.0.0"},
        "paths": {
            "/users/{userId}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [{"$ref": "#/components/parameters/UserIdParam"}],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": {}}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "parameters": {
                "UserIdParam": {
                    "name": "userId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                }
            }
        },
    }
    operation = OpenAPIParser(spec).parse()[0]
    assert len(operation.path_params) == 1
    assert operation.path_params[0].name == "userId"
    assert operation.path_params[0].required is True
    assert operation.path_params[0].schema["type"] == "integer"


def test_parser_resolves_request_body_and_response_refs() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Ref API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {"$ref": "#/components/requestBodies/CreateUserBody"},
                    "responses": {"201": {"$ref": "#/components/responses/UserResponse"}},
                }
            }
        },
        "components": {
            "requestBodies": {
                "CreateUserBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {"name": {"type": "string"}},
                            }
                        }
                    },
                }
            },
            "responses": {
                "UserResponse": {
                    "description": "Created",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"id": {"type": "integer"}},
                            }
                        }
                    },
                }
            },
        },
    }
    operation = OpenAPIParser(spec).parse()[0]
    assert operation.request_body_required is True
    assert operation.request_body_model is not None
    assert operation.response_schema == {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
    }
