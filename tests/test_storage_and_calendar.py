from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from bustracker.calendar_sync import load_json_trips, parse_ics
from bustracker.config import Settings
from bustracker.db import Storage
from bustracker.models import Level, TripSource


def test_json_and_ics_loading_and_storage_sync(tmp_path: Path):
    trips_file = tmp_path / "viagens.json"
    ev_date = date.today() + timedelta(days=20)
    ida_date = date.today() + timedelta(days=10)
    volta_date = date.today() + timedelta(days=11)

    trips_file.write_text(
        json.dumps(
            [
                {
                    "id": "v1",
                    "nome": "Viagem Manual JSON",
                    "origem": "Rio de Janeiro, RJ",
                    "destino": "Caçapava, SP",
                    "hub_alternativo": "São José dos Campos, SP",
                    "data_ida": ida_date.isoformat(),
                    "data_volta": volta_date.isoformat(),
                    "limite_partida_ida": "22:00",
                    "limite_chegada_volta": "07:15",
                },
                {
                    "id": "v2",
                    "name": "Evento Bimestral",
                    "event_date": ev_date.isoformat(),
                },
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(
        local_trips_file=trips_file,
        default_origin="rio-de-janeiro-rj",
        default_destination="cacapava-sp",
        default_hubs=["sao-jose-dos-campos-sp"],
        default_outbound_depart_before="22:00",
        default_return_arrive_before="07:15",
        calendar_keywords=["prova"],
    )

    loaded = load_json_trips(settings)
    assert loaded is not None and len(loaded) == 2
    assert loaded[0].origin == "rio-de-janeiro-rj"
    assert loaded[0].destination == "cacapava-sp"
    assert loaded[0].hubs == ["sao-jose-dos-campos-sp"]
    assert loaded[1].outbound is not None
    assert loaded[1].outbound.date == ev_date - timedelta(days=1)

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ev-100@example.com
SUMMARY:Prova Presencial
DTSTART;VALUE=DATE:{ev_date.strftime('%Y%m%d')}
DESCRIPTION:destino: sao-paulo-sp
END:VEVENT
BEGIN:VEVENT
UID:ev-101@example.com
SUMMARY:Reuniao Online Ignorada
DTSTART;VALUE=DATE:{ev_date.strftime('%Y%m%d')}
END:VEVENT
END:VCALENDAR
"""
    ics_trips = parse_ics(ics_content, settings)
    assert len(ics_trips) == 1
    assert ics_trips[0].destination == "sao-paulo-sp"

    storage = Storage(tmp_path / "test.db")
    try:
        upserted, removed = storage.sync_source(TripSource.JSON, loaded)
        assert (upserted, removed) == (2, 0)
        assert len(storage.list_trips()) == 2

        storage.save_snapshot(loaded[0].id, "ida", None, 0, Level.NO_DATA)
        assert storage.last_snapshot(loaded[0].id, "ida") is not None
    finally:
        storage.close()
