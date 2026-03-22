# Module Plan: `py/server/plugins/dbdbi.py`

## Purpose

Port of `OVMS::Server::DbDBI`, providing the database-backed function interface
used by protocol, auth, and push subsystems.

## Completed

- Registers broad legacy function surface (`Db*` calls used by other modules).
- Implements owner caches and key read/write operations.
- Implements periodic housekeeping stub (historical expiration + utilization flush).
- Provides SQLite-compatible execution path for local development bootstrap.

## Remaining work

## Database backend parity

- Implement true MySQL backend support equivalent to Perl DBI behavior
  (connection parameters, reconnect strategy, encoding setup).
- Support production DSN parsing and credential handling exactly from
  `[db]` config semantics.
- Replace SQLite fallback behavior with explicit backend selection and
  clear compatibility guarantees.

## Query parity and correctness

- Audit every SQL query against `v3/server/plugins/system/OVMS/Server/DbDBI.pm`
  for ordering, filtering, grouping, and default behavior differences.
- Restore missing special ordering logic (`FIELD(...)` patterns, timestamp
  semantics, and UTC handling).
- Validate column naming/typing assumptions against `v3/server/ovms_server.sql`.
- Implement all edge-case behavior for absent owners/cars/messages/tokens.

## Housekeeping and utilization

- Port utilization accumulation semantics exactly (including per-client-type
  accounting conventions and rollover behavior).
- Match historical expiration batch limits and scheduling cadence.
- Ensure timer lifecycle and cancellation are robust on shutdown/restart.

## Concurrency and reliability

- Replace synchronous DB operations with async-safe strategy (executor,
  async driver, or explicit thread confinement).
- Add retry/backoff logic for transient DB failures.
- Introduce transaction boundaries for multi-step updates where required.

## Security and integrity

- Enforce parameterized queries consistently.
- Add schema/version checks at startup.
- Add audit logging for mutation paths (token and notification writes).

## Testing

- Unit tests for each exported `Db*` function.
- Integration tests with realistic schema fixtures and mixed app/car traffic.
- Compatibility tests against known outputs from Perl implementation.
