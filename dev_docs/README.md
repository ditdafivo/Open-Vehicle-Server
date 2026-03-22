# OVMS Python Port Development Notes

This directory tracks the current state of the Python port and the remaining
work required to reach feature parity with the legacy Perl server.

## Scope

Current Python modules documented here:

- `py/server/plugins/vece.py`
- `py/server/plugins/dbdbi.py`
- `py/server/plugins/authdbsimple.py`
- `py/server/plugins/apiv2.py`

## How to use these docs

- Start with `roadmap.md` for milestone-level sequencing.
- Use each module-specific document for implementation gaps and concrete tasks.
- Keep these docs synchronized with code changes and commit updates.

## Parity objective

Parity means functional compatibility with `v3/server/ovms_server.pl` and the
Perl modules loaded by `v3/server/conf/ovms_server.conf.default`, plus any
transitive plugin dependencies.
