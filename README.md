# Housecairn for Home Assistant

[![CI](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml?query=branch%3Amain)
[![Validate](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml?query=branch%3Amain)

A Home Assistant integration for [Housecairn](https://github.com/HouseCairn/housecairn),
the self-hosted planner for home maintenance and renovation projects. It shows
what needs doing in a home as Home Assistant sensors and as a to-do list, lets you
mark a task done (or take it back) from Home Assistant, and lets an automation
report a problem.

> **Status: early development.** Sensors, a to-do list with "Done", and the
> `housecairn.report` action. A calendar and more actions are planned
> ([docs/plan.md](docs/plan.md)).

## How it connects

Home Assistant calls the Housecairn API (`/api/v1`) with a **Housecairn API
token** that you create in Housecairn and paste into the setup dialog.

- You create the token in Housecairn itself: **More, Me, API tokens**. You name
  it, tick the rights, choose the homes it opens and how long it lasts (30 days,
  90 days or a year); the token is shown once, so copy it into the setup dialog
  of Home Assistant. You can revoke it from the same screen at any time.
- **No Home Assistant token is ever created, asked for or sent to Housecairn.**
- Rights of the token: **Read** is enough for the sensors and the to-do list.
  Add **Write** to mark a task done from Home Assistant, take a "Done" back and
  report a problem. Without Write the to-do list is shown but read-only, and the
  action is refused. The token is bound to the homes you choose in Housecairn; it
  cannot see any other.
- A token expires: when it does, Home Assistant shows a notification asking for a
  new one (see Setup).
- It is stored in the configuration entry of the integration, never written to
  the logs, and redacted from the diagnostics.
- The TLS certificate of the server is verified by default.
- The integration talks to the address you entered and nowhere else. It has no
  telemetry and no dependency beyond Home Assistant itself.

## Requirements

- Home Assistant 2026.10 or later.
- A Housecairn instance reachable from Home Assistant, new enough to have the
  **API tokens** screen, the filter of the tasks without a date and the tokens
  of a home that requires a sign-in provider (the current `main`; no tagged
  release has them yet), and a token with the Read right (and Write to mark
  tasks done and report problems) bound to the home to show.
- A home that requires signing in through a sign-in provider (single sign-on)
  can be added with a token created while signed in through that provider: see
  [A home that requires a sign-in provider](#a-home-that-requires-a-sign-in-provider).

## Installation

With [HACS](https://hacs.xyz):

1. In HACS, open the menu, choose **Custom repositories**, add
   `https://github.com/HouseCairn/home-assistant-housecairn` with the type
   **Integration**.
2. Install **Housecairn**, then restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and pick
   **Housecairn**.

Without HACS, copy `custom_components/housecairn` into the `custom_components`
folder of your Home Assistant configuration and restart.

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
| `room`, `item`, `article` | The identifier in Housecairn of a room, an item or a stock item, to say where. At most one. Optional. |

It never makes a duplicate. When a report of the same person that is not closed
yet (still open, or made into a task) has the same title, whatever the case, and
the same place, nothing is created. The response tells which:

```yaml
report_id: 3f2b0c7e-1d2a-4c5b-9e8f-0a1b2c3d4e5f
created: false   # true when the report was created now
status: open     # or task
```

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
reports waiting per person, and refuses more until some are dealt with.

### Requests

The integration reads Housecairn every five minutes, with five requests: the two
task lists and the stock list of the sensors (the to-do list uses the same two
task lists), the tasks without a date (`due=none`), and the tasks done in the
last seven days. The rooms are read once, and again only when a listed task is
in a room not seen yet. The action reads the reports of the person that are not
closed (two requests), then creates one if needed. At setup it also
sends one harmless request to find out whether the token has the Write right
(an undo of a task that does not exist: Housecairn refuses it without changing
anything). The sensors and the list become unavailable while Housecairn cannot
be reached, and come back on their own.

"Today" is the date in the time zone of Home Assistant, while Housecairn decides
what is overdue in the time zone of its instance. Use the same time zone for
both, or the two sensors may disagree for a few hours around midnight.

## Diagnostics

**Settings > Devices & services > Housecairn > Download diagnostics** gives the
counts and dates the integration read, and whether the last update succeeded.
The token, the address of the instance, the name of the home, the names of rooms
and the titles of tasks and stock items are left out, so the file can be attached
to an issue.

## Changes

See [CHANGELOG.md](CHANGELOG.md).

## Development

```shell
uv sync --locked
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

The tests simulate the Housecairn API with answers captured from Housecairn
itself (`tests/fixtures/api/`); `tests/fixtures/openapi.yaml` is the schema the
client was written against.

## How this project is built

This integration is developed with an AI coding agent, under human review. Each
pull request says which tool was used.

## License

[AGPL-3.0-only](LICENSE), like Housecairn. See [NOTICE](NOTICE).
Copyright (C) 2026 Robvred.
