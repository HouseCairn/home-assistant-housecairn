# Housecairn for Home Assistant

[![CI](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml?query=branch%3Amain)
[![Validate](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml?query=branch%3Amain)

A Home Assistant integration for [Housecairn](https://github.com/HouseCairn/housecairn),
the self-hosted planner for home maintenance and renovation projects. It shows
what needs doing in a home as Home Assistant sensors.

> **Status: early development.** This first version only reads. Task lists with
> "Done", a calendar and actions for automations are planned
> ([docs/plan.md](docs/plan.md)).

## How it connects

Home Assistant calls the Housecairn API (`/api/v1`) with a **Housecairn API
token** that you create in Housecairn and paste into the setup dialog.

- **No Home Assistant token is ever created, asked for or sent to Housecairn.**
- The token needs the `read` scope only, and is bound to the homes you choose
  in Housecairn. It cannot change anything.
- It is stored in the configuration entry of the integration, never written to
  the logs, and redacted from the diagnostics.
- The TLS certificate of the server is verified by default.
- The integration talks to the address you entered and nowhere else. It has no
  telemetry and no dependency beyond Home Assistant itself.

## Requirements

- Home Assistant 2026.10 or later.
- A Housecairn instance reachable from Home Assistant, and an API token with the
  `read` scope bound to the home to show.
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

Each home is a separate entry, identified by the UUID of the home: the same
home cannot be added twice. If the token is bound to several homes, the dialog
asks which one; add the others by setting up the integration again, with the
same token or another one.

When the token expires or is revoked, Home Assistant shows a notification
asking for a new one; the new token must be bound to the same home.

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

The integration reads Housecairn every five minutes, with three requests. The
sensors become unavailable while Housecairn cannot be reached, and come back on
their own.

"Today" is the date in the time zone of Home Assistant, while Housecairn decides
what is overdue in the time zone of its instance. Use the same time zone for
both, or the two sensors may disagree for a few hours around midnight.

## Diagnostics

**Settings > Devices & services > Housecairn > Download diagnostics** gives the
counts and dates the integration read, and whether the last update succeeded.
The token, the address of the instance, the name of the home and the titles of
tasks and stock items are left out, so the file can be attached to an issue.

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
