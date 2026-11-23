"""Constants for MowBite."""

import json
from pathlib import Path
from typing import Any

DOMAIN = "mowbite"

CONF_PREFIX = "prefix"
# where the MowBite app runs, for its colours and symbols on the map (optional)
CONF_APP_URL = "app_url"
# when the card shows the map, unless the card itself says otherwise
CONF_MAP = "map"
MAP_MODES = ["app", "auto", "always", "never"]
# the mower's sizes for drawing its body and the strip its blade cuts, as MowBite's settings have them (m)
CONF_MOWER = "mower"
CONF_SIZES = "mower_sizes"
SIZE_KEYS = ["width", "front", "rear", "blade", "bladeAhead", "bladeOffset"]
# the widest blade MowBite takes, more than any mower running OpenMower cuts
MAX_BLADE = 0.4


def _models() -> dict[str, dict[str, Any]]:
    """The mower models MowBite knows, by the option's value (the app's key with underscores): the app's own table,
    written into mower_models.json when its pictures are built (scripts/build-art.mjs). The app is where it's kept"""
    table = json.loads((Path(__file__).parent / "mower_models.json").read_text(encoding="utf-8"))
    return {model["key"].replace("-", "_"): model for model in table["models"]}


_MODELS = _models()
# each model's sizes and the name it's picked by
MOWER_MODELS: dict[str, dict[str, float]] = {key: model["sizes"] for key, model in _MODELS.items()}
MOWER_LABELS: dict[str, str] = {key: model["label"] for key, model in _MODELS.items()}

DEFAULT_PORT = 1883
DEFAULT_NAME = "OpenMower"
