from __future__ import annotations

import asyncio
from datetime import date, datetime

import pytest

from bustracker.providers import REGISTRY, build_providers
from bustracker.providers.aguia_branca import AguiaBrancaProvider
from bustracker.providers.base import HttpSession
from bustracker.providers.cometa import CometaProvider, _normalize_name
from bustracker.providers.guanabara import GuanabaraProvider, slug_to_guanabara_city


def test_registry_contains_new_providers():
    assert "guanabara" in REGISTRY
    assert "cometa" in REGISTRY
    assert "aguiabranca" in REGISTRY
    assert REGISTRY["guanabara"] is GuanabaraProvider
    assert REGISTRY["cometa"] is CometaProvider
    assert REGISTRY["aguiabranca"] is AguiaBrancaProvider


def test_build_providers_creates_instances():
    session = HttpSession()
    try:
        providers = build_providers(["guanabara", "cometa", "aguiabranca", "buser"], session)
        names = [p.name for p in providers]
        assert names == ["guanabara", "cometa", "aguiabranca", "buser"]
    finally:
        asyncio.run(session.aclose())


def test_slug_to_guanabara_city():
    assert slug_to_guanabara_city("rio-de-janeiro-rj") == "RIO DE JANEIRO - RJ"
    assert slug_to_guanabara_city("sao-jose-dos-campos-sp") == "SAO JOSE DOS CAMPOS - SP"
    assert slug_to_guanabara_city("taubate-sp") == "TAUBATE - SP"
    assert slug_to_guanabara_city("campinas-sp") == "CAMPINAS - SP"


def test_guanabara_parse():
    session = HttpSession()
    try:
        provider = GuanabaraProvider(session)
        mock_data = {
            "trips": [
                {
                    "company": "SAMPAIO",
                    "class_of_service": "SEMI LEITO",
                    "total": 78.79,
                    "origin": {
                        "date_time": "2026-11-16T07:30:00",
                        "location": "RIO DE JANEIRO - RJ",
                        "address": "Rodoviária Novo Rio",
                    },
                    "destination": {
                        "date_time": "2026-11-16T13:30:00",
                        "location": "SAO JOSE DOS CAMPOS - SP",
                        "address": "Rodoviária de São José dos Campos",
                    },
                    "routes": [
                        {"available_seats": 26}
                    ],
                },
                {
                    # Viagem inválida/sem preço deve ser ignorada
                    "total": 0,
                    "origin": {"date_time": "2026-11-16T09:00:00"},
                    "destination": {"date_time": "2026-11-16T15:00:00"},
                }
            ]
        }
        offers = provider.parse(
            mock_data,
            "rio-de-janeiro-rj",
            "sao-jose-dos-campos-sp",
            date(2026, 11, 16),
        )
        assert len(offers) == 1
        o = offers[0]
        assert o.provider == "guanabara"
        assert o.company == "SAMPAIO"
        assert o.seat_type == "SEMI LEITO"
        assert o.price == 78.79
        assert o.seats == 26
        assert o.depart_at == datetime(2026, 11, 16, 7, 30)
        assert o.arrive_at == datetime(2026, 11, 16, 13, 30)
        assert "Novo Rio" in o.boarding_point
        assert "viajeguanabara.com.br/onibus" in o.url
    finally:
        asyncio.run(session.aclose())


def test_cometa_match_place_and_parse():
    session = HttpSession()
    try:
        provider = CometaProvider(session)
        places = [
            {"id": -1, "city": "São Paulo (Todos)", "state": "SP"},
            {"id": 18697, "city": "São Paulo (Rod. Tietê)", "state": "SP"},
            {"id": 19301, "city": "Campinas", "state": "SP"},
            {"id": 14199, "city": "Rio de Janeiro (Novo Rio)", "state": "RJ"},
        ]
        # Preferência por (Todos) quando disponível
        assert provider._match_place(places, "sao-paulo-sp") == -1
        assert provider._match_place(places, "campinas-sp") == 19301
        assert provider._match_place(places, "rio-de-janeiro-rj") == 14199
        assert provider._match_place(places, "curitiba-pr") is None

        mock_data = {
            "result": {
                "servicesList": [
                    {
                        "departureDate": "2026-11-16T05:00:00",
                        "arrivalDate": "2026-11-16T06:30:00",
                        "price": 59.4,
                        "freeSeats": 44,
                        "class": "CONVENCIONAL",
                        "company": "VIACAO COMETA S A",
                        "originDesc": "São Paulo (Rod. Tietê)",
                        "destinationDesc": "Campinas",
                    }
                ]
            }
        }
        offers = provider.parse(
            mock_data,
            "sao-paulo-sp",
            "campinas-sp",
            date(2026, 11, 16),
        )
        assert len(offers) == 1
        o = offers[0]
        assert o.provider == "cometa"
        assert o.company == "VIACAO COMETA S A"
        assert o.seat_type == "CONVENCIONAL"
        assert o.price == 59.4
        assert o.seats == 44
        assert o.depart_at == datetime(2026, 11, 16, 5, 0)
        assert o.arrive_at == datetime(2026, 11, 16, 6, 30)
    finally:
        asyncio.run(session.aclose())


def test_aguia_branca_parse():
    session = HttpSession()
    try:
        provider = AguiaBrancaProvider(session)
        mock_data = {
            "toGo": {
                "lsServicos": [
                    {
                        "departure": "16/11/2026 07:30",
                        "arrival": "16/11/2026 17:20",
                        "price": 172.63,
                        "freeSeats": "5",
                        "serviceClass": "DD - SEMILEITO",
                        "company": "VIACAO AGUIA BRANCA SA",
                        "originDesc": "Terminal Novo Rio",
                        "destinationDesc": "Rodoviária de Vitória",
                    }
                ]
            }
        }
        offers = provider.parse(
            mock_data,
            "rio-de-janeiro-rj",
            "vitoria-es",
            date(2026, 11, 16),
        )
        assert len(offers) == 1
        o = offers[0]
        assert o.provider == "aguiabranca"
        assert o.company == "VIACAO AGUIA BRANCA SA"
        assert o.seat_type == "DD - SEMILEITO"
        assert o.price == 172.63
        assert o.seats == 5
        assert o.depart_at == datetime(2026, 11, 16, 7, 30)
        assert o.arrive_at == datetime(2026, 11, 16, 17, 20)
        assert "aguiabranca.com.br/onibus" in o.url
    finally:
        asyncio.run(session.aclose())


def test_http_session_has_post():
    session = HttpSession()
    assert hasattr(session, "get")
    assert hasattr(session, "post")
    assert hasattr(session, "request")
    asyncio.run(session.aclose())
