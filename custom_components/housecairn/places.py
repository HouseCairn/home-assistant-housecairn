"""Where a problem seen by Home Assistant is in Housecairn: a room, and an item in it.

Everything starts from the entity that fired the automation:

- the **room** is the Home Assistant area of the entity, or else of its device, matched
  to a room of the home by name (case, accents and runs of white space aside). No room
  is ever created in Housecairn: no match, or several, means no room.
- the **item** is the device of the entity. It is, in this order: the item remembered
  for that device (the link survives a rename on either side, and is dropped when the
  item was deleted in Housecairn); an item of that room with the name of the device; or,
  when asked, a new piece of equipment in that room, named after the device, with its
  manufacturer and model. Several items with that name in the room means none.

Nothing is changed in Home Assistant: no area, device or entity is created or edited.
The rooms are read only when the action runs, and kept a minute.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .api import (
    ITEM_TEXT_MAX,
    HouseCairnClient,
    HouseCairnNotFoundError,
    HouseCairnRejectedError,
    HouseCairnScopeError,
    Item,
    Room,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The rooms of a home change rarely; reading them once a minute at most is plenty.
ROOMS_TTL: Final = 60.0
STORAGE_VERSION: Final = 1


class RoomMatch(StrEnum):
    """How the room of a report was found."""

    MATCHED = "matched"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


class ItemMatch(StrEnum):
    """How the item of a report was found."""

    LINKED = "linked"
    MATCHED = "matched"
    CREATED = "created"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class Place:
    """The room and the item found for a report, and how."""

    room: str | None = None
    item: str | None = None
    room_match: RoomMatch = RoomMatch.NONE
    item_match: ItemMatch = ItemMatch.NONE


def normalize(name: str) -> str:
    """A name as compared: without case, accents, or runs of white space."""
    decomposed = unicodedata.normalize("NFKD", name)
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(bare.casefold().split())


def store_key(entry_id: str) -> str:
    """The storage key of the device links of one config entry."""
    return f"{DOMAIN}.{entry_id}.item_links"


type Device = dr.DeviceEntry | dr.ChildDeviceEntry


def _device_name(device: Device) -> str | None:
    name = (device.name_by_user or device.name or "").strip()
    return name or None


def _cut(text: str | None) -> str:
    return " ".join((text or "").split())[:ITEM_TEXT_MAX].strip()


class PlaceFinder:
    """Finds the place of a report for one home. Calls are serialised by the caller."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, client: HouseCairnClient, home_id: str
    ) -> None:
        self._hass = hass
        self._client = client
        self._home_id = home_id
        self._store: Store[dict[str, dict[str, str]]] = Store(
            hass, STORAGE_VERSION, store_key(entry_id)
        )
        self._links: dict[str, str] | None = None
        self._rooms: list[Room] = []
        self._rooms_read_at: float | None = None

    async def links(self) -> dict[str, str]:
        """Device id to item id, loaded once from storage."""
        if self._links is None:
            data = await self._store.async_load()
            self._links = dict((data or {}).get("devices", {}))
        return self._links

    async def _save(self) -> None:
        await self._store.async_save({"devices": dict(await self.links())})

    async def find(self, entity_id: str | None, area_id: str | None, create_item: bool) -> Place:
        """The room and item for an entity, `area_id` forcing the area when given."""
        entities = er.async_get(self._hass)
        devices = dr.async_get(self._hass)
        entity = entities.async_get(entity_id) if entity_id else None
        device = devices.async_get(entity.device_id) if entity and entity.device_id else None
        if not area_id:
            area_id = (entity.area_id if entity else None) or (device.area_id if device else None)

        room, room_match = await self._room(area_id)
        if device is None:
            return Place(room=room, room_match=room_match)

        links = await self.links()
        linked = links.get(device.id)
        if linked is not None:
            try:
                item = await self._client.item(self._home_id, linked)
            except HouseCairnNotFoundError:
                # Deleted in Housecairn: forget it and look again.
                del links[device.id]
                await self._save()
            else:
                return Place(
                    room=room, item=item.id, room_match=room_match, item_match=ItemMatch.LINKED
                )

        name = _device_name(device)
        if room is None or name is None:
            return Place(room=room, room_match=room_match)

        # Compared as cut for creation, so a long name finds the item it created.
        wanted = normalize(_cut(name))
        rows = await self._client.room_items(self._home_id, room)
        same = [item for item in rows.items if normalize(item.name) == wanted]
        if len(same) > 1:
            return Place(room=room, room_match=room_match, item_match=ItemMatch.AMBIGUOUS)
        if same:
            return await self._linked(device, same[0], room, room_match, ItemMatch.MATCHED)
        if not create_item or not rows.complete:
            return Place(room=room, room_match=room_match)

        # A child device (one channel of a device) has no maker of its own: its parent's.
        maker = (
            device
            if isinstance(device, dr.DeviceEntry)
            else dr.async_get(self._hass).async_get(device.parent_device_id)
        )
        if maker is not None and not isinstance(maker, dr.DeviceEntry):
            maker = None
        try:
            created = await self._client.create_item(
                self._home_id,
                room,
                _cut(name),
                brand=_cut(maker.manufacturer if maker else None),
                model=_cut(maker.model if maker else None),
            )
        except (HouseCairnRejectedError, HouseCairnScopeError) as exc:
            # A viewer of the home may report but not add an item; a name Housecairn
            # refuses. The report is what matters: it goes to the room alone.
            _LOGGER.warning("Housecairn did not add the device as an item (%s)", type(exc).__name__)
            return Place(room=room, room_match=room_match)
        return await self._linked(device, created, room, room_match, ItemMatch.CREATED)

    async def _linked(
        self,
        device: Device,
        item: Item,
        room: str,
        room_match: RoomMatch,
        how: ItemMatch,
    ) -> Place:
        (await self.links())[device.id] = item.id
        await self._save()
        return Place(room=room, item=item.id, room_match=room_match, item_match=how)

    async def _room(self, area_id: str | None) -> tuple[str | None, RoomMatch]:
        area = ar.async_get(self._hass).async_get_area(area_id) if area_id else None
        if area is None:
            return None, RoomMatch.NONE
        wanted = normalize(area.name)
        same = [room for room in await self._read_rooms() if normalize(room.name) == wanted]
        if len(same) > 1:
            return None, RoomMatch.AMBIGUOUS
        if not same:
            return None, RoomMatch.NONE
        return same[0].id, RoomMatch.MATCHED

    async def _read_rooms(self) -> list[Room]:
        now = time.monotonic()
        if self._rooms_read_at is None or now - self._rooms_read_at > ROOMS_TTL:
            self._rooms = (await self._client.rooms(self._home_id)).items
            self._rooms_read_at = now
        return self._rooms

    async def async_remove(self) -> None:
        """Forget every link: the config entry is removed."""
        await self._store.async_remove()
