from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from bustracker.config import LocalConnection, Settings
from bustracker.models import LegSpec, Offer
from bustracker.routing import build_itineraries

TZ = ZoneInfo("America/Sao_Paulo")


def test_leg_spec_window_and_arrival_deadline():
    # Janela de ida: segunda até 22:00
    spec_out = LegSpec(
        date=date(2026, 11, 23),
        depart_after=time(18, 0),
        depart_before=time(22, 0),
    )
    assert spec_out.accepts(
        datetime(2026, 11, 23, 21, 30, tzinfo=TZ),
        datetime(2026, 11, 24, 3, 0, tzinfo=TZ),
    )
    assert not spec_out.accepts(
        datetime(2026, 11, 23, 22, 30, tzinfo=TZ),
        datetime(2026, 11, 24, 4, 0, tzinfo=TZ),
    )

    # Janela de volta atravessando meia-noite (21:00 -> 01:00) com chegada até 07:15 no dia seguinte
    spec_ret = LegSpec(
        date=date(2026, 11, 24),
        depart_after=time(21, 0),
        depart_before=time(1, 0),
        arrive_before=time(7, 15),
        arrive_day_offset=1,
    )
    assert spec_ret.crosses_midnight
    assert spec_ret.search_dates() == [date(2026, 11, 24), date(2026, 11, 25)]
    assert spec_ret.accepts(
        datetime(2026, 11, 25, 0, 30, tzinfo=TZ),
        datetime(2026, 11, 25, 6, 45, tzinfo=TZ),
    )
    assert not spec_ret.accepts(
        datetime(2026, 11, 24, 23, 0, tzinfo=TZ),
        datetime(2026, 11, 25, 7, 45, tzinfo=TZ),
    )


def test_build_itineraries_with_hub_and_local_connection():
    settings = Settings(
        max_transfers=1,
        local_connections=[LocalConnection("sao-jose-dos-campos-sp", "cacapava-sp", 12.0, 35)],
    )
    spec = LegSpec(
        date=date(2026, 11, 23),
        depart_after=time(18, 0),
        depart_before=time(22, 0),
    )

    async def fake_fetch(origin: str, destination: str, travel_date: date) -> list[Offer]:
        if origin == "rio-de-janeiro-rj" and destination == "cacapava-sp":
            return []  # Sem direto
        if origin == "rio-de-janeiro-rj" and destination == "sao-jose-dos-campos-sp":
            return [
                Offer(
                    provider="buser",
                    origin=origin,
                    destination=destination,
                    depart_at=datetime(2026, 11, 23, 21, 0, tzinfo=TZ),
                    arrive_at=datetime(2026, 11, 24, 2, 0, tzinfo=TZ),
                    price=59.90,
                    seats=8,
                    seat_type="semi leito",
                    company="Buser",
                    alighting_point="Posto da Gruta (São José dos Campos)",
                ),
                # Fora da janela (22:45 > 22:00)
                Offer(
                    provider="buser",
                    origin=origin,
                    destination=destination,
                    depart_at=datetime(2026, 11, 23, 22, 45, tzinfo=TZ),
                    arrive_at=datetime(2026, 11, 24, 3, 30, tzinfo=TZ),
                    price=49.90,
                    seats=10,
                ),
            ]
        return []

    its = asyncio.run(
        build_itineraries(
            "rio-de-janeiro-rj",
            "cacapava-sp",
            spec,
            ["sao-jose-dos-campos-sp"],
            fake_fetch,
            settings,
        )
    )
    assert len(its) == 1
    it = its[0]
    assert it.transfers == 1
    assert it.price == 71.90
    assert it.seats == 8
    assert it.segments[1].is_estimate
