# Module Plan: `py/server/plugins/apiv2.py`

## Purpose

Partial port of `OVMS::Server::ApiV2`, handling protocol v2 TCP transport,
welcome negotiation, authentication flow, and app/car relay behavior.

## Completed

- Starts plaintext listener on tcp/6867.
- Tracks connection metadata in core registry.
- Implements basic welcome parsing and auth dispatch.
- Implements inactivity timeout loops for pre-auth/app/batch/car clients.
- Provides basic relay routing between app and car channels.

## Remaining work

## Protocol completeness

- Implement full v2 command parser and message handling matrix
  (all message prefixes and server actions).
- Support TLS listener parity on tcp/6870 including cert configuration behavior
  from legacy config.
- Port websocket and any protocol-upgrade paths present in Perl implementation.
- Implement group subscription/message behavior (`group_msgs`, `group_subs`).

## Session lifecycle

- Match exact logging and historical log persistence behavior.
- Port disconnect reasons and cleanup ordering for each termination path.
- Implement ping cadence and lastping semantics exactly.
- Ensure write backpressure handling and flush/drain behavior are robust.

## Permission and auth integration

- Enforce permission checks for all message types using `Authenticate` outputs.
- Implement token/owner/vehicle validation semantics matching Perl.
- Port auth-failure notification suppression logic (`authfail_notified`).

## Observability and ops

- Add per-connection metrics (latency, rx/tx bytes, message counts).
- Export utilization counters to DB path with parity to Perl.
- Add debug tooling for protocol transcript replay.

## Testing

- Add protocol fixture tests for welcome/auth/timeouts.
- Add interoperability tests against existing OVMS clients.
- Add long-running soak tests with mixed app/car workloads and reconnect storms.
