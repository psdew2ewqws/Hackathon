"""Validate the shipped site1.example.json against the JSON Schema."""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from traffic_intel_sandbox.metadata.validator import validate


def test_site_example_validates(site_example, intersection_schema):
    errors = validate(site_example)
    assert errors == [], f"site1.example.json is not schema-valid: {errors}"


def test_schema_itself_is_valid(intersection_schema):
    with intersection_schema.open() as fh:
        schema = json.load(fh)
    # Raises SchemaError on any meta-schema violation.
    Draft202012Validator.check_schema(schema)


def test_schema_rejects_empty_object(intersection_schema):
    with intersection_schema.open() as fh:
        schema = json.load(fh)
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors({}))
    # Must complain about all required top-level fields.
    required = {"intersection_id", "camera", "approaches", "stop_lines", "monitoring_zones"}
    messages = " ".join(e.message for e in errors)
    for field in required:
        assert field in messages, f"schema should require {field}"
