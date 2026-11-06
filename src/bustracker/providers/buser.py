"""Provedor Buser.

A página pública de busca (`/onibus/<origem>/<destino>?ida=AAAA-MM-DD`) é renderizada no servidor
(Nuxt 3) e já traz todos os grupos de viagem no payload `__NUXT_DATA__`. Assim conseguimos os dados
com uma única requisição GET leve, sem navegador headless.

Campos utilizados de cada grupo:
- `max_split_value`: preço exibido por passageiro;
- `preco_base`: preço "cheio" de referência (quando há desconto);
- `vagas`: assentos disponíveis (para fretamento Buser o site limita a exibição a 13);
- `datetime_ida` / `chegada_ida`: partida e chegada com fuso horário;
- `tipo_assento`, `company_friendly_name`, `origem.nickname`, `destino.nickname`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from ..models import Offer
from ..utils.nuxt import parse_nuxt_html
from .base import BaseProvider, ProviderError

log = logging.getLogger(__name__)

BASE_URL = "https://www.buser.com.br"
# Observado: para viagens de fretamento Buser o site exibe no máximo 13 vagas.
SEAT_DISPLAY_CAP = 13


def _find_key(obj: Any, key: str, depth: int = 0) -> dict | None:
    if depth > 10:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for value in obj.values():
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj[:50]:
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    return None


def _place_name(place: Any) -> str:
    if not isinstance(place, dict):
        return ""
    nickname = place.get("nickname") or ""
    city = place.get("name") or place.get("city_name") or ""
    if nickname and city:
        return f"{nickname} ({city})"
    return nickname or city


class BuserProvider(BaseProvider):
    name = "buser"

    def booking_url(
        self,
        origin: str,
        destination: str,
        travel_date: date,
        group_id: str | None = None,
    ) -> str:
        url = f"{BASE_URL}/onibus/{origin}/{destination}?ida={travel_date.isoformat()}"
        if group_id:
            url += f"&idGrupoDestaque={group_id}&idGrupoAdicional={group_id}"
        return url

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        url = self.booking_url(origin, destination, travel_date)
        resp = await self.session.get(url)
        if resp.status_code == 404:
            log.info("Buser: trecho %s -> %s não encontrado", origin, destination)
            return []
        if resp.status_code != 200:
            raise ProviderError(f"Buser respondeu HTTP {resp.status_code}")
        return self.parse(resp.text, origin, destination, travel_date, url)

    def parse(
        self, html: str, origin: str, destination: str, travel_date: date, url: str = ""
    ) -> list[Offer]:
        root = parse_nuxt_html(html)
        if root is None:
            raise ProviderError("Buser: payload __NUXT_DATA__ ausente (layout pode ter mudado)")

        search_state = (root.get("pinia") or {}).get("search") if isinstance(root, dict) else None
        if isinstance(search_state, dict) and search_state.get("trechoNaoEncontrado"):
            log.info("Buser: trecho %s -> %s não atendido", origin, destination)
            return []

        results = None
        if isinstance(search_state, dict):
            results = search_state.get("results")
        if not isinstance(results, dict) or "groups_by_date" not in results:
            results = _find_key(root, "groups_by_date")
        if not results:
            return []

        wanted = travel_date.isoformat()
        offers: list[Offer] = []
        for block in results.get("groups_by_date") or []:
            if not isinstance(block, dict) or block.get("datetime_ida") != wanted:
                continue
            for group in block.get("grupos") or []:
                offer = self._to_offer(group, origin, destination, url)
                if offer:
                    offers.append(offer)
        log.debug("Buser: %d ofertas para %s -> %s em %s", len(offers), origin, destination, wanted)
        return offers

    def _to_offer(self, g: dict, origin: str, destination: str, url: str) -> Offer | None:
        try:
            if g.get("closed") or g.get("grupo_classe_closed"):
                return None
            if g.get("trecho_alternativo"):
                # Ignora sugestões de outras cidades injetadas como trecho alternativo,
                # pois o roteador já avalia hubs e conexões locais explicitamente.
                return None
            price = g.get("max_split_value") or g.get("ref_split_value") or g.get("preco_base")
            if price is None:
                return None
            seats = g.get("vagas")
            seats = int(seats) if seats is not None else None
            if seats is not None and seats <= 0:
                return None

            depart_at = datetime.fromisoformat(g["datetime_ida"])
            arrive_at = datetime.fromisoformat(g["chegada_ida"])
            orig_place = g.get("origem") if isinstance(g.get("origem"), dict) else {}
            dest_place = g.get("destino") if isinstance(g.get("destino"), dict) else {}
            real_origin = str(
                g.get("cidade_origem_slug") or orig_place.get("slug") or origin
            ).strip()
            real_dest = str(
                g.get("cidade_destino_slug") or dest_place.get("slug") or destination
            ).strip()
            group_id = str(g.get("id") or "").strip() or None

            if group_id or real_origin != origin or real_dest != destination or not url:
                offer_url = self.booking_url(
                    real_origin, real_dest, depart_at.date(), group_id=group_id
                )
            else:
                offer_url = url

            is_buser_charter = g.get("modelo_venda") == "buser"
            return Offer(
                provider=self.name,
                origin=real_origin,
                destination=real_dest,
                depart_at=depart_at,
                arrive_at=arrive_at,
                price=round(float(price), 2),
                seats=seats,
                seats_capped=bool(is_buser_charter and seats is not None and seats >= SEAT_DISPLAY_CAP),
                seat_type=str(g.get("tipo_assento") or ""),
                company=str(g.get("company_friendly_name") or g.get("company_name") or "Buser"),
                boarding_point=_place_name(g.get("origem")),
                alighting_point=_place_name(g.get("destino")),
                url=offer_url,
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("Buser: grupo ignorado (%s)", exc)
            return None
