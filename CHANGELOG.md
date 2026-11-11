# Changelog

The versions of the integration, the newest first. The plan of each lot is in
[docs/plan.md](docs/plan.md).

## Unreleased

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
