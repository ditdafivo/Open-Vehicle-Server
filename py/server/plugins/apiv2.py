"""OVMS protocol v2 TCP listener.

This is a partial Python port of ``OVMS::Server::ApiV2`` that provides
connection acceptance, welcome-line processing, authentication, and
basic routing between app and car clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from typing import Any

from py.server.ovms_server import BasePlugin, LOGGER


class ApiV2(BasePlugin):
    """Listen for and process protocol v2 client connections."""

    def __init__(self, server) -> None:
        super().__init__(server)
        self.timeout_app = server.config.get_int("server", "timeout_app", fallback=60 * 20)
        self.timeout_car = server.config.get_int("server", "timeout_car", fallback=60 * 16)
        self.timeout_api = server.config.get_int("server", "timeout_api", fallback=60 * 2)
        self._servers: list[asyncio.base_events.Server] = []
        self._conn_ids = itertools.count(1)
        self.server.plugins.register_event("StartRun", "ApiV2", self.start)

    def start(self, *_) -> None:
        """Start the plaintext listener task."""

        asyncio.create_task(self._start_servers())

    async def _start_servers(self) -> None:
        LOGGER.info("- - - starting V2 server listener on port tcp/6867")
        self._servers.append(await asyncio.start_server(self._accept_client, host="0.0.0.0", port=6867))

    async def _accept_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn_id = str(next(self._conn_ids))
        peer = writer.get_extra_info("peername")
        host, port = (peer[0], peer[1]) if peer else ("-", 0)
        LOGGER.info("#%s - - new connection from %s:%s", conn_id, host, port)
        self.server.core.conn_start(
            conn_id,
            reader=reader,
            writer=writer,
            host=host,
            port=port,
            clienttype="-",
            proto="v2/6867",
            lastrx=asyncio.get_running_loop().time(),
            lasttx=asyncio.get_running_loop().time(),
            callback_tx=self._callback_tx,
            callback_shutdown=self._callback_shutdown,
        )

        task = asyncio.create_task(self._connection_loop(conn_id, reader, writer))
        timer = asyncio.create_task(self._timeout_loop(conn_id))
        done, pending = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await p
        for d in done:
            with contextlib.suppress(Exception):
                await d
        self._terminate(conn_id, "connection closed")

    async def _connection_loop(self, conn_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readline()
        if not line:
            return
        text = line.decode(errors="replace").strip()
        if not self._welcome(conn_id, text):
            return
        while True:
            line = await reader.readline()
            if not line:
                return
            msg = line.decode(errors="replace").strip()
            self.server.core.conn_set_attribute(conn_id, "lastrx", asyncio.get_running_loop().time())
            await self._io_line(conn_id, msg)

    async def _timeout_loop(self, conn_id: str) -> None:
        while self.server.core.conn_defined(conn_id):
            await asyncio.sleep(15)
            clienttype = self.server.core.conn_get_attribute(conn_id, "clienttype") or "-"
            now = asyncio.get_running_loop().time()
            lastrx = self.server.core.conn_get_attribute(conn_id, "lastrx") or now
            lasttx = self.server.core.conn_get_attribute(conn_id, "lasttx") or now
            if clienttype == "-" and (lastrx + 60) < now:
                self._terminate(conn_id, "timeout due to no initial welcome exchange")
                return
            if clienttype == "A" and (lastrx + self.timeout_app) < now:
                self._terminate(conn_id, "timeout app due to inactivity")
                return
            if clienttype == "B" and (lastrx + self.timeout_api) < now:
                self._terminate(conn_id, "timeout btc due to inactivity")
                return
            if clienttype == "C":
                if (lastrx + self.timeout_car) < now:
                    self._terminate(conn_id, "timeout car due to inactivity")
                    return
                if (lasttx + self.timeout_car - 60) < now:
                    self.server.core.conn_transmit(conn_id, "v2", "A", "FA")

    def _welcome(self, conn_id: str, line: str) -> bool:
        self.server.core.conn_set_attribute(conn_id, "lastrx", asyncio.get_running_loop().time())
        parts = line.split()
        if len(parts) < 5 or not parts[0].startswith("MP-"):
            self._terminate(conn_id, f"invalid welcome line: {line}")
            return False

        clienttype = parts[0][3:4]
        protscheme = parts[1]
        token_a = parts[2]
        token_b = parts[3]
        vehicle_id = parts[4].upper()

        self.server.core.conn_set_attributes(
            conn_id,
            clienttype=clienttype,
            protscheme=protscheme,
            vehicleid=vehicle_id,
            owner=token_a,
            appid=token_b,
            permissions="",
        )

        if clienttype in {"A", "B"}:
            perms = self.server.plugins.function_call("Authenticate", token_a, token_b) or ""
            if not perms:
                self.server.core.conn_transmit(conn_id, "v2", "E", "AuthFail")
                self._terminate(conn_id, "authentication failed")
                return False
            self.server.core.conn_set_attribute(conn_id, "permissions", perms)
            self.server.core.app_connect(token_a, vehicle_id, conn_id)
            self.server.core.conn_transmit(conn_id, "v2", "E", "Welcome")
            return True

        if clienttype == "C":
            self.server.core.car_connect(token_a, vehicle_id, conn_id)
            self.server.core.conn_set_attribute(conn_id, "permissions", "*")
            self.server.core.conn_transmit(conn_id, "v2", "E", "Welcome")
            return True

        self._terminate(conn_id, f"unsupported client type {clienttype}")
        return False

    async def _io_line(self, conn_id: str, line: str) -> None:
        clienttype = self.server.core.conn_get_attribute(conn_id, "clienttype") or "-"
        owner = self.server.core.conn_get_attribute(conn_id, "owner") or "-"
        vehicle_id = self.server.core.conn_get_attribute(conn_id, "vehicleid") or "-"
        if clienttype == "C":
            self.server.core.clients_transmit(owner, vehicle_id, "v2", line)
        else:
            self.server.core.car_transmit(owner, vehicle_id, "v2", line)

    def _callback_tx(self, conn_id: str, fmt: str, *data: str) -> None:
        if fmt != "v2":
            return
        writer: asyncio.StreamWriter | None = self.server.core.conn_get_attribute(conn_id, "writer")
        if not writer:
            return
        payload = " ".join(str(item) for item in data).strip()
        if payload:
            writer.write((payload + "\r\n").encode())
            self.server.core.conn_set_attribute(conn_id, "lasttx", asyncio.get_running_loop().time())

    def _callback_shutdown(self, conn_id: str) -> None:
        writer: asyncio.StreamWriter | None = self.server.core.conn_get_attribute(conn_id, "writer")
        if writer:
            writer.close()

    def _terminate(self, conn_id: str, reason: str) -> None:
        if not self.server.core.conn_defined(conn_id):
            return
        vehicle_id = self.server.core.conn_get_attribute(conn_id, "vehicleid") or "-"
        owner = self.server.core.conn_get_attribute(conn_id, "owner") or "-"
        clienttype = self.server.core.conn_get_attribute(conn_id, "clienttype") or "-"
        LOGGER.info("#%s %s %s/%s %s", conn_id, clienttype, owner, vehicle_id, reason)
        if clienttype == "C":
            self.server.core.car_disconnect(owner, vehicle_id, conn_id)
        elif clienttype == "B":
            self.server.core.batch_disconnect(owner, vehicle_id, conn_id)
        elif clienttype == "A":
            self.server.core.app_disconnect(owner, vehicle_id, conn_id)
        self.server.core.conn_shutdown(conn_id)
        self.server.core.conn_finish(conn_id)
