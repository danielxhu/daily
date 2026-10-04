"""Contract codegen (X0.4).

Derives, from the §7 Pydantic models, the two artifacts that keep backend and
frontend in sync:

* a JSON-Schema document (`tests/snapshots/schema.json`) — the machine-checkable
  contract snapshot (this is what FastAPI's OpenAPI would emit for these models);
* a TypeScript types file (`frontend/src/types/contract.ts`) — so the frontend can
  start against the stable contract with fixtures/mock (Stage 2) and fail loudly if
  it drifts.

Tests assert the committed artifacts equal a fresh regeneration. To update them
after an intentional §7 change: `python -m app.schemas.codegen`.
"""

from __future__ import annotations

import json
import types
import typing
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.schemas.models import (
    ALL_MODELS,
    CitationType,
    ExtractionMethod,
    Origin,
    SourceFailureKind,
    SourceType,
    SubscriptionFailureKind,
    Tier,
)

_THIS = Path(__file__).resolve()
BACKEND_DIR = _THIS.parents[2]
WORKPLACE_DIR = _THIS.parents[3]
SNAPSHOT_PATH = BACKEND_DIR / "tests" / "snapshots" / "schema.json"
TS_PATH = WORKPLACE_DIR / "frontend" / "src" / "types" / "contract.ts"

_NONE = type(None)

# Shared enum aliases emitted as named TS types and referenced where used.
_ALIASES: list[tuple[str, Any]] = [
    ("SourceType", SourceType),
    ("Origin", Origin),
    ("CitationType", CitationType),
    ("Tier", Tier),
    ("ExtractionMethod", ExtractionMethod),
    ("SourceFailureKind", SourceFailureKind),
    ("SubscriptionFailureKind", SubscriptionFailureKind),
]


# ---------------------------------------------------------------------------
# JSON-Schema snapshot
# ---------------------------------------------------------------------------


def build_schema_document() -> dict[str, Any]:
    """One JSON-Schema doc with shared `$defs` for every §7 model (deduped)."""
    _, schema = models_json_schema(
        [(m, "validation") for m in ALL_MODELS],
        ref_template="#/$defs/{model}",
    )
    return schema


def schema_json() -> str:
    return json.dumps(build_schema_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# TypeScript codegen
# ---------------------------------------------------------------------------


def _ts_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _alias_name(ann: Any) -> str | None:
    for name, lit in _ALIASES:
        if ann == lit:
            return name
    return None


def _ts_type(ann: Any) -> str:
    name = _alias_name(ann)
    if name is not None:
        return name

    origin = typing.get_origin(ann)

    if origin is typing.Literal:
        return " | ".join(_ts_literal(a) for a in typing.get_args(ann))

    if origin is typing.Union or origin is getattr(types, "UnionType", object()):
        args = list(typing.get_args(ann))
        non_none = [_ts_type(a) for a in args if a is not _NONE]
        rendered = " | ".join(non_none)
        if _NONE in args:
            rendered = f"{rendered} | null"
        return rendered

    if origin is list:
        item_args = typing.get_args(ann)
        item = _ts_type(item_args[0]) if item_args else "unknown"
        return f"{item}[]"

    if origin is dict:
        return "Record<string, unknown>"

    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann.__name__

    if ann is str:
        return "string"
    if ann in (int, float):
        return "number"
    if ann is bool:
        return "boolean"
    if ann in (datetime, date):
        return "string"
    if ann is Any:
        return "unknown"
    return "unknown"


def _ts_interface(model: type[BaseModel]) -> str:
    lines = [f"export interface {model.__name__} {{"]
    for fname, field in model.model_fields.items():
        optional = "" if field.is_required() else "?"
        lines.append(f"  {fname}{optional}: {_ts_type(field.annotation)};")
    lines.append("}")
    return "\n".join(lines)


def generate_typescript() -> str:
    parts = [
        "// AUTO-GENERATED from backend/app/schemas/models.py (SSOT §7). DO NOT EDIT.",
        "// Regenerate: `cd backend && python -m app.schemas.codegen`.",
        "",
    ]
    for name, lit in _ALIASES:
        union = " | ".join(_ts_literal(a) for a in typing.get_args(lit))
        parts.append(f"export type {name} = {union};")
    parts.append("")
    parts.extend(_ts_interface(m) + "\n" for m in ALL_MODELS)
    return "\n".join(parts).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Regeneration entry point
# ---------------------------------------------------------------------------


def regenerate() -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(schema_json(), encoding="utf-8")
    TS_PATH.write_text(generate_typescript(), encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH}")
    print(f"wrote {TS_PATH}")


if __name__ == "__main__":
    regenerate()
