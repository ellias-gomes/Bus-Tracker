"""Provedor Viação Águia Branca.

Utiliza os serviços REST oficiais do portal Águia Branca (SAP Commerce Cloud / Hybris):
1. Resolução de IDs de cidade via `/travel/origins/search?term=...` e `/travel/destinations/search?term=...`
2. Consulta de horários e tarifas via `POST /search-travel`
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from ..models import Offer
from .base import BaseProvider, ProviderError

log = logging.getLogger(__name__)

SITE_URL = "https://www.aguiabranca.com.br"
API_BASE = f"{SITE_URL}/aguiabrancacommercewebservices/v2/aguiaBranca"

_GLOBAL_ORIGIN_CACHE: dict[str, str | None] = {}
_GLOBAL_DEST_CACHE: dict[str, str | None] = {}


def _normalize_name(value: str) -> str:
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "", s).lower()


class AguiaBrancaProvider(BaseProvider):
    name = "aguiabranca"
    experimental = False

    def __init__(self, session):
        super().__init__(session)

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return f"{SITE_URL}/onibus/{origin}/{destination}"

    async def _resolve_location_id(self, city_slug: str, is_origin: bool) -> str | None:
        cache = _GLOBAL_ORIGIN_CACHE if is_origin else _GLOBAL_DEST_CACHE
        if city_slug in cache:
            return cache[city_slug]

        parts = city_slug.strip().rsplit("-", 1)
        if len(parts) != 2:
            cache[city_slug] = None
            return None

        city_term = parts[0].replace("-", " ")
        target_norm = _normalize_name(parts[0])
        endpoint = "origins" if is_origin else "destinations"
        url = f"{API_BASE}/travel/{endpoint}/search"
        headers = {
            "Accept": "application/json",
            "Referer": f"{SITE_URL}/",
        }

        try:
            resp = await self.session.get(url, headers=headers, params={"term": city_term})
        except ProviderError as exc:
            log.warning("Águia Branca: falha ao buscar localidade %s (%s)", city_slug, exc)
            return None

        if resp.status_code != 200:
            cache[city_slug] = None
            return None

        locs = resp.json().get("locations") or []
        for loc in locs:
            cidade = loc.get("cidade") or ""
            if target_norm in _normalize_name(cidade):
                loc_id = str(loc.get("id") or "")
                if loc_id:
                    cache[city_slug] = loc_id
                    return loc_id

        cache[city_slug] = None
        return None

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        orig_id = await self._resolve_location_id(origin, is_origin=True)
        if not orig_id:
            log.debug("Águia Branca: origem %s não atendida", origin)
            return []

        dest_id = await self._resolve_location_id(destination, is_origin=False)
        if not dest_id:
            log.debug("Águia Branca: destino %s não atendido", destination)
            return []

        url = f"{API_BASE}/search-travel"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": f"{SITE_URL}/",
        }
        body = {
            "origin": orig_id,
            "destination": dest_id,
            "goingDate": travel_date.strftime("%d/%m/%Y"),
            "adult": "1",
        }

        try:
            resp = await self.session.post(url, headers=headers, json=body)
        except ProviderError as exc:
            log.warning("Águia Branca: falha na busca (%s)", exc)
            return []

        if resp.status_code != 200:
            log.info("Águia Branca respondeu HTTP %s para %s -> %s", resp.status_code, origin, destination)
            return []

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError(f"Águia Branca: resposta JSON inválida ({exc})") from exc

        return self.parse(data, origin, destination, travel_date)

    def parse(
        self, data: dict[str, Any], origin: str, destination: str, travel_date: date
    ) -> list[Offer]:
        offers: list[Offer] = []
        services = (data.get("toGo") or {}).get("lsServicos") or []
        url = self.booking_url(origin, destination, travel_date)

        for s in services:
            if not isinstance(s, dict):
                continue
            offer = self._service_to_offer(s, origin, destination, url)
            if offer is not None:
                offers.append(offer)

        log.debug("Águia Branca: %d ofertas para %s -> %s em %s", len(offers), origin, destination, travel_date)
        return offers

    def _service_to_offer(
        self, s: dict[str, Any], origin: str, destination: str, booking_url: str
    ) -> Offer | None:
        try:
            raw_depart = s.get("departure")
            raw_arrive = s.get("arrival")
            if not raw_depart or not raw_arrive:
                return None

            depart_at = datetime.strptime(raw_depart.strip(), "%d/%m/%Y %H:%M")
            arrive_at = datetime.strptime(raw_arrive.strip(), "%d/%m/%Y %H:%M")

            raw_price = s.get("price")
            if raw_price is None:
                return None
            price = round(float(raw_price), 2)
            if price <= 0:
                return None

            seats: int | None = None
            raw_seats = str(s.get("freeSeats") or "").strip()
            if raw_seats.isdigit():
                seats = int(raw_seats)

            seat_type = str(s.get("serviceClass") or s.get("descClass") or "").strip()
            company = str(s.get("company") or "Viação Águia Branca").strip()
            boarding = str(s.get("originDesc") or "").strip()
            alighting = str(s.get("destinationDesc") or "").strip()

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
            log.debug("Águia Branca: serviço ignorado (%s)", exc)
            return None
