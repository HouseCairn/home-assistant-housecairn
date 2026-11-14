# Guide

Everything the integration does, in detail. Installation and a summary are in
the [README](../README.md).

## How it connects

Home Assistant calls the Housecairn API (`/api/v1`) with a **Housecairn API
token** that you create in Housecairn and paste into the setup dialog.

- You create the token in Housecairn itself: **More, Me, API tokens, Create a token**. You name
  it, tick the rights, choose the homes it opens and how long it lasts (30 days,
  90 days or a year); the token is shown once, so copy it into the setup dialog
  of Home Assistant. You can revoke it from the same screen at any time.
- **No Home Assistant token is ever created, asked for or sent to Housecairn.**
- Rights of the token: **Read** is enough for the sensors and the to-do list.
  Add **Write** to mark a task done from Home Assistant, take a "Done" back and
  report a problem. Without Write the to-do list is shown but read-only, and
  the action is refused. The token is bound to the homes
  you choose in Housecairn; it cannot see any other.
- A token expires: when it does, Home Assistant shows a notification asking for a
  new one (see [Setup](#setup)).
- It is stored in the configuration entry of the integration, never written to
  the logs, and redacted from the diagnostics.
- The TLS certificate of the server is verified by default.
- The integration talks to the address you entered and nowhere else. It has no
  telemetry and no dependency beyond Home Assistant itself.

## Requirements

- Home Assistant 2026.10 or later.
- A Housecairn instance reachable from Home Assistant, version 0.1.0 or later
  (it has the **API tokens** screen, the filter of the tasks without a date and
  the tokens of a home that requires a sign-in provider), and a token with the
  Read right (and Write to mark tasks done and report problems) bound to the
  home to show.
- A home that requires signing in through a sign-in provider (single sign-on)
  can be added with a token created while signed in through that provider: see
  [A home that requires a sign-in provider](#a-home-that-requires-a-sign-in-provider).

## Setup

Enter the address of Housecairn (for example `https://housecairn.example.com`)
and the API token. The integration checks both with a real call before saving.
The address may contain a path when Housecairn is served under a prefix
(`https://example.com/housecairn/`): the integration keeps it in every request.

The integration then finds out, without changing anything, whether the token has
the Write right. If it has not, the dialog says that the to-do list will be
read-only and that a token with Read and Write is needed to mark tasks done;
you can add the home anyway.

Each home is a separate entry, identified by the UUID of the home: the same
home cannot be added twice. If the token is bound to several homes, the dialog
asks which one; add the others by setting up the integration again, with the
same token or another one.

When the token expires or is revoked, Home Assistant shows a notification
asking for a new one; the new token must be bound to the same home, with the
Read right and, to mark tasks done, the Write right (the dialog says so again if
the new token has no Write right).

### A home that requires a sign-in provider

In Housecairn an owner can require that a home be opened only by people signed in
through a given sign-in provider. A token opens such a home only if it was created
in a session signed in through that provider:

1. In Housecairn, open **More, Me, API tokens, Create a token**.
2. If you signed in with a password or a passkey, the home is listed but cannot be
   ticked: use **Continue with** and the name of the provider next to it. You sign
   in through the provider and come back to the form.
3. Tick the home, the rights and the lifetime, and create the token.

The token remembers the provider and opens the home as long as the home requires
that provider, or no provider at all. If the token was created otherwise, or if an
owner later requires another provider, Housecairn refuses it (`sso_required`):
Home Assistant then asks for a new token and says why, and the steps above give
one.

## What you get

One device per home, with these sensors:

| Sensor | State | Attributes |
| --- | --- | --- |
| Overdue tasks | Number of open tasks past their date | `tasks` (title and date, first 20), `complete` |
| Tasks due today | Number of open tasks due today | `tasks`, `complete`, `day` |
| Next due date | Date of the next open task, today included | `task` |
| Stock items below threshold | Number of stock items at or below their threshold | `items` (name, quantity, threshold, unit, first 20), `complete` |

`complete` is false when a list was too long to read in full (more than 2,000
rows): the count is then a minimum.

### To-do list

One list per home, named **Tasks**. It shows the open tasks that are overdue, due
today or due in the next 14 days, oldest first, each with its date and, when the
task has one, its room as the description. Why 14 days: far enough to plan a
week or a weekend, near enough that a yearly task due next autumn does not sit in
the list all year. A task that Housecairn hides until a few days before its date
(its own setting) stays hidden in the list too, as in Housecairn. The open tasks
**without a date** come after them, with no date.

Below, checked, come the tasks **marked done in the last seven days** (today and
the six days before), the latest first. Skipped tasks are not among them.

Checking an item marks the task **done** in Housecairn (today's date, no cost or
note), and Housecairn creates the next occurrence of a repeating task by itself.
**Unchecking** a task done in the last seven days takes that "Done" back
(Housecairn's undo): the task is open again, and the next occurrence of a
repeating task is removed. Housecairn refuses it when that next occurrence has
been changed since (moved, noted or done); Home Assistant then says so. The list
is read again right away in both cases, without waiting for the next five
minutes. Both need a token with the Write right; without it the list is
read-only (Home Assistant shows no check box).

A repeating task done lately is listed twice under the same title: its next
occurrence (open) and the one just done (checked). Calling `todo.update_item` with
the title takes the first, the open one, and fails when asked to uncheck it: use
the `uid` of the item (the automation and the Home Assistant interface already do).

Nothing else is offered from Home Assistant: no new task, no rename, no new date,
no deletion. Housecairn deletes a task with all of its occurrences, which is not
what deleting a line of a to-do list means. Plan and change tasks in Housecairn.

If somebody closed the task in Housecairn meanwhile, or removed it, Home
Assistant says so ("already marked done or skipped in Housecairn") and the list
is refreshed.

### Action: report a problem

`housecairn.report` creates a report in Housecairn, as if the person who owns
the token had used the Report screen. It needs a token with the Write right;
without it the action fails and says so.

| Field | |
| --- | --- |
| `config_entry_id` | The home (its entry in Home Assistant). Required. |
| `title` | What is wrong, 200 characters at most. Required. |
| `room`, `item`, `article` | The identifier in Housecairn of a room, an item or a stock item, to say where. At most one. Optional; when given, it comes before the three fields below. |
| `entity_id` | The entity that saw the problem: the place is then found from it (see [Where the report goes](#where-the-report-goes)). Optional. |
| `area_id` | An area of Home Assistant whose room is used instead of the area of the entity. Optional. |
| `create_item` | Add the device of the entity to the room when the room has no item with its name. Optional, false by default (true in the blueprints). |

It never makes a duplicate. When a report of the same person that is not closed
yet (still open, or made into a task) has the same title, whatever the case, and
the same place, nothing is created. The response tells which:

```yaml
report_id: 3f2b0c7e-1d2a-4c5b-9e8f-0a1b2c3d4e5f
created: false     # true when the report was created now
status: open       # or task
room_match: matched  # or none, ambiguous
item_match: created  # or linked, matched, none, ambiguous
```

`room_match` and `item_match` say how the place was found from `entity_id` (see
below); both are `none` when an identifier was given or nothing was looked up.

Example: the battery of a smoke detector has been low for an hour.

```yaml
automation:
  - alias: "Smoke detector battery low"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.hallway_smoke_detector_battery
        below: 20
        for: "01:00:00"
    actions:
      - action: housecairn.report
        data:
          config_entry_id: 0123456789abcdef0123456789abcdef
          title: "Smoke detector battery low"
          # The identifier of the detector in Housecairn, if it is an item there.
          item: 3f2b0c7e-1d2a-4c5b-9e8f-0a1b2c3d4e5f
        response_variable: report
      - action: persistent_notification.create
        data:
          message: >-
            {{ 'Reported in Housecairn' if report.created
               else 'Already reported in Housecairn' }}
```

The automation editor offers the home in a list. Housecairn counts at most twenty
waiting reports per person and per home, and refuses more until some are dealt with.

### Where the report goes

With `entity_id`, nothing has to be looked up by hand: the report goes where the
entity is. Say a boiler in Home Assistant is in the area **Kitchen**, and its
fault sensor turns on. The report goes to the room **Kitchen** of the home in
Housecairn, on the item **Boiler** of that room; if the room has no such item and
`create_item` is true, the boiler is added to the room first.

1. **The room** is the area of the entity, or else the area of its device. It is
   matched to a room of the home by name, whatever the case, the accents and the
   spaces (the area "Entrée" matches the room "entree"). `area_id` gives another
   area. No room is ever created in Housecairn: when no room has that name, or
   several have, the report has no place (`room_match: none` or `ambiguous`).
2. **The item** is the device of the entity, found in this order:
   - the item already linked to that device (`linked`). The link is kept by
     Home Assistant, in the storage of the integration; it holds when the device
     or the item is renamed, and is forgotten when the item was deleted in
     Housecairn, the search then starting again;
   - an item of the room with the name of the device, the name you gave it in
     Home Assistant if any (`matched`), with the same comparison as the room;
   - with `create_item`, a new piece of equipment in the room, named after the
     device, with its manufacturer as the brand and its model (`created`).
   Two items of the room with that name: none is chosen and none is added
   (`ambiguous`). An entity without a device has no item; without a room, only
   an item already linked to the device is used.
3. The report then goes to the item, which says the room, or to the room alone.

What it needs:

- the **same name** for the area in Home Assistant and the room in Housecairn;
- a token with the **Write** right, as for every report, and, to add a device,
  a person who may change the home (an owner or a member: a viewer can report
  but not add items, and the report then goes to the room alone).

Nothing is changed in Home Assistant: no area, device or entity is created or
edited, and the items of Housecairn do not become devices of Home Assistant.

Example: a leak sensor on for five minutes, wherever it is.

```yaml
automation:
  - alias: "Leak"
    triggers:
      - trigger: state
        entity_id: binary_sensor.boiler_leak
        to: "on"
        for: "00:05:00"
    actions:
      - action: housecairn.report
        data:
          config_entry_id: 0123456789abcdef0123456789abcdef
          title: "Leak: {{ trigger.to_state.name }}"
          entity_id: "{{ trigger.entity_id }}"
          create_item: true
```

### Blueprints

Two blueprints write that automation for you. Import one with the button, or in
**Settings > Automations & scenes > Blueprints > Import blueprint** with the
address below it, then create an automation from it: choose the home and the
entities, and the rest has defaults.

**Report when an entity stays in a state** (a leak, a `problem` sensor, a boiler
fault): the state (`on` by default) and how long (five minutes by default).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FHouseCairn%2Fhome-assistant-housecairn%2Fmain%2Fblueprints%2Fautomation%2Fhousecairn%2Freport_on_state.yaml)

```text
https://raw.githubusercontent.com/HouseCairn/home-assistant-housecairn/main/blueprints/automation/housecairn/report_on_state.yaml
```

**Report when a value stays below a threshold** (a battery level): the threshold
(20 by default) and how long (five minutes by default).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FHouseCairn%2Fhome-assistant-housecairn%2Fmain%2Fblueprints%2Fautomation%2Fhousecairn%2Freport_below_threshold.yaml)

```text
https://raw.githubusercontent.com/HouseCairn/home-assistant-housecairn/main/blueprints/automation/housecairn/report_below_threshold.yaml
```

Both also take a title (by default "Problem detected:" or "Low:" and the name of
the entity), an area that forces the room, and "Add the device if missing" (on by
default). They run one report after the other (`mode: queued`), and a report that
is not closed yet is not made again.

To try an automation made from a blueprint, put the entity in the wanted state
(**Developer tools > States**, set the state, then wait for the duration), not
**Run actions**: run by hand, the automation has no entity that triggered it, so
it stops with the message "Run by hand: nothing is reported" and creates nothing.

### Requests

The integration reads Housecairn every five minutes, with five requests: the two
task lists and the stock list of the sensors (the to-do list uses the same two
task lists), the tasks without a date (`due=none`), and the tasks done in the
last seven days. The rooms are read once, and again only when a listed task is
in a room not seen yet. The action reads the reports of the person that are not
closed (two requests), then creates one if needed. With `entity_id`, it also
reads the rooms (kept one minute), the linked item or the items of the room, and
adds the item if asked: never between two calls, never on a schedule. At setup it also
sends one harmless request to find out whether the token has the Write right
(an undo of a task that does not exist: Housecairn refuses it without changing
anything). The sensors and the list become unavailable while Housecairn cannot
be reached, and come back on their own.

"Today" is the date in the time zone of Home Assistant, while Housecairn decides
what is overdue in the time zone of its instance. Use the same time zone for
both, or the two sensors may disagree for a few hours around midnight.

## Diagnostics

**Settings > Devices & services > Housecairn > Download diagnostics** gives the
counts and dates the integration read, whether the last update succeeded, and
how many devices are linked to an item (a count, without any name or identifier).
The token, the address of the instance, the name of the home, the names of rooms
and the titles of tasks and stock items are left out, so the file can be attached
to an issue.

## Development

```shell
uv sync --locked --python 3.14   # as in CI; under 3.15, some dependencies have no wheel
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

The tests simulate the Housecairn API with answers captured from Housecairn
itself (`tests/fixtures/api/`); `tests/fixtures/openapi.yaml` is the schema the
client was written against.
