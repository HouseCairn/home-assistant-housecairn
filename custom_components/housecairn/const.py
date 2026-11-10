"""Constants of the Housecairn integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "housecairn"

CONF_HOME_ID: Final = "home_id"

# Tasks and stock change a few times a day: three requests every five minutes are
# plenty, and a new day is picked up within five minutes of midnight.
UPDATE_INTERVAL: Final = timedelta(minutes=5)

# Rows listed in the attributes of a sensor: enough to read on a dashboard, small
# enough for the recorder.
ATTRIBUTE_ROWS: Final = 20
