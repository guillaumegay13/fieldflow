from __future__ import annotations

from typing import get_args, get_origin

from fieldflow.spec_parser import Parameter, SchemaFactory


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
