# Plan

One lot is one pull request. Each lot says what it needs from the Housecairn
API (`/api/v1`). What is missing there is a pull request to plan in the main
repository, [HouseCairn/housecairn](https://github.com/HouseCairn/housecairn),
before the lot that needs it. The endpoints named below are those of the
OpenAPI schema in `tests/fixtures/openapi.yaml`.

The rule does not change from one lot to the next: Home Assistant calls
Housecairn with a Housecairn token; Housecairn never holds a Home Assistant
token.

## Lot 1: setup and sensors (in 0.1.0)

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

- **Token management, for people: done in Housecairn** (More, Me, API tokens;
  `POST/GET/DELETE /me/tokens/`, session only by design, so Home Assistant never
  manages tokens itself). Nothing left to ask.
- **`GET /me/token/`**, the token that authenticates the request: scopes, homes,
  expiry. Still missing. The integration cannot read its own scopes, so lot 2
  finds out whether the token has `write` by a request that changes nothing
  (see lot 2); with this endpoint it would read them, and it could warn (a
  repair issue) before the token expires instead of after.
- **`GET /homes/{home_id}/summary/`** (or counts on the lists): overdue count,
  count due on a given day, next due date, low stock count, in one request. The
  lists are paged by cursor without a count, so the integration makes three
  requests per update and reads whole lists to count them.
- **The time zone of the instance**, or a `due_on=today` filter decided by the
  server. `overdue=true` uses the date of the instance; "due today" has to use
  the date of Home Assistant.
- **Homes that require a sign-in provider**: done in Housecairn (docs/adr/0057).
  A token created in a session signed in through the provider opens the home
  while it requires that provider or none; lot 3 uses it.

## Lot 2: to-do list with "Done" (in 0.1.0)

One `todo` entity per home: the open occurrences that are overdue, due today or
due in the next 14 days, with their date and their room as the description.
Checking an item completes the occurrence (`POST .../complete/`, today's date, no
cost or note); the coordinator is refreshed right after. Needs a token with
`read` and `write`; with `read` only, the entity exists and has no check box.
Setup and reauthentication say so.

Uses:

- `GET /homes/{home_id}/occurrences/?overdue=true` and
  `?status=open&due_after=<today>&include_hidden=true`, the two lists of the
  sensors (no extra request: the second is read up to 14 days ahead instead of up
  to today). Rows whose `visible_from` is still ahead are left out, as in
  Housecairn; rows past 14 days are left out.
- `GET /homes/{home_id}/rooms/`, once, and again only when a listed task has a
  room not seen yet.
- `POST /homes/{home_id}/occurrences/{occurrence_id}/complete/` with an empty body.
- `GET /homes/{home_id}/occurrences/{occurrence_id}/`, only after a 400 on
  `complete`, to tell "closed meanwhile" from another refusal.
- `POST .../occurrences/00000000-0000-0000-0000-000000000000/undo/`, once per
  setup, as the probe of the `write` scope: the scope is checked before the
  occurrence is looked up, so the answer is 403 without `write` and 404 with it,
  and nothing can change (the occurrence cannot exist). Captured from
  Housecairn itself (`tests/fixtures/api/write_probe_*.json`).
  Any other answer (400, 405, 5xx, 200) leaves the scope unknown: the list stays
  read-only, a warning is logged and the reads go on. Only a refused token (401)
  or an unreachable server stops the setup.

Chosen, and why:

- **No creation, rename, re-dating or deletion from Home Assistant.** The API can
  create a task (`POST /homes/{home_id}/tasks/`) but only without a date, which
  this list would not show; and it can delete a task (`DELETE
  /homes/{home_id}/tasks/{task_id}/`) but that removes the task with all of its
  occurrences, not a line of a list. Neither is "properly" a to-do item. Done is the
  only action.
- **Undone is not offered.** `POST .../undo/` exists, but a done occurrence leaves
  the list, so there is no checked item to uncheck. Lot 3 adds the tasks done
  lately, checked, and undo.
- **Tasks without a date are not listed** (see below; lot 3 lists them).

Missing in the API, by endpoint:

- `POST .../complete/`, `.../postpone/`, `.../skip/`, `.../undo/`: a stable error
  `code`. An occurrence that is already closed answers `400
  {"detail": ["This occurrence is already closed."]}`, a message
  and no code. The integration therefore reads the occurrence
  after any 400 on `complete` (`status` done or skipped means closed meanwhile)
  instead of parsing the message. A code (say `occurrence_closed`) in the body,
  or a 409, would save that request and make the answer reliable.
- `GET /me/token/` (lot 1): the scopes of the token, instead of the probe above.
- `GET /homes/{home_id}/occurrences/`: a filter on undated occurrences (for
  example `due=none`). They sort last and have no `due_before` match, so listing
  them means reading the whole list. Done in Housecairn on the task list
  (`GET /homes/{home_id}/tasks/?due=none`), which lot 3 uses.
- `GET /homes/{home_id}/occurrences/`: the room name and the task notes in each
  row. The room is an id; the names come from `GET /rooms/`. Notes are not in the
  row at all.
- `GET /homes/{home_id}/occurrences/`: an `updated_after` filter, so an update
  reads what changed instead of the whole lists.

## Lot 3: tasks without a date, tasks done lately, report action (in 0.1.0)

Decisions of the maintainer (2026-11-10). The list keeps its 14 days; a read-only
token is still accepted, with the information step.

- **Tasks without a date** are listed after the dated ones, without a date:
  `GET /homes/{home_id}/tasks/?due=none` (one request per update; each row names
  its open occurrence, which "Done" completes). The task list is never read whole.
- **Tasks done in the last seven days** (today and the six days before) are listed,
  checked: `GET /homes/{home_id}/occurrences/?status=done&closed_after=<day>&ordering=recent`
  (one request per update). Unchecking one calls
  `POST .../occurrences/{occurrence_id}/undo/`, with the `write` scope. A 400 has no
  code: the integration reads the occurrence; still done means the next
  occurrence was changed since ("cannot be undone any more"), open means somebody
  took it back already.
- **`housecairn.report`**, an action with a response: `POST /homes/{home_id}/reports/`
  (`title`, at most one of `room`, `item`, `article`), `write` scope. Before
  creating, it reads `GET /homes/{home_id}/reports/?status=open&mine=true` and
  `?status=task&mine=true`: a report of the same person, not closed, with the same
  title (case aside) and the same place is returned instead (`created: false`). Calls
  are serialised per home, so two automations firing together make one report.
  "Not closed" is open or made into a task: Housecairn calls only resolved and
  closed without action closed (`reports.models.CLOSED_STATUSES`).
- **A home that requires a sign-in provider**: a token created in a session signed
  in through that provider opens it (Housecairn docs/adr/0057). A 403
  `sso_required` (token created otherwise, or the provider changed) now asks for
  a new token, with a step (`reauth_sso`) that says why and how to create it.

Requests per update: five (two task lists and the stock for the sensors, the tasks
without a date, the tasks done lately), plus the rooms when one is unknown.

Missing in the API, by endpoint:

- `POST .../undo/`: a stable error `code` (as for `complete`), which would save the
  read of the occurrence after a refusal.
- `GET /homes/{home_id}/reports/`: a filter on several statuses (`status=open,task`)
  or `status=waiting`, which would make the duplicate check one request.
- `POST /homes/{home_id}/reports/`: an idempotency key, or a refusal of a
  duplicate by Housecairn itself; the check is done by the integration, and two
  Home Assistant instances with the same token could still race.
- `GET /me/token/` (lot 1): still the way to know the scopes without the probe.

## Lot 4: calendar

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

## Lot 5: more actions, and events

**Actions** for automations, with a `write` token: complete, postpone and skip
an occurrence, create a task, record a stock movement (reporting a problem is
lot 3).

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
  lot 2, since automations retry. The `complete` call and the client written for
  lot 2 exist already (`HouseCairnClient.complete`); postpone and skip do not.

## Before an announcement

- Brand images (icon and logo) for Home Assistant and HACS; the `brands` check of
  the HACS action is skipped until then.
- Releases with a version tag, so HACS installs a version and not the default
  branch.
- A CI run on the beta of each monthly Home Assistant release.
