# Python Port Roadmap (Perl v3 Server Parity)

## Current baseline

The Python server can bootstrap plugin loading and start a basic API v2 listener.
The port currently provides partial implementations for VECE, DbDBI,
AuthDbSimple, and ApiV2.

## Milestone plan

## Milestone 1: Stabilize foundation (short term)

- Replace ad-hoc asyncio task startup with explicit lifecycle management
  (startup hooks, shutdown hooks, cancellation, and resource cleanup).
- Add integration tests for plugin registration contracts (functions/events)
  and end-to-end boot behavior.
- Define a compatibility matrix for protocol features implemented vs missing.
- Introduce structured configuration validation and defaults for all known
  sections used by legacy modules.

## Milestone 2: Protocol and DB compatibility (mid term)

- Complete ApiV2 command handling and framing behavior to match Perl semantics.
- Complete DbDBI SQL behavior, schema support, and MySQL production operation.
- Port/enable dependent plugins needed for real traffic paths:
  - `ApiHttp`
  - `ApiHttpCore`
  - push modules (`Push`, `PushMAIL`, `PushGCM`, `PushEXPO`, `PushAPNS`)
  - alternative auth modules (`AuthNone`, `AuthDrupal`)
- Reproduce timeout, connection, and ping behaviors exactly where interoperability
  depends on legacy timings.

## Milestone 3: Operational parity (long term)

- Add production observability: metrics, tracing hooks, health endpoints,
  and operational dashboards.
- Add migration documentation and deployment templates replacing Perl container
  assumptions from `v3_server_dockerfile`.
- Execute staged compatibility rollout (canary, dual-run validation,
  rollback strategy).

## Cross-cutting requirements

- Security hardening (auth validation, input validation, TLS controls,
  credential management).
- Error taxonomy and recoverability strategy.
- Conformance test corpus generated from known Perl behavior and protocol
  capture fixtures.
- Performance benchmarking under concurrent app/car workloads.
