# Open Vehicle Server Python Port

This repository now includes a Python 3 runtime entrypoint for the OVMS v3
server.

## Run with uv + hatch

```bash
uv tool install hatch
hatch run run
```

## Direct run

```bash
uv run ovms-server --config v3/server/conf/ovms_server.conf.default
```

## Scope of the current port

The Python runtime currently ports the legacy Perl bootstrap and infrastructure:

- Config loading and plugin list parsing
- Core connection registries and helper utilities
- Plugin manager event/function registry
- Periodic statistics logging

System plugins listed by the default config are wired to Python no-op fallback
implementations so the service can boot cleanly while full plugin-by-plugin
ports are completed.
