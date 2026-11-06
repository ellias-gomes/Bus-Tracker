"""Provedor ClickBus (EXPERIMENTAL / desabilitado por padrão).

Situação verificada em 11/2026:
- A página de resultados é um app Next.js que carrega as viagens no navegador, via
  `https://bff.clickbus.com/web/api/v6/trips?from=<slug>&to=<slug>&departureDate=AAAA-MM-DD&clientId=...`.
- Chamadas diretas a esse endpoint retornam `403 ST: Forbidden request`, ou seja, ele exige uma
  credencial/sessão emitida pelo front-end oficial.

Este projeto NÃO tenta contornar esse controle de acesso. O conector fica pronto para ser usado caso
a ClickBus ofereça um acesso autorizado (ex.: API de parceiros/afiliados): basta definir
`CLICKBUS_API_BASE` / `CLICKBUS_API_TOKEN` no `.env` e adicionar `clickbus` em `ENABLED_PROVIDERS`.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime

from ..models import Offer
from .base import BaseProvider, ProviderError

log = logging.getLogger(__name__)


class ClickBusProvider(BaseProvider):
    name = "clickbus"
    experimental = True

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return (
            f"https://www.clickbus.com.br/onibus/{origin}/{destination}"
            f"?departureDate={travel_date.isoformat()}"
        )

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        base = os.getenv("CLICKBUS_API_BASE", "").rstrip("/")
        token = os.getenv("CLICKBUS_API_TOKEN", "")
        if not base or not token:
            raise ProviderError(
                "ClickBus requer acesso autorizado (CLICKBUS_API_BASE/CLICKBUS_API_TOKEN). "
                "O endpoint público do site bloqueia chamadas diretas."
            )
        resp = await self.session.get(
            f"{base}/trips",
            params={"from": origin, "to": destination, "departureDate": travel_date.isoformat()},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code in (401, 403):
            raise ProviderError(f"ClickBus negou acesso (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ProviderError(f"ClickBus respondeu HTTP {resp.status_code}")
        return self.parse(resp.json(), origin, destination, travel_date)

    def parse(self, data: dict, origin: str, destination: str, travel_date: date) -> list[Offer]:
        """Parser defensivo do formato `trips[].parts[]` usado pelo front-end da ClickBus.

        Não validado contra respostas reais (sem acesso autorizado); ajuste quando houver.
        """
        offers: list[Offer] = []
        url = self.booking_url(origin, destination, travel_date)
        for trip in data.get("trips") or []:
            parts = trip.get("parts") or []
            if len(parts) != 1:
                continue  # conexões da própria ClickBus ficam fora nesta versão
            part = parts[0]
            try:
                price = (trip.get("price") or part.get("price") or {}).get("total") or trip.get("price")
                offers.append(
                    Offer(
                        provider=self.name,
                        origin=origin,
                        destination=destination,
                        depart_at=datetime.fromisoformat(part["departure"]["schedule"]),
                        arrive_at=datetime.fromisoformat(part["arrival"]["schedule"]),
                        price=round(float(price), 2),
                        seats=part.get("availableSeats"),
                        seat_type=str(part.get("busClass") or part.get("serviceClass") or ""),
                        company=str((part.get("busCompany") or {}).get("name") or ""),
                        boarding_point=str((part.get("departure") or {}).get("place", {}).get("name", "")),
                        alighting_point=str((part.get("arrival") or {}).get("place", {}).get("name", "")),
                        url=url,
                    )
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                log.debug("ClickBus: viagem ignorada (%s)", exc)
        return offers
