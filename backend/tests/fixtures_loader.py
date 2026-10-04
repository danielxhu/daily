"""Fixture-bank loader (X0.5).

Resolves the demo fixtures under `tests/fixtures/` and the eval datasets under
`eval/`, so tests and the future `eval/benchmark.py` load demo data the same way.
All data is local and offline (NFR-3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def fixture_path(rel: str) -> Path:
    return FIXTURES_DIR / rel


def load_text(rel: str) -> str:
    return fixture_path(rel).read_text(encoding="utf-8")


def load_json(rel: str) -> Any:
    return json.loads(load_text(rel))


def eval_path(rel: str) -> Path:
    return EVAL_DIR / rel


def load_eval(rel: str) -> Any:
    return json.loads(eval_path(rel).read_text(encoding="utf-8"))
