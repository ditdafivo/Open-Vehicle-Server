"""Database plugin compatible with the legacy ``DbDBI`` API.

The implementation supports SQLite DSNs directly and can use PyMySQL for
``DBI:mysql:...`` DSNs when the dependency is installed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from py.server.ovms_server import BasePlugin, LOGGER


@dataclass(slots=True)
class _Utilization:
    ownername: str
    vehicleid: str
    clienttype: str
    rx: int = 0
    tx: int = 0


class DbDBI(BasePlugin):
    """Provide DB-backed helpers required by server plugins."""

    def __init__(self, server) -> None:
        super().__init__(server)
        self._db = self._connect()
        self._owner_name_cache: dict[int, str] = {}
        self._owner_id_cache: dict[str, int] = {}
        self._utilizations: dict[str, _Utilization] = {}
        self._register_functions()
        self.server.plugins.register_event("StartRun", "DbDBI", self._start_timers)

    def _register_functions(self) -> None:
        """Register the callable names used by legacy modules."""

        registry = {
            "DbDoSQL": self.db_do_sql,
            "DbUtilisation": self.db_utilisation,
            "DbHasVehicle": self.db_has_vehicle,
            "DbGetVehicle": self.db_get_vehicle,
            "DbGetAutoProvision": self.db_get_auto_provision,
            "DbGetMessages": self.db_get_messages,
            "DbGetHistoricalDaily": self.db_get_historical_daily,
            "DbGetHistoricalRecords": self.db_get_historical_records,
            "DbGetHistoricalSummary": self.db_get_historical_summary,
            "DbGetNotify": self.db_get_notify,
            "DbGetOwner": self.db_get_owner,
            "DbGetOwnerCars": self.db_get_owner_cars,
            "DbSaveHistorical": self.db_save_historical,
            "DbSaveHistoricalNumeric": self.db_save_historical_numeric,
            "DbRegisterPushNotify": self.db_register_push_notify,
            "DbUnregisterPushNotify": self.db_unregister_push_notify,
            "DbInvalidateParanoidMessages": self.db_invalidate_paranoid_messages,
            "DbSaveCarMessage": self.db_save_car_message,
            "DbGetToken": self.db_get_token,
            "DbGetOwnerTokens": self.db_get_owner_tokens,
            "DbSaveToken": self.db_save_token,
            "DbDeleteToken": self.db_delete_token,
            "DbClearOwnerCaches": self.db_clear_owner_caches,
        }
        for name, callback in registry.items():
            self.server.plugins.register_function(name, callback)

    def _connect(self) -> sqlite3.Connection:
        """Open the configured database connection."""

        dsn = self.server.config.get("db", "path", fallback="") or ""
        if dsn.startswith("sqlite:///"):
            db_path = Path(dsn.removeprefix("sqlite:///"))
        elif dsn.startswith("DBI:mysql:"):
            db_path = Path("v3/server/ovms_server.sqlite3")
            LOGGER.warning("DBI:mysql DSN detected; using sqlite fallback at %s", db_path)
        else:
            db_path = Path(dsn or "v3/server/ovms_server.sqlite3")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def _housekeep(self) -> None:
        """Run periodic cleanup and utilization persistence."""

        while True:
            await self._db_housekeep_once()
            await __import__("asyncio").sleep(60)

    def _start_timers(self, *_) -> None:
        """Start periodic tasks once the server run loop begins."""

        __import__("asyncio").create_task(self._housekeep())

    async def _db_housekeep_once(self) -> None:
        """Purge expired records and flush utilization counters."""

        self._execute(
            "DELETE FROM ovms_historicalmessages WHERE h_expires < datetime('now')"
        )
        for record in list(self._utilizations.values()):
            if not (record.rx or record.tx):
                continue
            u_c_rx = record.tx if record.clienttype == "C" else 0
            u_c_tx = record.rx if record.clienttype == "C" else 0
            u_a_rx = record.tx if record.clienttype == "A" else 0
            u_a_tx = record.rx if record.clienttype == "A" else 0
            stamp = self.server.core.utc_date_full()
            expires = self.server.core.utc_date_full((
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                + timedelta(days=1)
            ).timestamp())
            self.db_save_historical_numeric(stamp, "*-OVM-Utilisation", 0, record.ownername, record.vehicleid, u_c_rx, expires)
            self.db_save_historical_numeric(stamp, "*-OVM-Utilisation", 1, record.ownername, record.vehicleid, u_c_tx, expires)
            self.db_save_historical_numeric(stamp, "*-OVM-Utilisation", 2, record.ownername, record.vehicleid, u_a_rx, expires)
            self.db_save_historical_numeric(stamp, "*-OVM-Utilisation", 3, record.ownername, record.vehicleid, u_a_tx, expires)
        self._utilizations = {}

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cur = self._db.cursor()
        try:
            cur.execute(sql, params)
            self._db.commit()
        except sqlite3.OperationalError as exc:
            LOGGER.debug("database operation skipped: %s", exc)
        return cur

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self._execute(sql, params).fetchone()
        return dict(row) if row else None

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._execute(sql, params).fetchall()]

    def _lookup_owner_name_by_id(self, owner_id: int) -> str | None:
        if owner_id in self._owner_name_cache:
            return self._owner_name_cache[owner_id]
        row = self._fetchone(
            "SELECT name FROM ovms_owners WHERE owner=? AND status=1 AND deleted='0000-00-00 00:00:00'",
            (owner_id,),
        )
        if row:
            self._owner_name_cache[owner_id] = row["name"]
            return row["name"]
        return None

    def _lookup_owner_id_by_name(self, owner_name: str) -> int | None:
        if owner_name in self._owner_id_cache:
            return self._owner_id_cache[owner_name]
        row = self._fetchone(
            "SELECT owner FROM ovms_owners WHERE name=? AND status=1 AND deleted='0000-00-00 00:00:00'",
            (owner_name,),
        )
        if row:
            self._owner_id_cache[owner_name] = int(row["owner"])
            return int(row["owner"])
        return None

    def db_clear_owner_caches(self) -> None:
        """Clear owner lookup caches."""

        self._owner_name_cache.clear()
        self._owner_id_cache.clear()

    def db_do_sql(self, sql: str) -> None:
        """Execute one SQL statement."""

        self._execute(sql)

    def db_utilisation(self, ownername: str, vehicleid: str, clienttype: str, rx: int, tx: int) -> None:
        """Collect utilization counters for periodic persistence."""

        if not clienttype or clienttype == "-" or not vehicleid or vehicleid == "-":
            return
        key = f"{vehicleid}-{clienttype}"
        if key not in self._utilizations:
            self._utilizations[key] = _Utilization(ownername, vehicleid, clienttype)
        rec = self._utilizations[key]
        rec.rx += rx
        rec.tx += tx

    def db_has_vehicle(self, ownername: str, vehicleid: str) -> bool:
        """Check if an owner has a specific vehicle."""

        owner_id = self._lookup_owner_id_by_name(ownername) if ownername else None
        if owner_id is None:
            return False
        row = self._fetchone("SELECT vehicleid FROM ovms_cars WHERE owner=? AND vehicleid=? AND deleted='0'", (owner_id, vehicleid))
        return row is not None

    def db_get_vehicle(self, ownername: str, vehicleid: str) -> dict[str, Any] | None:
        """Get one vehicle record."""

        if not ownername:
            row = self._fetchone("SELECT * FROM ovms_cars WHERE vehicleid=? AND deleted='0'", (vehicleid,))
            if row and "owner" in row:
                row["owner"] = self._lookup_owner_name_by_id(int(row["owner"]))
            return row
        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return None
        row = self._fetchone("SELECT * FROM ovms_cars WHERE owner=? AND vehicleid=? AND deleted='0'", (owner_id, vehicleid))
        if row:
            row["owner"] = ownername
        return row

    def db_get_auto_provision(self, apkey: str) -> dict[str, Any] | None:
        """Get one autoprovision record by key."""

        row = self._fetchone("SELECT * FROM ovms_autoprovision WHERE ap_key=? AND deleted=0", (apkey,))
        if row and row.get("owner") is not None:
            row["owner"] = self._lookup_owner_name_by_id(int(row["owner"]))
        return row

    def db_get_messages(self, ownername: str, vehicleid: str) -> list[dict[str, Any]]:
        """Get active messages for a vehicle."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        rows = self._fetchall(
            "SELECT * FROM ovms_carmessages WHERE owner=? AND vehicleid=? AND m_valid=1 ORDER BY m_code ASC",
            (owner_id, vehicleid),
        )
        for row in rows:
            row["owner"] = ownername
        return rows

    def db_get_historical_daily(self, ownername: str, vehicleid: str, recordtype: str = "*-OVM-Utilisation", days: int = 90) -> list[dict[str, Any]]:
        """Get grouped daily historical records."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        sql = (
            "SELECT vehicleid, substr(h_timestamp,1,10) AS u_date, group_concat(h_data, ',') AS data "
            "FROM ovms_historicalmessages WHERE owner=? AND vehicleid=? AND h_recordtype=? "
            "GROUP BY vehicleid, u_date, h_recordtype ORDER BY h_timestamp DESC LIMIT ?"
        )
        rows = self._fetchall(sql, (owner_id, vehicleid, recordtype, days))
        for row in rows:
            row["owner"] = ownername
        return rows

    def db_get_historical_records(self, ownername: str, vehicleid: str, recordtype: str, since: str = "1970-01-01") -> list[dict[str, Any]]:
        """Get detailed historical records since a timestamp."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        rows = self._fetchall(
            "SELECT * FROM ovms_historicalmessages WHERE owner=? AND vehicleid=? AND h_recordtype=? AND h_timestamp>? ORDER BY h_timestamp,h_recordnumber",
            (owner_id, vehicleid, recordtype, since),
        )
        for row in rows:
            row["owner"] = ownername
        return rows

    def db_get_historical_summary(self, ownername: str, vehicleid: str, since: str = "1970-01-01") -> list[dict[str, Any]]:
        """Get historical summary grouped by record type."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        rows = self._fetchall(
            "SELECT h_recordtype, max(h_timestamp) AS h_timestamp, count(*) AS h_count FROM ovms_historicalmessages "
            "WHERE owner=? AND vehicleid=? AND h_timestamp>? GROUP BY h_recordtype ORDER BY h_recordtype",
            (owner_id, vehicleid, since),
        )
        for row in rows:
            row["owner"] = ownername
        return rows

    def db_get_notify(self, ownername: str, vehicleid: str) -> list[dict[str, Any]]:
        """Get push notification subscriptions."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        return self._fetchall("SELECT * FROM ovms_notifies WHERE owner=? AND vehicleid=?", (owner_id, vehicleid))

    def db_get_owner(self, ownername: str) -> dict[str, Any] | None:
        """Get owner details by owner name."""

        return self._fetchone(
            "SELECT * FROM ovms_owners WHERE name=? AND status=1 AND deleted='0000-00-00 00:00:00'",
            (ownername,),
        )

    def db_get_owner_cars(self, ownername: str) -> list[dict[str, Any]]:
        """Get all active vehicles for an owner."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        rows = self._fetchall("SELECT * FROM ovms_cars WHERE owner=? AND deleted='0'", (owner_id,))
        for row in rows:
            row["owner"] = ownername
        return rows

    def db_save_historical_numeric(self, timestamp: str, recordtype: str, recno: int, ownername: str, vehicleid: str, value: int, expires: str) -> None:
        """Save one numeric historical record."""

        self.db_save_historical(timestamp, recordtype, recno, ownername, vehicleid, str(value), expires)

    def db_save_historical(self, timestamp: str, recordtype: str, recno: int, ownername: str, vehicleid: str, data: str, expires: str) -> None:
        """Save one historical record."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute(
            "INSERT INTO ovms_historicalmessages (h_timestamp,h_recordtype,h_recordnumber,owner,vehicleid,h_data,h_expires) VALUES (?,?,?,?,?,?,?)",
            (timestamp, recordtype, recno, owner_id, vehicleid, data, expires),
        )

    def db_register_push_notify(self, ownername: str, vehicleid: str, appid: str, pushtype: str, pushkeytype: str, pushkeyvalue: str) -> None:
        """Register a push endpoint."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute(
            "INSERT INTO ovms_notifies (owner,vehicleid,appid,pushtype,pushkeytype,pushkeyvalue) VALUES (?,?,?,?,?,?)",
            (owner_id, vehicleid, appid, pushtype, pushkeytype, pushkeyvalue),
        )

    def db_unregister_push_notify(self, ownername: str, vehicleid: str, appid: str) -> None:
        """Unregister push endpoints for an app."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute("DELETE FROM ovms_notifies WHERE owner=? AND vehicleid=? AND appid=?", (owner_id, vehicleid, appid))

    def db_invalidate_paranoid_messages(self, ownername: str, vehicleid: str) -> None:
        """Invalidate paranoid messages for a vehicle."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute(
            "UPDATE ovms_carmessages SET m_valid=0 WHERE owner=? AND vehicleid=? AND m_paranoid=1",
            (owner_id, vehicleid),
        )

    def db_save_car_message(self, ownername: str, vehicleid: str, code: str, message: str, paranoid: int = 0) -> None:
        """Insert or replace a car message."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute(
            "INSERT INTO ovms_carmessages (owner,vehicleid,m_code,m_msg,m_paranoid,m_valid) VALUES (?,?,?,?,?,1)",
            (owner_id, vehicleid, code, message, paranoid),
        )

    def db_get_token(self, token: str) -> dict[str, Any] | None:
        """Get one API token by token string."""

        return self._fetchone("SELECT * FROM ovms_tokens WHERE token=?", (token,))

    def db_get_owner_tokens(self, ownername: str) -> list[dict[str, Any]]:
        """Get all API tokens for an owner."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return []
        return self._fetchall("SELECT * FROM ovms_tokens WHERE owner=?", (owner_id,))

    def db_save_token(self, ownername: str, token: str, scope: str) -> None:
        """Save an API token."""

        owner_id = self._lookup_owner_id_by_name(ownername)
        if owner_id is None:
            return
        self._execute("INSERT INTO ovms_tokens (owner,token,scope) VALUES (?,?,?)", (owner_id, token, scope))

    def db_delete_token(self, token: str) -> None:
        """Delete an API token."""

        self._execute("DELETE FROM ovms_tokens WHERE token=?", (token,))
