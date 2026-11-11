# Housecairn for Home Assistant

A Home Assistant integration for [Housecairn](https://github.com/HouseCairn/housecairn),
the self-hosted planner for home maintenance and renovation work: see what
needs doing in your home from Home Assistant, and mark it done there.

[![CI](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/ci.yml?query=branch%3Amain)
[![Validate](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/HouseCairn/home-assistant-housecairn/actions/workflows/validate.yml?query=branch%3Amain)
[![HACS: custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
![Home Assistant 2026.10 or later](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-41BDF5.svg)
[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg)](LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HouseCairn&repository=home-assistant-housecairn&category=integration)

No screenshot yet: none has been taken in a real Home Assistant instance.

The full description is in the [guide](docs/guide.md); Housecairn's own
documentation is at <https://docs.housecairn.app>.

## What it does

- **One device per home**, with four sensors: overdue tasks, tasks due today,
  next due date, stock items below their threshold.
- **A to-do list per home**, named **Tasks**: open tasks overdue, due today or
  due in the next 14 days, with their date and room.
- **Mark a task done** by checking it: Housecairn records it today and creates
  the next occurrence of a repeating task.
- **A Housecairn API token, never a Home Assistant token**: limited to the homes
  and rights you choose in Housecairn, revocable there at any time.
- **Reauthentication** when the token expires or is revoked: Home Assistant asks
  for a new one.
- **Diagnostics** without the token, the address, or the names of the home,
  rooms, tasks and stock items.
- English and French.

## Install

1. In HACS, open the top-right menu, choose **Custom repositories**, add
   `https://github.com/HouseCairn/home-assistant-housecairn` with the type
   **Integration** (or use the button above).
2. Install **Housecairn**, then restart Home Assistant.
3. In Housecairn, open **More** > **Me** > **API tokens** and create a token:
   a name (such as "Home Assistant"), the rights **Read** and **Write** (Write
   is needed to mark tasks done; Read alone gives a read-only list), the
   **home** to show, and how long it lasts. Copy the token: it is shown once.
4. In Home Assistant, go to **Settings** > **Devices & services** >
   **Add integration**, pick **Housecairn**, and enter the address of
   Housecairn (such as `https://housecairn.example.com`, with its path if it is
   served under one) and the token. The integration checks both before saving.

Without HACS, copy `custom_components/housecairn` into the `custom_components`
folder of your Home Assistant configuration and restart. Details, including a
token bound to several homes: [Setup](docs/guide.md#setup).

## Requirements

- Home Assistant 2026.10 or later.
- A Housecairn instance reachable from Home Assistant, recent enough to have the
  **API tokens** screen (the current `main`; no release has it yet).
- With the [Housecairn app](https://github.com/HouseCairn/home-assistant-addons)
  for Home Assistant: an address that reaches it without Home Assistant's
  interface, such as its port; ingress addresses only work in a browser.

## Known limits

- **Nothing but "Done" from Home Assistant**: no new task, no rename, no new
  date, no deletion; plan and change tasks in Housecairn.
- **Tasks without a date** are not in the to-do list, nor tasks due more than
  14 days ahead.
- **A home that requires signing in through an identity provider** cannot be
  added: Housecairn refuses API tokens for it, by design.
- **Polling every five minutes** (three requests); the list is read again right
  after a task is marked done.
- **"Today" is the date in Home Assistant's time zone**, while Housecairn decides
  what is overdue in its own: use the same time zone for both.
- **No calendar and no actions for automations yet**: planned in
  [docs/plan.md](docs/plan.md).

## Project status

**Early development, no version released yet.** The integration is at 0.2.0 in
its manifest (sensors, then the to-do list with "Done"), without a tagged
release; Housecairn has no release yet either, and its first version, v0.1.0,
is planned. Install from the default branch, and expect changes.

## Privacy and security

- The integration talks to the address you entered and nowhere else: no
  telemetry, no tracker, no dependency beyond Home Assistant itself.
- The token is stored in the configuration entry only, never written to the
  logs, and redacted from the diagnostics. The TLS certificate of the server is
  verified by default.
- Report a vulnerability as described in Housecairn's
  [SECURITY.md](https://github.com/HouseCairn/housecairn/blob/main/SECURITY.md),
  not in a public issue.

## Contributing

Issues and pull requests are welcome. Contributions follow Housecairn's
[CONTRIBUTING.md](https://github.com/HouseCairn/housecairn/blob/main/CONTRIBUTING.md):
the [Contributor License Agreement](https://github.com/HouseCairn/housecairn/blob/main/CLA.md)
and a `Signed-off-by` line on each commit. AI coding agents start with
Housecairn's [AGENTS.md](https://github.com/HouseCairn/housecairn/blob/main/AGENTS.md)
and this repository's [plan](docs/plan.md). How to run the checks:
[Development](docs/guide.md#development).

This integration is developed with an AI coding agent, under human review. Each
pull request says which tool was used.

## License

Housecairn, by Robvred. Copyright (C) 2026 Robvred.
[AGPL-3.0-only](LICENSE), like Housecairn, with the additional terms of
[NOTICE](NOTICE).
