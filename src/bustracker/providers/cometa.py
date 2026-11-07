"""Provedor Viação Cometa (Grupo JCA - Cometa, 1001, Catarinense).

Utiliza os serviços REST oficiais do Grupo JCA integrados ao portal da Viação Cometa:
1. Obtenção de authorizationId via `/content/jca/cometa/pt-br/jcr:content.authorization.json?clear=1`
2. Autenticação OAuth2 via `https://api.jcatlm.com.br/oauth/v3/login`
3. Consulta de localidades e rotas via `https://api.jcatlm.com.br/route/v1/getRoutes`
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from datetime import date, datetime
from typing import Any

from ..models import Offer
from .base import BaseProvider, ProviderError

log = logging.getLogger(__name__)

SITE_URL = "https://www.viacaocometa.com.br"
API_URL = "https://api.jcatlm.com.br"
CLIENT_ID = "52a68031-74aa-4635-9eb0-448f699d5be5"
COMPANY_ID = "7"  # Viação Cometa

_GLOBAL_ACCESS_TOKEN: str = ""
_GLOBAL_TOKEN_EXPIRES_AT: float = 0.0
_GLOBAL_ORIGINS_CACHE: list[dict[str, Any]] | None = None
_GLOBAL_DESTINATIONS_CACHE: dict[int, list[dict[str, Any]]] = {
    -41: [  # Rio de Janeiro (Todos)
        {"id": -1, "city": "São Paulo (Todos)", "state": "SP"},
        {"id": 19288, "city": "Aparecida", "state": "SP"},
        {"id": 19301, "city": "Campinas", "state": "SP"},
        {"id": 21737, "city": "São Paulo (Rod. Barra Funda)", "state": "SP"},
        {"id": 18697, "city": "São Paulo (Rod. Tietê)", "state": "SP"},
    ],
    -1: [  # São Paulo (Todos)
        {"id": -41, "city": "Rio de Janeiro (Todos)", "state": "RJ"},
        {"id": 14199, "city": "Rio de Janeiro (Novo Rio)", "state": "RJ"},
        {"id": 19288, "city": "Aparecida", "state": "SP"},
        {"id": 19301, "city": "Campinas", "state": "SP"},
        {"id": 19030, "city": "Santos - Terminal Rodoviário", "state": "SP"},
    ],
    19265: [  # São José dos Campos
        {"id": -41, "city": "Rio de Janeiro (Todos)", "state": "RJ"},
        {"id": 14199, "city": "Rio de Janeiro (Novo Rio)", "state": "RJ"},
        {"id": 19030, "city": "Santos - Terminal Rodoviário", "state": "SP"},
    ],
    19288: [  # Aparecida
        {"id": -41, "city": "Rio de Janeiro (Todos)", "state": "RJ"},
        {"id": 14199, "city": "Rio de Janeiro (Novo Rio)", "state": "RJ"},
        {"id": -1, "city": "São Paulo (Todos)", "state": "SP"},
        {"id": 18697, "city": "São Paulo (Rod. Tietê)", "state": "SP"},
        {"id": 19301, "city": "Campinas", "state": "SP"},
    ],
}
_GLOBAL_LOCK = asyncio.Lock()


def _normalize_name(value: str) -> str:
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "", s).lower()


class CometaProvider(BaseProvider):
    name = "cometa"
    experimental = False

    def __init__(self, session):
        super().__init__(session)

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return f"{SITE_URL}/"

    async def _ensure_token(self) -> str:
        global _GLOBAL_ACCESS_TOKEN, _GLOBAL_TOKEN_EXPIRES_AT
        async with _GLOBAL_LOCK:
            now = time.time()
            if _GLOBAL_ACCESS_TOKEN and now < _GLOBAL_TOKEN_EXPIRES_AT:
                return _GLOBAL_ACCESS_TOKEN

            auth_url = f"{SITE_URL}/content/jca/cometa/pt-br/jcr:content.authorization.json?clear=1"
            headers_auth = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{SITE_URL}/",
                "X-Requested-With": "XMLHttpRequest",
            }
            resp_auth = await self.session.get(auth_url, headers=headers_auth)
            if resp_auth.status_code != 200:
                raise ProviderError(f"Cometa: falha na autorização (HTTP {resp_auth.status_code})")

            auth_id = (resp_auth.json().get("result") or {}).get("authorizationId")
            if not auth_id:
                raise ProviderError("Cometa: authorizationId ausente na resposta")

            login_url = f"{API_URL}/oauth/v3/login"
            login_headers = {
                "Referer": f"{SITE_URL}/",
                "Origin": SITE_URL,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": auth_id,
                "x-site-company-id": COMPANY_ID,
            }
            resp_login = await self.session.post(
                login_url,
                headers=login_headers,
                json={"grant_type": "client_credentials"},
            )
            if resp_login.status_code not in (200, 201):
                raise ProviderError(f"Cometa: falha no login OAuth (HTTP {resp_login.status_code})")

            data = resp_login.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in") or 3600)
            if not token:
                raise ProviderError("Cometa: access_token ausente na resposta de login")

            _GLOBAL_ACCESS_TOKEN = token
            _GLOBAL_TOKEN_EXPIRES_AT = now + max(60, expires_in - 60)
            return _GLOBAL_ACCESS_TOKEN

    def _api_headers(self, token: str) -> dict[str, str]:
        return {
            "Referer": f"{SITE_URL}/",
            "Origin": SITE_URL,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "client_id": CLIENT_ID,
            "access_token": token,
            "x-site-company-id": COMPANY_ID,
        }

    async def _get_origins(self, token: str) -> list[dict[str, Any]]:
        global _GLOBAL_ORIGINS_CACHE
        if _GLOBAL_ORIGINS_CACHE is not None:
            return _GLOBAL_ORIGINS_CACHE
        async with _GLOBAL_LOCK:
            if _GLOBAL_ORIGINS_CACHE is not None:
                return _GLOBAL_ORIGINS_CACHE
            try:
                resp = await self.session.get(
                    f"{API_URL}/place/v1/searchOrigin", headers=self._api_headers(token)
                )
                if resp.status_code == 200:
                    _GLOBAL_ORIGINS_CACHE = resp.json().get("result") or []
                    return _GLOBAL_ORIGINS_CACHE
            except Exception as exc:
                log.debug("Cometa: falha ao buscar origens: %s", exc)
                _GLOBAL_ORIGINS_CACHE = []
        return _GLOBAL_ORIGINS_CACHE or []

    async def _get_destinations(self, origin_id: int, token: str) -> list[dict[str, Any]]:
        if origin_id in _GLOBAL_DESTINATIONS_CACHE:
            return _GLOBAL_DESTINATIONS_CACHE[origin_id]
        async with _GLOBAL_LOCK:
            if origin_id in _GLOBAL_DESTINATIONS_CACHE:
                return _GLOBAL_DESTINATIONS_CACHE[origin_id]
            try:
                resp = await self.session.get(
                    f"{API_URL}/place/v1/searchDestination",
                    headers=self._api_headers(token),
                    params={"originId": str(origin_id)},
                )
                if resp.status_code == 200:
                    dests = resp.json().get("result") or []
                    _GLOBAL_DESTINATIONS_CACHE[origin_id] = dests
                    return dests
            except Exception as exc:
                log.debug("Cometa: falha ao buscar destinos para origem %s: %s", origin_id, exc)
                _GLOBAL_DESTINATIONS_CACHE[origin_id] = []
        return _GLOBAL_DESTINATIONS_CACHE.get(origin_id, [])

    def _match_place(self, places: list[dict[str, Any]], city_slug: str) -> int | None:
        parts = city_slug.strip().rsplit("-", 1)
        if len(parts) != 2:
            return None
        target_name = _normalize_name(parts[0])
        target_uf = parts[1].upper()

        candidates: list[tuple[int, int]] = []
        for p in places:
            p_state = (p.get("state") or "").upper()
            if p_state != target_uf:
                continue
            p_city = _normalize_name(p.get("city") or "")
            if target_name in p_city:
                p_id = p.get("id")
                if p_id is not None:
                    is_todos = "(todos)" in (p.get("city") or "").lower()
                    candidates.append((0 if is_todos else 1, int(p_id)))

        if candidates:
            candidates.sort()
            return candidates[0][1]
        return None

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        try:
            token = await self._ensure_token()
        except ProviderError as exc:
            log.warning("Cometa: autenticação indisponível (%s)", exc)
            return []

        origins = await self._get_origins(token)
        orig_id = self._match_place(origins, origin)
        if orig_id is None:
            log.debug("Cometa: origem %s não atendida", origin)
            return []

        destinations = await self._get_destinations(orig_id, token)
        dest_id = self._match_place(destinations, destination)
        if dest_id is None:
            log.debug("Cometa: destino %s não atendido a partir de %s", destination, origin)
            return []

        body = {
            "origin": orig_id,
            "destination": dest_id,
            "departureDate": travel_date.isoformat(),
            "availability": True,
            "SalePlatform": "SITES-UTP",
        }

        try:
            resp = await self.session.post(
                f"{API_URL}/route/v1/getRoutes",
                headers=self._api_headers(token),
                json=body,
            )
        except ProviderError as exc:
            log.warning("Cometa: falha ao buscar rotas (%s)", exc)
            return []

        if resp.status_code != 200:
            log.info("Cometa respondeu HTTP %s para %s -> %s", resp.status_code, origin, destination)
            return []

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError(f"Cometa: resposta JSON inválida ({exc})") from exc

        return self.parse(data, origin, destination, travel_date)

    def parse(
        self, data: dict[str, Any], origin: str, destination: str, travel_date: date
    ) -> list[Offer]:
        offers: list[Offer] = []
        services = (data.get("result") or {}).get("servicesList") or []
        url = self.booking_url(origin, destination, travel_date)

        for s in services:
            if not isinstance(s, dict):
                continue
            offer = self._service_to_offer(s, origin, destination, url)
            if offer is not None:
                offers.append(offer)

        log.debug("Cometa: %d ofertas para %s -> %s em %s", len(offers), origin, destination, travel_date)
        return offers

    def _service_to_offer(
        self, s: dict[str, Any], origin: str, destination: str, booking_url: str
    ) -> Offer | None:
        try:
            raw_depart = s.get("departureDate")
            raw_arrive = s.get("arrivalDate")
            if not raw_depart or not raw_arrive:
                return None

            depart_at = datetime.fromisoformat(raw_depart)
            arrive_at = datetime.fromisoformat(raw_arrive)

            raw_price = s.get("priceWithDiscount") or s.get("price")
            if raw_price is None:
                return None
            price = round(float(raw_price), 2)
            if price <= 0:
                return None

            seats: int | None = None
            raw_seats = s.get("freeSeats")
            if raw_seats is not None:
                try:
                    seats = int(raw_seats)
                except (ValueError, TypeError):
                    seats = None

            seat_type = str(s.get("class") or "").strip()
            company = str(s.get("company") or "Viação Cometa").strip()
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
            log.debug("Cometa: serviço ignorado (%s)", exc)
            return None
