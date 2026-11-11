# Changelog

The versions of the integration, the newest first. The plan of each lot is in
[docs/plan.md](docs/plan.md).

## 0.3.0

Needs a Housecairn instance with the filter of the tasks without a date and the
tokens of a home that requires a sign-in provider (the current `main`).

### Added

- The to-do list shows the open tasks **without a date**, after the dated ones.
- The to-do list shows, checked, the tasks **marked done in the last seven days**.
  Unchecking one takes the "Done" back in Housecairn (Write right). When
  Housecairn refuses, because the next occurrence of the task was changed since,
  Home Assistant says so.
- The **`housecairn.report`** action reports a problem in a home from an
  automation (title, and at most one room, item or stock item). It never makes a
  duplicate of a report of the same person that is not closed yet, and returns
  the identifier of the report (`response_variable`). Write right.
- A home that **requires a sign-in provider** can be added with a token created
  while signed in through that provider. When Housecairn answers `sso_required`
  (a token created otherwise, or the provider changed), Home Assistant asks for
  a new token and says why.

### Changed

- Five requests per update instead of three (the tasks without a date, the tasks
  done lately).
- A 403 `sso_required` asks for a new token instead of retrying the setup.

## 0.2.0

- One to-do list per home: the open tasks overdue, due today or due in the next
  14 days. Checking one marks it done in Housecairn (Write right); without the
  Write right the list is read-only, which the setup says.
- Tokens are created on the API tokens screen of Housecairn.
- An address with a path (Housecairn served under a prefix) is kept in every
  request.

## 0.1.0

- Setup with the address of Housecairn and a Housecairn API token, one entry per
  home, reauthentication.
- Sensors per home: overdue tasks, tasks due today, next due date, stock items
  below their threshold. Diagnostics without the token or the content of the
  home.
