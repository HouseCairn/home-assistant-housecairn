# Plan

One lot is one pull request. Each lot says what it needs from the Housecairn
API (`/api/v1`). What is missing there is a pull request to plan in the main
repository, [HouseCairn/housecairn](https://github.com/HouseCairn/housecairn),
before the lot that needs it. The endpoints named below are those of the
OpenAPI schema in `tests/fixtures/openapi.yaml`.

The rule does not change from one lot to the next: Home Assistant calls
Housecairn with a Housecairn token; Housecairn never holds a Home Assistant
token.

## Lot 1: setup and sensors (this version)

Config flow (address, token, TLS verified by default, one entry per home,
reauthentication), a coordinator, four sensors per home, diagnostics, English
and French.

Uses, with a `read` token:

- `GET /homes/` (setup: the homes of the token) and `GET /homes/{home_id}/`
  (reauthentication);
- `GET /homes/{home_id}/occurrences/?overdue=true`;
- `GET /homes/{home_id}/occurrences/?status=open&due_after=<today>&include_hidden=true`;
- `GET /homes/{home_id}/articles/?low=true`.

Missing in the API, by endpoint:

- **Token management, for people.** Tokens are issued only by
  `apitokens.services.issue_token`: there is no screen, no endpoint and no
  management command to create one, and the admin site can list and revoke
  only. Until the "data and API" lot of Housecairn adds them, a person cannot
  create the token this integration asks for. Needed: a screen, and
  `POST/GET/DELETE /me/tokens/` (create with name, scopes, homes and expiry;
  list; revoke).
- **`GET /me/token/`**, the token that authenticates the request: scopes, homes,
  expiry. The integration could then check the scope at setup without guessing
  from a 403, and warn (a repair issue) before the token expires instead of
  after.
- **`GET /homes/{home_id}/summary/`** (or counts on the lists): overdue count,
  count due on a given day, next due date, low stock count, in one request. The
  lists are paged by cursor without a count, so the integration makes three
  requests per update and reads whole lists to count them.
- **The time zone of the instance**, or a `due_on=today` filter decided by the
  server. `overdue=true` uses the date of the instance; "due today" has to use
  the date of Home Assistant.
- **Homes that require a sign-in provider** answer 403 `sso_required` to any
  token (`homes.sso.signed_in_providers`). That is a decision of Housecairn
  (docs/adr/0021), not a gap; the integration refuses such a home and says why.
  If Home Assistant must show such homes, Housecairn needs a token rule for them.

## Lot 2: to-do lists with "Done"

One `todo` entity per home (later perhaps per room or per person): the open
occurrences, and the recently closed ones in the completed section. Checking an
item completes the occurrence; unchecking it undoes the completion. Needs a
token with `read` and `write`.

Available: `GET /homes/{home_id}/occurrences/` (`status`, `closed_after`),
`POST /homes/{home_id}/occurrences/{occurrence_id}/complete/` and `.../undo/`,
`POST /homes/{home_id}/tasks/` (create with a title only),
`PATCH` and `DELETE /homes/{home_id}/tasks/{task_id}/`.

Missing in the API, by endpoint:

- `GET /homes/{home_id}/occurrences/`: an `updated_after` filter, so an update
  reads what changed instead of the whole list;
- `GET /homes/{home_id}/occurrences/`: the task `notes` (or a short
  description) and the room name in each row, for the item description,
  without one request per task;
- `POST .../complete/` is safe to retry: a second call on the same occurrence
  is refused because it is no longer open (`tasks.services._require_open`). A
  stable error `code` for that refusal would let the integration treat it as
  done without parsing a message;
- `GET /me/token/` (lot 1), to tell the person at setup that the token lacks
  `write` instead of failing at the first "Done".

## Lot 3: calendar

One `calendar` entity per home: each occurrence is an all-day event on its due
date. Needs `read`.

Available: `GET /homes/{home_id}/occurrences/` with `due_after` and
`due_before`, which is what `async_get_events` asks for.

Missing in the API, by endpoint:

- `GET /api/v1/calendar/` refuses every token (session only, by design of
  `calendar.api`): the integration builds events from the occurrences instead.
  Nothing to change if that stays acceptable.
- Occurrences have no time of day and no duration usable by a calendar
  (`estimated_minutes` is on the task only): events stay all-day. A
  `estimated_minutes` field in occurrence rows would allow a duration.
- The future occurrences of a repeating task do not exist until the previous
  one is done; the calendar can show only the next one of each task. Needed if
  more is wanted: `GET /homes/{home_id}/occurrences/forecast/?until=<date>`,
  computed by the recurrence engine, read only.

## Lot 4: actions and events

**Actions** for automations, with a `write` token: complete, postpone and skip
an occurrence, create a task, record a stock movement, report a problem.

Available: `POST .../occurrences/{occurrence_id}/complete/`, `.../postpone/`,
`.../skip/`, `POST /homes/{home_id}/tasks/`, `POST /homes/{home_id}/movements/`,
`POST /homes/{home_id}/reports/`.

**Events** from Home Assistant to Housecairn, with an `events` token: a sensor
(low battery, leak, threshold) arms a task, as the J3 blueprint and
`rest_command` do.

Available: `POST /homes/{home_id}/events/` (`kind`, `payload`), which records the
event.

Missing in the API, by endpoint:

- `POST /homes/{home_id}/events/`: events are recorded only; arming a task from
  an event comes with J3 of Housecairn (`events.services`). The rule that links a
  `kind` to a task, and its endpoint, do not exist yet.
- Scopes: one entry would hold a token with `read`, `write` and `events`, or two
  tokens. Scopes do not imply each other, so one token with the three scopes is
  enough; `GET /me/token/` (lot 1) is what lets the integration offer only the
  actions its token allows.
- `POST .../complete/`, `.../postpone/`, `.../skip/`: the stable error codes of
  lot 2, since automations retry.

## Before an announcement

- Brand images (icon and logo) for Home Assistant and HACS; the `brands` check of
  the HACS action is skipped until then.
- Releases with a version tag, so HACS installs a version and not the default
  branch.
- A CI run on the beta of each monthly Home Assistant release.
