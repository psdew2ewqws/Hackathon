"""C11 — JSON Schema validator for intersection metadata.

Validates ``--site`` against ``intersection_schema.json`` using the
``jsonschema`` library's Draft 2020-12 validator.

Exit 0 = valid. Exit 1 = one or more errors (printed as JSON-Pointer paths).
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_RESOURCE = files("traffic_intel_sandbox.metadata").joinpath("intersection_schema.json")


def load_schema() -> dict:
    with SCHEMA_RESOURCE.open() as fh:  # type: ignore[attr-defined]
        return json.load(fh)


def validate(site_path: Path, schema: dict | None = None) -> list[str]:
    schema = schema or load_schema()
    with site_path.open() as fh:
        instance = json.load(fh)
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        path = "/" + "/".join(str(p) for p in err.path) if err.path else "<root>"
        errors.append(f"{path}: {err.message}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate intersection metadata JSON.")
    parser.add_argument("--site", type=Path, required=True,
                        help="Path to site metadata JSON (e.g., site1.example.json)")
    args = parser.parse_args(argv)

    errors = validate(args.site)
    if errors:
        print(f"[validate] FAIL — {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"[validate] OK — {args.site}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
