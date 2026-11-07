"""Busca de ofertas e montagem de itinerários (direto, via hub com conexão local ou com baldeação)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable

from .config import Settings
from .models import Itinerary, LegSpec, Offer
from .providers import BaseProvider, ProviderError

log = logging.getLogger(__name__)

# Espera máxima aceitável entre dois ônibus numa baldeação.
MAX_CONNECTION_WAIT = timedelta(hours=6)

FetchFn = Callable[[str, str, date], Awaitable[list[Offer]]]


def _to_naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


class OfferSearch:
    """Consulta todos os provedores habilitados, com busca concorrente e cache por execução."""

    def __init__(self, providers: list[BaseProvider], on_offers: Callable[[date, list[Offer]], None] | None = None):
        self.providers = providers
        self.on_offers = on_offers
        self._cache: dict[tuple[str, str, date], list[Offer]] = {}
        self.errors: list[str] = []

    async def fetch(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        key = (origin, destination, travel_date)
        if key in self._cache:
            return self._cache[key]

        async def _query(p: BaseProvider) -> list[Offer]:
            try:
                return await p.search(origin, destination, travel_date)
            except ProviderError as exc:
                msg = f"{p.name}: {exc}"
                log.warning(msg)
                if msg not in self.errors:
                    self.errors.append(msg)
                return []
            except Exception as exc:
                log.warning("Erro no provedor %s: %s", p.name, exc)
                return []

        # Executa todos os provedores em paralelo para máxima velocidade
        results = await asyncio.gather(*(_query(p) for p in self.providers))
        offers: list[Offer] = [o for r in results for o in r]

        self._cache[key] = offers
        if self.on_offers and offers:
            self.on_offers(travel_date, offers)
        return offers


def _local_segment(origin: str, destination: str, depart_at, minutes: int, cost: float) -> Offer:
    return Offer(
        provider="local",
        origin=origin,
        destination=destination,
        depart_at=depart_at,
        arrive_at=depart_at + timedelta(minutes=minutes),
        price=cost,
        seat_type="conexão local (estimada)",
        company="Transporte local",
        is_estimate=True,
    )


def _itinerary_matches_spec(spec: LegSpec, it: Itinerary) -> bool:
    """Verifica se o itinerário atende aos filtros de data/horário da especificação.

    Para trechos que começam com conexão local estimada (ex.: Jundiaí -> Campinas),
    o cálculo retroativo do deslocamento pode cair na noite do dia anterior
    (ex.: ônibus às 00:20 com deslocamento local às 23:15 da véspera). Avaliar
    o embarque no ônibus principal (main_segment) garante que viagens válidas
    no dia pretendido não sejam incorretamente descartadas.
    """
    dep = it.main_segment.depart_at if it.segments[0].is_estimate else it.depart_at
    if spec.accepts(dep, it.arrive_at):
        return True
    return spec.accepts(it.depart_at, it.arrive_at)


async def build_itineraries(
    origin: str,
    destination: str,
    spec: LegSpec,
    hubs: list[str],
    fetch: FetchFn,
    settings: Settings,
) -> list[Itinerary]:
    """Monta e filtra os itinerários válidos para um trecho, ordenados por preço."""
    itineraries: list[Itinerary] = []
    min_conn = timedelta(minutes=settings.min_connection_minutes)

    for d in spec.search_dates():
        # 1) Direto
        for offer in await fetch(origin, destination, d):
            itineraries.append(Itinerary([offer]))

        if settings.max_transfers < 1:
            continue

        # 2) Via hubs (inclui hubs informados + hubs com conexão local cadastrada para a origem/destino)
        effective_hubs = list(hubs)
        for conn in settings.local_connections:
            if conn.city_a == destination and conn.city_b not in effective_hubs:
                effective_hubs.append(conn.city_b)
            elif conn.city_b == destination and conn.city_a not in effective_hubs:
                effective_hubs.append(conn.city_a)
            elif conn.city_a == origin and conn.city_b not in effective_hubs:
                effective_hubs.append(conn.city_b)
            elif conn.city_b == origin and conn.city_a not in effective_hubs:
                effective_hubs.append(conn.city_a)

        for hub in effective_hubs:
            if hub in (origin, destination):
                continue

            conn_dest = settings.local_connection(hub, destination)
            conn_orig = settings.local_connection(origin, hub)

            if conn_dest:
                # Ônibus até o hub + conexão local estimada até o destino final.
                for first in await fetch(origin, hub, d):
                    local = _local_segment(
                        hub, destination, first.arrive_at + timedelta(minutes=10),
                        conn_dest.minutes, conn_dest.cost,
                    )
                    itineraries.append(Itinerary([first, local]))
            elif conn_orig:
                # Conexão local estimada até o hub + ônibus do hub até o destino.
                # Busca também no início do dia seguinte (d + 1), pois um ônibus saindo
                # do hub na madrugada (ex.: 00h20) tem sua partida calculada na cidade de origem
                # antes da meia-noite (ex.: 23h15 de d), pertencendo perfeitamente à janela de d!
                hub_offers = list(await fetch(hub, destination, d))
                hub_offers.extend(await fetch(hub, destination, d + timedelta(days=1)))
                for second in hub_offers:
                    start = second.depart_at - min_conn - timedelta(minutes=conn_orig.minutes)
                    local = _local_segment(origin, hub, start, conn_orig.minutes, conn_orig.cost)
                    itineraries.append(Itinerary([local, second]))
            else:
                # Baldeação real: dois ônibus pesquisados nos provedores.
                # Se não houver segundo ônibus na plataforma, trata o hub como ponto de
                # desembarque/embarque próximo com deslocamento local até o destino final.
                firsts = await fetch(origin, hub, d)
                arrival_dates = sorted({f.arrive_at.date() for f in firsts})
                seconds: list[Offer] = []
                for ad in arrival_dates:
                    seconds.extend(await fetch(hub, destination, ad))

                paired = 0
                for first in firsts:
                    for second in seconds:
                        wait = _to_naive(second.depart_at) - _to_naive(first.arrive_at)
                        if min_conn <= wait <= MAX_CONNECTION_WAIT:
                            itineraries.append(Itinerary([first, second]))
                            paired += 1

                if paired == 0 and firsts:
                    for first in firsts:
                        local = _local_segment(
                            hub, destination, _to_naive(first.arrive_at) + timedelta(minutes=10), 30, 0.0
                        )
                        itineraries.append(Itinerary([first, local]))
                elif paired == 0 and not firsts:
                    for second in await fetch(hub, destination, d):
                        start = _to_naive(second.depart_at) - min_conn - timedelta(minutes=30)
                        local = _local_segment(origin, hub, start, 30, 0.0)
                        itineraries.append(Itinerary([local, second]))

    valid = [it for it in itineraries if _itinerary_matches_spec(spec, it)]

    unique: dict[str, Itinerary] = {}
    for it in valid:
        unique.setdefault(it.key(), it)
    result = sorted(unique.values(), key=lambda it: (it.price, it.transfers, _to_naive(it.arrive_at)))
    log.debug(
        "Trecho %s -> %s (%s): %d opções brutas, %d válidas",
        origin, destination, spec.date, len(itineraries), len(result),
    )
    return result
