"""Provedor Guanabara (Expresso Guanabara, Real Expresso, Util, Sampaio, Brisa).

A consulta é feita através do endpoint REST oficial consumido pelo front-end Next.js da plataforma:
`https://viajeguanabara.com.br/api/search/services/?origin=<ORIGEM>&destination=<DESTINO>&departure_date=<AAAA-MM-DD>&passengers=1:1`
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from ..models import Offer
from .base import BaseProvider, ProviderError

log = logging.getLogger(__name__)

BASE_URL = "https://viajeguanabara.com.br"


def slug_to_guanabara_city(slug: str) -> str:
    """Converte slug `cidade-uf` (ex: `sao-jose-dos-campos-sp`) para o padrão da Guanabara.

    Exemplo:
        `rio-de-janeiro-rj` -> `RIO DE JANEIRO - RJ`
        `sao-jose-dos-campos-sp` -> `SAO JOSE DOS CAMPOS - SP`
    """
    parts = slug.strip().rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 2:
        city = parts[0].replace("-", " ").upper()
        uf = parts[1].upper()
        return f"{city} - {uf}"
    return slug.replace("-", " ").upper()


class GuanabaraProvider(BaseProvider):
    name = "guanabara"
    experimental = False

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return (
            f"{BASE_URL}/onibus/{origin}/{destination}"
            f"?departure_date={travel_date.isoformat()}&passengers=1:1"
        )

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        orig_city = slug_to_guanabara_city(origin)
        dest_city = slug_to_guanabara_city(destination)
        iso_date = travel_date.isoformat()

        url = (
            f"{BASE_URL}/api/search/services/"
            f"?origin={orig_city}&destination={dest_city}&departure_date={iso_date}&passengers=1:1"
        )
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{BASE_URL}/",
        }

        try:
            resp = await self.session.get(url, headers=headers)
        except ProviderError as exc:
            log.warning("Guanabara: falha na requisição (%s)", exc)
            return []

        if resp.status_code == 404:
            log.info("Guanabara: trecho %s -> %s não encontrado", origin, destination)
            return []
        if resp.status_code != 200:
            raise ProviderError(f"Guanabara respondeu HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError(f"Guanabara: resposta JSON inválida ({exc})") from exc

        return self.parse(data, origin, destination, travel_date)

    def parse(
        self, data: dict[str, Any], origin: str, destination: str, travel_date: date
    ) -> list[Offer]:
        offers: list[Offer] = []
        trips = data.get("trips") or []
        url = self.booking_url(origin, destination, travel_date)

        for trip in trips:
            if not isinstance(trip, dict):
                continue
            offer = self._trip_to_offer(trip, origin, destination, url)
            if offer is not None:
                offers.append(offer)

        log.debug("Guanabara: %d ofertas para %s -> %s em %s", len(offers), origin, destination, travel_date)
        return offers

    def _trip_to_offer(
        self, trip: dict[str, Any], origin: str, destination: str, booking_url: str
    ) -> Offer | None:
        try:
            orig_info = trip.get("origin") or {}
            dest_info = trip.get("destination") or {}

            raw_depart = orig_info.get("date_time")
            raw_arrive = dest_info.get("date_time")
            if not raw_depart or not raw_arrive:
                return None

            depart_at = datetime.fromisoformat(raw_depart)
            arrive_at = datetime.fromisoformat(raw_arrive)

            raw_price = trip.get("total") or trip.get("sub_total") or trip.get("fare")
            if raw_price is None:
                return None
            price = round(float(raw_price), 2)
            if price <= 0:
                return None

            routes = trip.get("routes") or []
            seats: int | None = None
            if routes and isinstance(routes[0], dict):
                raw_seats = routes[0].get("available_seats")
                if raw_seats is not None:
                    try:
                        seats = int(raw_seats)
                    except (ValueError, TypeError):
                        seats = None

            company = str(trip.get("company") or "Guanabara").strip()
            seat_type = str(trip.get("class_of_service") or "").strip()
            boarding = str(orig_info.get("address") or orig_info.get("location") or "").strip()
            alighting = str(dest_info.get("address") or dest_info.get("location") or "").strip()

            return Offer(
                provider=self.name,
                origin=origin,
                destination=destination,
                depart_at=depart_at,
                arrive_at=arrive_at,
                price=price,
                seats=seats,
                seats_capped=False,
                seat_type=seat_type,
                company=company,
                boarding_point=boarding,
                alighting_point=alighting,
                url=booking_url,
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("Guanabara: viagem ignorada (%s)", exc)
            return None
