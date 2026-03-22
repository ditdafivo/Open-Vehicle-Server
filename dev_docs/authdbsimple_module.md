# Module Plan: `py/server/plugins/authdbsimple.py`

## Purpose

Port of `OVMS::Server::AuthDbSimple`, providing plain-text database password
authentication for controlled/private environments.

## Completed

- Registers `Authenticate` function.
- Implements owner lookup through `DbGetOwner`.
- Returns wildcard permission (`*`) on successful plaintext match.

## Remaining work

## Behavioral parity

- Confirm all return semantics exactly match Perl behavior for null/empty
  credentials and missing database fields.
- Validate compatibility with protocol v2 caller expectations for failure paths.

## Security posture

- Add explicit warning/guardrails in config and logs that this backend is not
  suitable for public deployments.
- Add optional rate limiting and lockout hooks.
- Ensure timing-safe comparison is used for password equality checks.

## Ecosystem integration

- Define clear interface contract for alternative auth backends
  (`AuthDrupal`, `AuthNone`) to avoid drift.
- Add shared auth test harness so all backends pass the same conformance suite.

## Testing

- Unit tests for success/failure/edge cases.
- Integration tests from API handshake entrypoints through auth decisions.
