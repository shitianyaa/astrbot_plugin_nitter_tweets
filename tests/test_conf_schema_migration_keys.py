"""Internal migration markers must stay declared and hidden in the WebUI schema.

`_video_resolution_preference_migrated` once shipped undeclared, so AstrBot's
WebUI rendered it as a bare editable field showing `true`. Every migration
sentinel written into config needs an `invisible` schema entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import config.compat as compat

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "_conf_schema.json"


def _migration_keys() -> set[str]:
    return {
        value
        for name, value in vars(compat).items()
        if name.endswith("MIGRATION_KEY") and isinstance(value, str)
    }


def test_every_migration_marker_is_declared_invisible():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    keys = _migration_keys()
    # Guard the guard: a renamed constant suffix would silently empty this set.
    assert len(keys) >= 7

    missing = sorted(key for key in keys if key not in schema)
    assert not missing, f"migration markers missing from _conf_schema.json: {missing}"

    visible = sorted(key for key in keys if not schema[key].get("invisible"))
    assert not visible, f"migration markers must be invisible in WebUI: {visible}"

    wrong_type = sorted(key for key in keys if schema[key].get("type") != "bool")
    assert not wrong_type, f"migration markers must be bool: {wrong_type}"
