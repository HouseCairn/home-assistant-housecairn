# Changelog

The versions of the integration, the newest first. The plan of each lot is in
[docs/plan.md](docs/plan.md).

## Unreleased

- **The two blueprints no longer fail when the automation is run by hand.**
  "Run actions" (or `automation.trigger`) gives a `trigger` with no `to_state` and
  no `entity_id`, and the title template failed with `'dict object' has no
  attribute 'to_state'`. The automation now stops with "Run by hand: nothing is
  reported", and reports nothing. The normal trigger is unchanged. To try an
  automation, put the entity in the wanted state (Developer tools > States).

## 0.2.0

A feature version: report a problem from the entity that saw it, with the room
found by its area and the item by its device, and two blueprints to start from.
Needs Housecairn 0.1.0 or later.

- **`housecairn.report` finds the place from the entity** that saw the problem
  (`entity_id`): the room of the home with the name of the area of the entity
  (or of its device), whatever the case, accents and spaces, and the item of
  that room with the name of the device. With `create_item`, the device is added
  to the room as a piece of equipment, with its manufacturer and model, when the
  room has no item by that name. Each device is linked to its item in the
  storage of the integration, so renaming either keeps the link; an item deleted
  in Housecairn is looked for again. `area_id` forces the room. No room is ever
  created, and nothing is changed in Home Assistant. The answer adds
  `room_match` and `item_match`. The `room`, `item` and `article` identifiers
  still come first.
- **Two blueprints** in `blueprints/automation/housecairn/`: report when an
  entity stays in a state (`on` for five minutes by default), and when a value
  stays below a threshold (20 for five minutes by default).
- Diagnostics count the devices linked to an item, without names.

## 0.1.1

A fix version: the integration logo shows in Home Assistant 2026.3 and later, once
HACS has updated the integration and Home Assistant has restarted. Needs
Housecairn 0.1.0 or later.

- **Logo in Home Assistant**: the integration ships its icon and logo (light and
  dark) in `custom_components/housecairn/brand/`, which Home Assistant 2026.3
  and later shows without an entry in `home-assistant/brands`. Rendered from the
  Housecairn artwork by `scripts/brand.py`.

## 0.1.0

The first version, a test version: it brings lots 1 to 3 of the plan. Needs
Housecairn 0.1.0 or later.

- Setup with the address of Housecairn and a Housecairn API token, created on
  the API tokens screen of Housecairn; one entry per home, reauthentication. An
  address with a path (Housecairn served under a prefix) is kept in every
  request.
- Sensors per home: overdue tasks, tasks due today, next due date, stock items
  below their threshold. Diagnostics without the token or the content of the
  home.
- One to-do list per home: the open tasks overdue, due today or due in the next
  14 days, then the open tasks **without a date**, and, checked, the tasks
  **marked done in the last seven days**. Checking a task marks it done in
  Housecairn; unchecking one takes the "Done" back, and when Housecairn refuses,
  because the next occurrence of the task was changed since, Home Assistant
  says so. Both need the Write right; without it the list is read-only, which
  the setup says.
- The **`housecairn.report`** action reports a problem in a home from an
  automation (title, and at most one room, item or stock item). It never makes a
  duplicate of a report of the same person that is not closed yet, and returns
  the identifier of the report (`response_variable`). Write right.
- A home that **requires a sign-in provider** can be added with a token created
  while signed in through that provider. When Housecairn answers `sso_required`
  (a token created otherwise, or the provider changed), Home Assistant asks for
  a new token and says why.
- Polling every five minutes, five requests per update.
