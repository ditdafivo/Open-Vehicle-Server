#!/usr/bin/env python3
"""OVMS v3 server entrypoint.

This module is a modern Python port of the legacy Perl server entrypoint
(`v3/server/ovms_server.pl`) and the two always-loaded core modules
(`Core.pm`, `Plugin.pm`).

The implementation intentionally focuses on parity for the server bootstrap,
plugin lifecycle, event/function registry, connection registry, and periodic
statistics logging.

To run with the default repository layout::

   uv run ovms-server --config v3/server/conf/ovms_server.conf.default

The plugin layer supports Python-native plugins and includes no-op fallback
plugins for the names listed by the legacy default config so the server can
start cleanly while additional module ports are completed.
"""

from __future__ import annotations

import argparse
import asyncio
import configparser
import importlib
import logging
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("ovms.server")


def _get_version() -> str:
    """Resolve the server version string from git metadata when available."""

    try:
        version = subprocess.check_output(
            ["git", "describe", "--always", "--tags", "--dirty"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return version or "3.0.0-custom"
    except Exception:
        return "3.0.0-custom"


class OVMSConfig:
    """Config reader for OVMS INI files including legacy heredoc blocks."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.parser = configparser.ConfigParser(interpolation=None)
        self.parser.optionxform = str
        raw = path.read_text(encoding="utf-8")
        self._plugin_list = self._parse_plugin_list(raw)
        self.parser.read_string(self._strip_heredoc(raw))

    def get(self, section: str, option: str, fallback: str | None = None) -> str | None:
        """Get a string config value."""

        return self.parser.get(section, option, fallback=fallback)

    def get_int(self, section: str, option: str, fallback: int) -> int:
        """Get an integer config value."""

        return self.parser.getint(section, option, fallback=fallback)

    @property
    def plugin_list(self) -> list[str]:
        """Configured plugin class suffixes from `[plugins] load`."""

        if self._plugin_list:
            return self._plugin_list
        fallback = self.get("plugins", "load", fallback="DbDBI") or "DbDBI"
        return [entry.strip() for entry in fallback.splitlines() if entry.strip()]

    @staticmethod
    def _strip_heredoc(raw: str) -> str:
        lines = raw.splitlines()
        out: list[str] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if line.strip().startswith("load=<<"):
                idx += 1
                while idx < len(lines) and lines[idx].strip() != "EOT":
                    idx += 1
                idx += 1
                out.append("load=")
                continue
            out.append(line)
            idx += 1
        return "\n".join(out) + "\n"

    @staticmethod
    def _parse_plugin_list(raw: str) -> list[str]:
        marker = "load=<<EOT"
        if marker not in raw:
            return []
        after = raw.split(marker, 1)[1]
        payload = after.split("\nEOT", 1)[0]
        return [line.strip() for line in payload.splitlines() if line.strip()]


@dataclass(slots=True)
class Connection:
    """Connection registry item."""

    attributes: dict[str, Any] = field(default_factory=dict)


class CoreService:
    """Core registry and helper functions ported from `Core.pm`."""

    def __init__(self, config: OVMSConfig) -> None:
        self.config = config
        self.version = _get_version()
        self._conns: dict[str, Connection] = {}
        self._car_conns: dict[str, str] = {}
        self._app_conns: dict[str, set[str]] = defaultdict(set)
        self._batch_conns: dict[str, set[str]] = defaultdict(set)

    @staticmethod
    def is_permitted(permissions: str, *rights: str) -> bool:
        """Check if a permission list includes at least one of `rights`."""

        if permissions == "*":
            return True
        allowed = {entry.strip().lower() for entry in permissions.split(",") if entry.strip()}
        return any(right.lower() in allowed for right in rights)

    @staticmethod
    def utc_date(timestamp: float | None = None) -> str:
        """Format timestamp as UTC date."""

        dt = datetime.fromtimestamp(timestamp or datetime.now(tz=timezone.utc).timestamp(), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def utc_date_full(timestamp: float | None = None) -> str:
        """Format timestamp as UTC date at midnight."""

        dt = datetime.fromtimestamp(timestamp or datetime.now(tz=timezone.utc).timestamp(), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d 00:00:00")

    @staticmethod
    def utc_time(timestamp: float | None = None) -> str:
        """Format timestamp as full UTC datetime."""

        dt = datetime.fromtimestamp(timestamp or datetime.now(tz=timezone.utc).timestamp(), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def conn_start(self, conn_id: str, **attr: Any) -> None:
        """Initialize or replace connection metadata."""

        LOGGER.info("#%s - - ConnStart", conn_id)
        self._conns[conn_id] = Connection(attributes=dict(attr))

    def conn_finish(self, conn_id: str) -> None:
        """Remove connection metadata."""

        LOGGER.info("#%s - - ConnFinish", conn_id)
        self._conns.pop(conn_id, None)

    def conn_get_attribute(self, conn_id: str, key: str) -> Any:
        """Get one connection attribute."""

        return self._conns.get(conn_id, Connection()).attributes.get(key)

    def conn_has_attribute(self, conn_id: str, key: str) -> bool:
        """Check if a connection has an attribute."""

        conn = self._conns.get(conn_id)
        return conn is not None and key in conn.attributes

    def conn_set_attribute(self, conn_id: str, key: str, value: Any) -> None:
        """Set one connection attribute."""

        self._conns.setdefault(conn_id, Connection()).attributes[key] = value

    def conn_set_attributes(self, conn_id: str, **attr: Any) -> None:
        """Set multiple connection attributes."""

        self._conns.setdefault(conn_id, Connection()).attributes.update(attr)

    def conn_inc_attribute(self, conn_id: str, key: str, value: int) -> None:
        """Increment a numeric connection attribute."""

        conn = self._conns.setdefault(conn_id, Connection())
        conn.attributes[key] = int(conn.attributes.get(key, 0)) + value

    def conn_defined(self, conn_id: str) -> bool:
        """Check if a connection exists."""

        return conn_id in self._conns

    def conn_keys(self, conn_id: str) -> list[str]:
        """Get all attribute keys for a connection."""

        return list(self._conns.get(conn_id, Connection()).attributes.keys())

    @staticmethod
    def _vkey(owner: str, vehicle_id: str) -> str:
        return f"{owner}/{vehicle_id}"

    def car_connect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Register a car transport connection."""

        vkey = self._vkey(owner, vehicle_id)
        self._car_conns[vkey] = conn_id
        LOGGER.info("#%s %s %s CarConnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)

    def car_disconnect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Unregister a car transport connection."""

        vkey = self._vkey(owner, vehicle_id)
        LOGGER.info("#%s %s %s CarDisconnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)
        self._car_conns.pop(vkey, None)

    def car_connection(self, owner: str, vehicle_id: str) -> str | None:
        """Find the active car connection id."""

        return self._car_conns.get(self._vkey(owner, vehicle_id))

    def app_connect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Register an app connection."""

        vkey = self._vkey(owner, vehicle_id)
        self._app_conns[vkey].add(conn_id)
        LOGGER.info("#%s %s %s AppConnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)

    def app_disconnect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Unregister an app connection."""

        vkey = self._vkey(owner, vehicle_id)
        LOGGER.info("#%s %s %s AppDisconnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)
        self._app_conns[vkey].discard(conn_id)

    def app_connections(self, owner: str, vehicle_id: str) -> list[str]:
        """Get app connection ids for vehicle."""

        return sorted(self._app_conns[self._vkey(owner, vehicle_id)])

    def batch_connect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Register a batch connection."""

        vkey = self._vkey(owner, vehicle_id)
        self._batch_conns[vkey].add(conn_id)
        LOGGER.info("#%s %s %s BatchConnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)

    def batch_disconnect(self, owner: str, vehicle_id: str, conn_id: str) -> None:
        """Unregister a batch connection."""

        vkey = self._vkey(owner, vehicle_id)
        LOGGER.info("#%s %s %s BatchDisconnect", conn_id, self.conn_get_attribute(conn_id, "clienttype") or "-", vkey)
        self._batch_conns[vkey].discard(conn_id)

    def client_connections(self, owner: str, vehicle_id: str) -> list[str]:
        """Get app+batch connections for vehicle."""

        vkey = self._vkey(owner, vehicle_id)
        return sorted(self._app_conns[vkey] | self._batch_conns[vkey])

    def conn_transmit(self, conn_id: str, fmt: str, *data: str) -> None:
        """Emit transport callback data to a single connection."""

        cb = self.conn_get_attribute(conn_id, "callback_tx")
        if cb:
            cb(conn_id, fmt, *data)

    def car_transmit(self, owner: str, vehicle_id: str, fmt: str, *data: str) -> None:
        """Emit transport callback data to a car connection."""

        conn_id = self.car_connection(owner, vehicle_id)
        if conn_id:
            self.conn_transmit(conn_id, fmt, *data)

    def clients_transmit(self, owner: str, vehicle_id: str, fmt: str, *data: str) -> None:
        """Emit transport callback data to non-car clients."""

        for conn_id in self.client_connections(owner, vehicle_id):
            if not conn_id.isdigit():
                continue
            c_owner = self.conn_get_attribute(conn_id, "owner")
            c_vehicle = self.conn_get_attribute(conn_id, "vehicleid")
            c_type = self.conn_get_attribute(conn_id, "clienttype") or "-"
            if c_owner != owner or c_vehicle != vehicle_id:
                LOGGER.error(
                    "#%s %s %s/%s ClientsTransmit mismatch %s/%s",
                    conn_id,
                    c_type,
                    owner,
                    vehicle_id,
                    c_owner,
                    c_vehicle,
                )
                continue
            if c_type != "C":
                self.conn_transmit(conn_id, fmt, *data)

    def conn_shutdown(self, conn_id: str) -> None:
        """Trigger transport shutdown callback."""

        cb = self.conn_get_attribute(conn_id, "callback_shutdown")
        if cb:
            cb(conn_id)


class BasePlugin:
    """Base class for Python OVMS plugins."""

    def __init__(self, server: "OVMSServer") -> None:
        self.server = server


class NullPlugin(BasePlugin):
    """Fallback plugin used until full module ports are completed."""

    def __init__(self, server: "OVMSServer", plugin_name: str) -> None:
        super().__init__(server)
        LOGGER.warning("plugin %s currently uses Python no-op fallback", plugin_name)


class PluginManager:
    """Event/function/plugin registry ported from `Plugin.pm`."""

    _legacy_null_plugins = {
        "VECE",
        "DbDBI",
        "ApiHttp",
        "ApiHttpCore",
        "ApiV2",
        "AuthDbSimple",
        "AuthNone",
        "AuthDrupal",
        "Push",
        "PushMAIL",
        "PushGCM",
        "PushEXPO",
        "PushAPNS",
    }

    def __init__(self, server: "OVMSServer") -> None:
        self.server = server
        self.plugins: dict[str, BasePlugin] = {}
        self.functions: dict[str, Callable[..., Any]] = {}
        self.events: dict[str, dict[str, Callable[..., Any]]] = defaultdict(dict)

    def load_plugins(self) -> None:
        """Load configured plugins."""

        self.event_call("PluginsLoading")
        for name in self.server.config.plugin_list:
            LOGGER.info("- - - loading plugin %s...", name)
            plugin_obj = self._load_single(name)
            if plugin_obj is None:
                LOGGER.error("- - - plugin %s could not be installed", name)
                continue
            self.plugins[name] = plugin_obj
        self.event_call("PluginsLoaded")

    def _load_single(self, name: str) -> BasePlugin | None:
        module_name = f"py.server.plugins.{name.lower()}"
        class_name = name
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            return cls(self.server)
        except ModuleNotFoundError:
            if name in self._legacy_null_plugins:
                return NullPlugin(self.server, name)
            LOGGER.exception("- - - no module found for plugin %s", name)
            return None
        except Exception:
            LOGGER.exception("- - - error while initializing plugin %s", name)
            return None

    def register_function(self, name: str, callback: Callable[..., Any]) -> None:
        """Register a callable by name."""

        LOGGER.info("- - -   RegisterFunction %s", name)
        self.functions[name] = callback

    def function_call(self, name: str, *params: Any) -> Any | None:
        """Call a named function and return its result."""

        callback = self.functions.get(name)
        if not callback:
            LOGGER.error("- - - Function %s does not exist", name)
            return None
        return callback(*params)

    def register_event(self, event: str, caller: str, callback: Callable[..., Any]) -> None:
        """Register callback under a named event."""

        LOGGER.info("- - -   RegisterEvent %s for %s", event, caller)
        self.events[event][caller] = callback

    def event_call(self, event: str, *params: Any) -> list[Any]:
        """Call every callback registered for `event`."""

        results: list[Any] = []
        for caller in sorted(self.events[event]):
            results.append(self.events[event][caller](*params))
        return results


class OVMSServer:
    """Top-level OVMS server runtime."""

    def __init__(self, config_path: Path) -> None:
        self.config = OVMSConfig(config_path)
        self.core = CoreService(self.config)
        self.plugins = PluginManager(self)
        self.info_counts: dict[str, int] = {}

    def info_count(self, topic: str, count: int) -> None:
        """Set one named statistics counter."""

        if count > 0:
            self.info_counts[topic] = count
        else:
            self.info_counts.pop(topic, None)

    async def info_timer(self) -> None:
        """Emit periodic statistics log lines."""

        await asyncio.sleep(10)
        while True:
            if self.info_counts:
                metrics = ", ".join(f"{k}={self.info_counts[k]}" for k in sorted(self.info_counts))
                LOGGER.info("- - - statistics: %s", metrics)
            await asyncio.sleep(10)

    async def run(self) -> None:
        """Bootstrap plugins and enter the asyncio event loop."""

        self.plugins.register_function("InfoCount", self.info_count)
        self.plugins.load_plugins()
        self.plugins.event_call("StartRun")
        await self.info_timer()


def parse_args() -> argparse.Namespace:
    """Parse command line options."""

    parser = argparse.ArgumentParser(description="OVMS Python server")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("v3/server/conf/ovms_server.conf.default"),
        help="Path to OVMS config file",
    )
    parser.add_argument("--log-level", default=None, help="Override [log] level")
    return parser.parse_args()


def setup_logging(config: OVMSConfig, level_override: str | None) -> None:
    """Configure global logging level from config or CLI override."""

    level_name = (level_override or config.get("log", "level", fallback="info") or "info").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    """Program entrypoint."""

    args = parse_args()
    config = OVMSConfig(args.config)
    setup_logging(config, args.log_level)
    server = OVMSServer(args.config)

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        LOGGER.info("shutting down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
