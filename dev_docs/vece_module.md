# Module Plan: `py/server/plugins/vece.py`

## Purpose

Port of `OVMS::Server::VECE` for vehicle error code expansion from legacy
`v3/server/vece/*.vece` data files.

## Completed

- Loads all `.vece` files from the legacy tree.
- Registers `VECE_Expansion` function.
- Supports progressive vehicle-type fallback by truncating type suffix.
- Handles duplicate keys in legacy data files via permissive parser settings.

## Remaining work

## Behavior parity

- Confirm section/key conflict precedence matches Perl exactly when multiple
  files define the same error code.
- Verify format substitution semantics are fully compatible with Perl `sprintf`
  behavior, including edge cases and malformed templates.
- Validate fallback traversal behavior for all known vehicle type hierarchies.

## Data handling

- Add optional validation mode to detect invalid `.vece` entries at startup.
- Provide deterministic conflict reporting (which file won, what was overridden).
- Add hot-reload support for VECE definitions, gated by configuration.

## Operational quality

- Add unit tests for expansion/fallback/conflict scenarios.
- Add integration tests validating interoperability with push notification flows.
- Add structured debug telemetry for unresolved codes and fallback path depth.

## Documentation

- Document VECE file format and precedence rules for maintainers.
- Add migration notes for introducing new vehicle types and codes.
