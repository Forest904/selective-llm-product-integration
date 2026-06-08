from __future__ import annotations

from pathlib import Path

from mosaic.m1_models import MediatedSchema, load_mediated_schema


def validate_mediated_schema(path: Path) -> MediatedSchema:
    return load_mediated_schema(path)
