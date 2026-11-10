"""A small asynchronous client of the Housecairn API v1.

Written against the OpenAPI schema of Housecairn (a copy is in
tests/fixtures/openapi.yaml). It reads with the `read` scope, and closes an
occurrence ("Done") with the `write` scope; the token is bound to the home it shows.

The token is sent in the `Authorization` header and nowhere else: it is never
part of an address, a log line or an exception message.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

import aiohttp

API_PREFIX: Final = "/api/v1"
REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=30)
# The largest page the API serves (core.pagination.DefaultCursorPagination).
PAGE_SIZE: Final = 200
# A list longer than this many pages is cut: the count is then "at least".
MAX_PAGES: Final = 10
# The statuses of an occurrence that is over (schema `OccurrenceStatusEnum`).
CLOSED_STATUSES: Final = frozenset({"done", "skipped"})
# An occurrence that cannot exist: the probe of the `write` scope (see has_write_scope).
NO_OCCURRENCE: Final = "00000000-0000-0000-0000-000000000000"


class HouseCairnError(Exception):
    """Any failure of a call to Housecairn."""


class HouseCairnConnectionError(HouseCairnError):
    """The server could not be reached, or did not answer in time."""


class HouseCairnTlsError(HouseCairnConnectionError):
    """The TLS certificate of the server was refused."""


class HouseCairnAuthError(HouseCairnError):
    """401: the token is invalid, expired or revoked."""


class HouseCairnScopeError(HouseCairnError):
    """403: the token does not have the scope the request needs."""


class HouseCairnHomeLockedError(HouseCairnError):
    """403 `sso_required`: the home requires a sign-in provider; a token never opens it."""


class HouseCairnNotFoundError(HouseCairnError):
    """404: the home or the occurrence does not exist, or the token is not bound to it."""


class HouseCairnRejectedError(HouseCairnError):
    """400: Housecairn refused the change (for example an occurrence already closed).

    The answer carries a message, not a stable code: `detail` is that message, for the
    logs and never for a decision.
    """

    def __init__(self, detail: str) -> None:
        super().__init__("the change was refused")
        self.detail = detail


class HouseCairnResponseError(HouseCairnError):
    """The server answered something the client does not understand."""


@dataclass(frozen=True, slots=True)
class Home:
    """A home (schema `Home`)."""

    id: str
    name: str
    locked: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Home:
        return cls(id=str(data["id"]), name=str(data["name"]), locked=bool(data["locked"]))


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One time a task has to be done (schema `Occurrence`), reduced to what is shown."""

    id: str
    task: str
    task_title: str
    due_on: datetime.date | None
    is_overdue: bool
    status: str
    room: str | None
    visible_from: datetime.date | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Occurrence:
        due = data["due_on"]
        visible = data["visible_from"]
        room = data["room"]
        return cls(
            id=str(data["id"]),
            task=str(data["task"]),
            task_title=str(data["task_title"]),
            due_on=datetime.date.fromisoformat(due) if due else None,
            is_overdue=bool(data["is_overdue"]),
            status=str(data["status"]),
            room=str(room) if room else None,
            visible_from=datetime.date.fromisoformat(visible) if visible else None,
        )

    @property
    def is_closed(self) -> bool:
        """Done or skipped: nothing is left to do."""
        return self.status in CLOSED_STATUSES


@dataclass(frozen=True, slots=True)
class Room:
    """A room (schema `Room`), reduced to its name."""

    id: str
    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Room:
        return cls(id=str(data["id"]), name=str(data["name"]))


@dataclass(frozen=True, slots=True)
class Article:
    """A stock item (schema `Article`), reduced to what is shown."""

    id: str
    name: str
    quantity: Decimal
    threshold: Decimal | None
    unit_label: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Article:
        threshold = data.get("threshold")
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            quantity=Decimal(str(data["quantity"])),
            threshold=Decimal(str(threshold)) if threshold is not None else None,
            unit_label=str(data["unit_label"]),
        )


@dataclass(frozen=True, slots=True)
class Rows[T]:
    """The rows of a list, and whether the list was read to its end."""

    items: list[T]
    complete: bool


def normalize_url(url: str) -> str:
    """The base address of the instance, without a trailing slash.

    Raises ValueError unless it is an http or https address with a host. A path is
    kept: Housecairn may be served under a prefix.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("not an http or https address")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("no query, fragment or credentials in the address")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


class HouseCairnClient:
    """Reads one Housecairn instance with a token, through a shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self._base = normalize_url(url) + API_PREFIX
        self._token = token

    async def homes(self) -> list[Home]:
        """The homes the token is bound to (`GET /homes/`)."""
        rows = await self._list("/homes/", {})
        return [Home.from_api(row) for row in rows.items]

    async def home(self, home_id: str) -> Home:
        """One home (`GET /homes/{home_id}/`)."""
        return Home.from_api(await self._get(f"/homes/{home_id}/", {}))

    async def overdue(self, home_id: str) -> Rows[Occurrence]:
        """Open occurrences past their date, the oldest first (`?overdue=true`).

        "Past" is decided by the server, in the time zone of the instance.
        """
        rows = await self._list(f"/homes/{home_id}/occurrences/", {"overdue": "true"})
        return Rows([Occurrence.from_api(row) for row in rows.items], rows.complete)

    async def open_from(
        self, home_id: str, day: datetime.date, until: datetime.date | None = None
    ) -> Rows[Occurrence]:
        """Open occurrences due on `day` and after, by due date, hidden ones included.

        The list is read only as far as `until` (`day` by default) goes: its first row
        is the next due date, the rows dated `day` are the tasks of the day, and the
        rows up to `until` are what the to-do list shows. Rows past `until` may be
        returned too (the last page is read whole); the caller cuts them.
        """
        last = (until or day).isoformat()
        params = {
            "status": "open",
            "due_after": day.isoformat(),
            "include_hidden": "true",
        }
        rows = await self._list(
            f"/homes/{home_id}/occurrences/",
            params,
            # Undated rows come last: a page that ends on one has no dated row after it.
            keep_going=lambda page: bool(page) and (page[-1].get("due_on") or "9") <= last,
        )
        return Rows([Occurrence.from_api(row) for row in rows.items], rows.complete)

    async def occurrence(self, home_id: str, occurrence_id: str) -> Occurrence:
        """One occurrence (`GET /occurrences/{occurrence_id}/`)."""
        data = await self._request("GET", f"/homes/{home_id}/occurrences/{occurrence_id}/")
        return Occurrence.from_api(data)

    async def complete(self, home_id: str, occurrence_id: str) -> None:
        """Mark an occurrence done today (`POST /occurrences/{occurrence_id}/complete/`).

        Needs the `write` scope. Housecairn creates the next occurrence of a repeating
        task by itself. An occurrence that is already closed is a 400 with a message
        and no stable code: the caller reads the occurrence to tell why.
        """
        await self._request(
            "POST", f"/homes/{home_id}/occurrences/{occurrence_id}/complete/", json={}
        )

    async def has_write_scope(self, home_id: str) -> bool:
        """Whether the token has the `write` scope, without changing anything.

        The API has no endpoint that describes the token (docs/plan.md). The scope is
        checked before the occurrence is looked up, so undoing an occurrence that
        cannot exist answers 403 without `write` and 404 with it.
        """
        try:
            await self._request(
                "POST", f"/homes/{home_id}/occurrences/{NO_OCCURRENCE}/undo/", json={}
            )
        except HouseCairnScopeError:
            return False
        except HouseCairnNotFoundError:
            return True
        raise HouseCairnResponseError("the probe of the write scope was accepted")

    async def rooms(self, home_id: str) -> Rows[Room]:
        """The rooms of the home (`GET /rooms/`)."""
        rows = await self._list(f"/homes/{home_id}/rooms/", {})
        return Rows([Room.from_api(row) for row in rows.items], rows.complete)

    async def low_stock(self, home_id: str) -> Rows[Article]:
        """Stock items at or below their threshold (`GET /articles/?low=true`)."""
        rows = await self._list(f"/homes/{home_id}/articles/", {"low": "true"})
        return Rows([Article.from_api(row) for row in rows.items], rows.complete)

    async def _list(
        self,
        path: str,
        params: dict[str, str],
        *,
        keep_going: Callable[[list[dict[str, Any]]], bool] | None = None,
    ) -> Rows[dict[str, Any]]:
        """Follow the cursor pagination, on the configured address only.

        The `next` link of a page is built by the server from the request it saw; it
        may name another host behind a proxy. Only its `cursor` is reused, so the token
        is never sent anywhere but the configured address.
        """
        query = {**params, "page_size": str(PAGE_SIZE)}
        items: list[dict[str, Any]] = []
        for _page in range(MAX_PAGES):
            data = await self._get(path, query)
            results = data.get("results")
            if not isinstance(results, list):
                raise HouseCairnResponseError("a list without results")
            items.extend(results)
            cursor = _cursor_of(data.get("next"))
            if cursor is None:
                return Rows(items, complete=True)
            if keep_going is not None and not keep_going(results):
                return Rows(items, complete=True)
            query = {**query, "cursor": cursor}
        return Rows(items, complete=False)

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return await self._request("GET", path, params)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        try:
            async with self._session.request(
                method,
                self._base + path,
                params=params,
                json=json,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as response:
                status = response.status
                try:
                    body: Any = await response.json(content_type=None)
                except ValueError:
                    body = None
        except aiohttp.ClientSSLError as exc:
            raise HouseCairnTlsError("TLS certificate refused") from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HouseCairnConnectionError(type(exc).__name__) from exc

        if status == 401:
            raise HouseCairnAuthError("token refused")
        if status == 403:
            if isinstance(body, dict) and body.get("code") == "sso_required":
                raise HouseCairnHomeLockedError("the home requires a sign-in provider")
            raise HouseCairnScopeError("the token lacks the scope this request needs")
        if status == 404:
            raise HouseCairnNotFoundError(path)
        if status == 400:
            raise HouseCairnRejectedError(_detail_of(body))
        if status != 200:
            raise HouseCairnResponseError(f"HTTP {status}")
        if not isinstance(body, dict):
            raise HouseCairnResponseError("not a JSON object")
        return body


def _detail_of(body: Any) -> str:
    """The message of a 400 (`{"detail": ["..."]}`), for the logs only."""
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, list):
            return " ".join(str(part) for part in detail)
        if detail:
            return str(detail)
    return ""


def _cursor_of(link: Any) -> str | None:
    if not link:
        return None
    values = parse_qs(urlsplit(str(link)).query).get("cursor")
    if not values:
        raise HouseCairnResponseError("a next page without cursor")
    return values[0]
