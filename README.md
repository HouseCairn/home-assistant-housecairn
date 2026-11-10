# Housecairn for Home Assistant

[![CI](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml?query=branch%3Amain)
[![Validate](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml?query=branch%3Amain)

A Home Assistant integration for [Housecairn](https://github.com/HouseCairn/housecairn),
the self-hosted planner for home maintenance and renovation projects. It shows
what needs doing in a home as Home Assistant sensors and as a to-do list, and
lets you mark a task done from Home Assistant.

> **Status: early development.** Sensors, and a to-do list with "Done". A calendar
> and actions for automations are planned ([docs/plan.md](docs/plan.md)).

## How it connects

Home Assistant calls the Housecairn API (`/api/v1`) with a **Housecairn API
token** that you create in Housecairn and paste into the setup dialog.

- You create the token in Housecairn itself: **More, Me, API tokens**. You name
  it, tick the rights, choose the homes it opens and how long it lasts (30 days,
  90 days or a year); the token is shown once, so copy it into the setup dialog
  of Home Assistant. You can revoke it from the same screen at any time.
- **No Home Assistant token is ever created, asked for or sent to Housecairn.**
- Rights of the token: **Read** is enough for the sensors and the to-do list.
  Add **Write** to be able to mark a task done from Home Assistant. Without
  Write the to-do list is shown but read-only. The token is bound to the homes
  you choose in Housecairn; it cannot see any other.
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
  **API tokens** screen (the current `main`; no tagged release has it yet), and
  a token with the Read right (and Write to mark tasks done) bound to the home
  to show.
- A home that requires signing in through an identity provider cannot be opened
  with an API token, by design of Housecairn: such a home cannot be added.

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
(its own setting) stays hidden in the list too, as in Housecairn. Tasks without a
date are not listed.

Checking an item marks the task **done** in Housecairn (today's date, no cost or
note), and Housecairn creates the next occurrence of a repeating task by itself.
The list is read again right away, without waiting for the next five minutes.
It needs a token with the Write right; without it the list is read-only (Home
Assistant shows no check box).

Nothing else is offered from Home Assistant: no new task, no rename, no new date,
no deletion. Housecairn creates a task without a date (which this list does not
show) and deletes a task with all of its occurrences, which is not what deleting
a line of a to-do list means. Plan and change tasks in Housecairn.

If somebody closed the task in Housecairn meanwhile, or removed it, Home
Assistant says so ("already marked done or skipped in Housecairn") and the list
is refreshed.

### Requests

The integration reads Housecairn every five minutes, with three requests; the
to-do list uses the same two task lists as the sensors. The rooms are read once,
and again only when a listed task is in a room not seen yet. At setup it also
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
