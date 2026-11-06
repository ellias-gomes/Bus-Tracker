"""Persistência local em SQLite (biblioteca padrão, sem ORM, ideal para Termux)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from ..models import Itinerary, Level, Trip, TripSource

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,          -- JSON de Trip.to_dict()
    source      TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Ofertas brutas coletadas (por rota/data), úteis para auditoria e reaproveitamento.
CREATE TABLE IF NOT EXISTS offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    provider     TEXT NOT NULL,
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    travel_date  TEXT NOT NULL,
    depart_at    TEXT NOT NULL,
    arrive_at    TEXT NOT NULL,
    price        REAL NOT NULL,
    seats        INTEGER,
    seat_type    TEXT,
    company      TEXT,
    boarding     TEXT,
    url          TEXT
);
CREATE INDEX IF NOT EXISTS idx_offers_route ON offers(origin, destination, travel_date, collected_at);

-- Melhor opção válida por trecho de viagem a cada coleta: base da série histórica.
CREATE TABLE IF NOT EXISTS leg_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id       TEXT NOT NULL,
    leg           TEXT NOT NULL,
    collected_at  TEXT NOT NULL,
    best_price    REAL,
    best_seats    INTEGER,
    options_count INTEGER NOT NULL,
    level         TEXT,
    best_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_trip ON leg_snapshots(trip_id, leg, collected_at);

CREATE TABLE IF NOT EXISTS alerts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id   TEXT NOT NULL,
    leg       TEXT NOT NULL,
    sent_at   TEXT NOT NULL,
    level     TEXT NOT NULL,
    price     REAL,
    milestone INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alerts_trip ON alerts(trip_id, leg, sent_at);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------ trips
    def upsert_trip(self, trip: Trip) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO trips (id, data, source, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data=excluded.data, source=excluded.source,
                    active=excluded.active, updated_at=excluded.updated_at
                """,
                (trip.id, json.dumps(trip.to_dict()), trip.source.value, int(trip.active), now, now),
            )

    def get_trip(self, trip_id: str) -> Trip | None:
        row = self._conn.execute("SELECT data FROM trips WHERE id=?", (trip_id,)).fetchone()
        return Trip.from_dict(json.loads(row["data"])) if row else None

    def list_trips(self, active_only: bool = True) -> list[Trip]:
        sql = "SELECT data FROM trips"
        if active_only:
            sql += " WHERE active=1"
        trips = [Trip.from_dict(json.loads(r["data"])) for r in self._conn.execute(sql)]
        return sorted(trips, key=lambda t: t.first_date() or date.max)

    def deactivate_trip(self, trip_id: str) -> bool:
        trip = self.get_trip(trip_id)
        if not trip:
            return False
        trip.active = False
        self.upsert_trip(trip)
        return True

    def sync_source(self, source: TripSource, trips: list[Trip]) -> tuple[int, int]:
        """Sincroniza as viagens de uma fonte externa (JSON/ICS).

        Viagens da fonte que não aparecem mais são desativadas. Retorna (upserts, desativadas).
        """
        incoming = {t.id for t in trips}
        for trip in trips:
            self.upsert_trip(trip)
        removed = 0
        for row in self._conn.execute(
            "SELECT id FROM trips WHERE source=? AND active=1", (source.value,)
        ).fetchall():
            if row["id"] not in incoming:
                self.deactivate_trip(row["id"])
                removed += 1
        return len(trips), removed

    # ----------------------------------------------------------------- offers
    def save_offers(self, travel_date: date, offers: list) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.tx() as c:
            c.executemany(
                """
                INSERT INTO offers (collected_at, provider, origin, destination, travel_date,
                    depart_at, arrive_at, price, seats, seat_type, company, boarding, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        now, o.provider, o.origin, o.destination, travel_date.isoformat(),
                        o.depart_at.isoformat(), o.arrive_at.isoformat(), o.price, o.seats,
                        o.seat_type, o.company, o.boarding_point, o.url,
                    )
                    for o in offers
                    if not o.is_estimate
                ],
            )

    # -------------------------------------------------------------- snapshots
    def save_snapshot(
        self, trip_id: str, leg: str, best: Itinerary | None, options_count: int, level: Level
    ) -> None:
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO leg_snapshots (trip_id, leg, collected_at, best_price, best_seats,
                    options_count, level, best_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trip_id, leg, datetime.now().isoformat(timespec="seconds"),
                    best.price if best else None, best.seats if best else None,
                    options_count, level.value, json.dumps(best.to_dict()) if best else None,
                ),
            )

    def daily_min_prices(self, trip_id: str, leg: str, days: int) -> list[tuple[date, float]]:
        """Menor preço válido por dia de coleta, nos últimos `days` dias."""
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """
            SELECT substr(collected_at, 1, 10) AS day, MIN(best_price) AS price
            FROM leg_snapshots
            WHERE trip_id=? AND leg=? AND collected_at>=? AND best_price IS NOT NULL
            GROUP BY day ORDER BY day
            """,
            (trip_id, leg, since),
        ).fetchall()
        return [(date.fromisoformat(r["day"]), float(r["price"])) for r in rows]

    def last_snapshot(self, trip_id: str, leg: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM leg_snapshots WHERE trip_id=? AND leg=? ORDER BY id DESC LIMIT 1",
            (trip_id, leg),
        ).fetchone()

    # ----------------------------------------------------------------- alerts
    def last_alert(self, trip_id: str, leg: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM alerts WHERE trip_id=? AND leg=? ORDER BY id DESC LIMIT 1",
            (trip_id, leg),
        ).fetchone()

    def milestone_sent(self, trip_id: str, leg: str, milestone: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM alerts WHERE trip_id=? AND leg=? AND milestone=? LIMIT 1",
            (trip_id, leg, milestone),
        ).fetchone()
        return row is not None

    def record_alert(
        self, trip_id: str, leg: str, level: Level, price: float | None, milestone: int | None
    ) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO alerts (trip_id, leg, sent_at, level, price, milestone) VALUES (?,?,?,?,?,?)",
                (trip_id, leg, datetime.now().isoformat(timespec="seconds"), level.value, price, milestone),
            )

    # --------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
