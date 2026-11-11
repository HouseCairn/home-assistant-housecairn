"""Constants of the Housecairn integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "housecairn"

CONF_HOME_ID: Final = "home_id"

# Tasks and stock change a few times a day: five requests every five minutes are
# plenty, and a new day is picked up within five minutes of midnight.
UPDATE_INTERVAL: Final = timedelta(minutes=5)

# Rows listed in the attributes of a sensor: enough to read on a dashboard, small
# enough for the recorder.
ATTRIBUTE_ROWS: Final = 20

# The to-do list shows what is overdue, what is due today and what comes in the next
# two weeks: far enough to plan a weekend or a week away, near enough that a yearly
# task due next autumn does not sit in the list all year. Tasks without a date come
# after them, whatever the horizon.
TODO_HORIZON: Final = timedelta(days=14)

# The to-do list also shows, checked, the tasks marked done in the last seven days
# (today included), so that a "Done" given by mistake can be taken back.
RECENTLY_DONE: Final = timedelta(days=7)

# The action that reports a problem in Housecairn.
SERVICE_REPORT: Final = "report"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_TITLE: Final = "title"
ATTR_ROOM: Final = "room"
ATTR_ITEM: Final = "item"
ATTR_ARTICLE: Final = "article"
# The entity that saw the problem: its area gives the room, its device the item.
ATTR_ENTITY_ID: Final = "entity_id"
# An area of Home Assistant that gives the room instead of the area of the entity.
ATTR_AREA_ID: Final = "area_id"
# Whether the device of the entity is added as an item when the room has none by its name.
ATTR_CREATE_ITEM: Final = "create_item"
# Housecairn refuses a longer title (reports.models.TITLE_MAX_LENGTH).
REPORT_TITLE_MAX: Final = 200
