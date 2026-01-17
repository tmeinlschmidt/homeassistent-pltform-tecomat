"""Constants for the Tecomat integration."""
from typing import Final

DOMAIN: Final = "tecomat"
DEFAULT_PORT: Final = 5010
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds

# Platforms we support
PLATFORMS: Final = ["light", "cover", "binary_sensor", "sensor", "switch", "button"]

# Configuration keys
CONF_VARIABLES: Final = "variables"
CONF_AUTO_DISCOVER: Final = "auto_discover"

# Entity configuration keys (for options flow)
CONF_LIGHTS: Final = "lights"
CONF_COVERS: Final = "covers"
CONF_COVER_UP_SUFFIX: Final = "cover_up_suffix"
CONF_COVER_DOWN_SUFFIX: Final = "cover_down_suffix"
CONF_BINARY_SENSORS: Final = "binary_sensors"
CONF_SENSORS: Final = "sensors"
CONF_SWITCHES: Final = "switches"
CONF_BUTTONS: Final = "buttons"

# Default suffixes for cover detection
DEFAULT_COVER_UP_SUFFIX: Final = "_UP"
DEFAULT_COVER_DOWN_SUFFIX: Final = "_DN"

# PLC data types
PLC_TYPE_BOOL: Final = "BOOL"
PLC_TYPE_INT: Final = "INT"
PLC_TYPE_SINT: Final = "SINT"
PLC_TYPE_USINT: Final = "USINT"
PLC_TYPE_DINT: Final = "DINT"
PLC_TYPE_UDINT: Final = "UDINT"
PLC_TYPE_REAL: Final = "REAL"
PLC_TYPE_TIME: Final = "TIME"
PLC_TYPE_TOD: Final = "TOD"
PLC_TYPE_DATE: Final = "DATE"
PLC_TYPE_DT: Final = "DT"
PLC_TYPE_STRING: Final = "STRING"
