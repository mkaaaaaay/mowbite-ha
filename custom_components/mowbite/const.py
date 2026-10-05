"""Constants for MowBite."""

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
MOWER_MODELS = {
    # the same body on all three, measured on a real one (MowBite's list)
    "yf_nx": {"width": 0.41, "front": 0.43, "rear": 0.18, "blade": 0.18, "bladeAhead": 0.185, "bladeOffset": 0.0},
}

DEFAULT_PORT = 1883
DEFAULT_NAME = "OpenMower"
