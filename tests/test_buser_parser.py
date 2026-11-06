from __future__ import annotations

import json
from datetime import date

from bustracker.providers.base import HttpSession
from bustracker.providers.buser import BuserProvider
from bustracker.utils.nuxt import decode_devalue


def test_decode_devalue_handles_refs_and_sets():
    flat = [
        {"items": 1, "tags": 4},
        ["Ref", 2],
        [3],
        "ok",
        ["Set", 5],
        "promo",
    ]
    decoded = decode_devalue(flat)
    assert decoded == {"items": ["ok"], "tags": ["promo"]}


def test_buser_provider_parses_ssr_html():
    # Monta um payload __NUXT_DATA__ realista
    flat = [
        {"pinia": 1},
        {"search": 2},
        {"trechoNaoEncontrado": False, "results": 3},
        {"groups_by_date": 4},
        [5],
        {"datetime_ida": "2026-11-23", "grupos": 6},
        [7, 10],
        {
            "id": 12,
            "closed": False,
            "grupo_classe_closed": False,
            "max_split_value": 64.9,
            "preco_base": 89.9,
            "vagas": 11,
            "modelo_venda": "buser",
            "datetime_ida": "2026-11-23T21:15:00-03:00",
            "chegada_ida": "2026-11-24T02:30:00-03:00",
            "tipo_assento": "semi leito",
            "company_friendly_name": "Parceira Buser",
            "origem": 8,
            "destino": 9,
        },
        {"nickname": "Posto Estação", "name": "Rio de Janeiro", "slug": "rio-de-janeiro-rj"},
        {"nickname": "Posto da Gruta", "name": "São José dos Campos", "slug": "sao-jose-dos-campos-sp"},
        {
            "closed": True,
            "max_split_value": 49.9,
            "vagas": 11,
            "datetime_ida": "2026-11-23T20:00:00-03:00",
            "chegada_ida": "2026-11-24T01:00:00-03:00",
        },
        13,
        "Bwgrcl",
    ]
    html = f'<html><body><script id="__NUXT_DATA__" type="application/json">{json.dumps(flat)}</script></body></html>'
    session = HttpSession()
    try:
        provider = BuserProvider(session)
        offers = provider.parse(
            html,
            "rio-de-janeiro-rj",
            "sao-jose-dos-campos-sp",
            date(2026, 11, 23),
            "https://www.buser.com.br/onibus/rio-de-janeiro-rj/sao-jose-dos-campos-sp?ida=2026-11-23",
        )
    finally:
        import asyncio
        asyncio.run(session.aclose())

    assert len(offers) == 1
    o = offers[0]
    assert o.price == 64.9
    assert o.seats == 13
    assert o.seats_capped is True
    assert o.seat_type == "semi leito"
    assert "Posto da Gruta" in o.alighting_point
    assert o.url == (
        "https://www.buser.com.br/onibus/rio-de-janeiro-rj/sao-jose-dos-campos-sp"
        "?ida=2026-11-23&idGrupoDestaque=Bwgrcl&idGrupoAdicional=Bwgrcl"
    )
