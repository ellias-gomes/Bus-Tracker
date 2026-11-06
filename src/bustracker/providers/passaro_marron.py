"""Provedor Pássaro Marron (EXPERIMENTAL / ainda não implementado).

Situação verificada em 11/2026:
- O site (`passaromarron.com.br/portal-de-passagens/...`) é uma SPA React servida pela plataforma
  de vendas DEX (domínios `app.passaromarron.com.br` / `prodvendasdex.passaromarron.com.br`).
- As consultas de horários/preços são feitas via chamadas internas do app, ainda não mapeadas aqui.
  O antigo `portaldepassagens.com.br/VendaWebPassaroMarron` responde 503.

Próximo passo: mapear o endpoint de busca da plataforma DEX (inspecionando o tráfego do navegador
numa busca normal) e implementar `search()` com uma chamada HTTP direta, como no provedor Buser.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from ..models import Offer
from .base import BaseProvider, ProviderError


class PassaroMarronProvider(BaseProvider):
    name = "passaromarron"
    experimental = True

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return (
            "https://www.passaromarron.com.br/portal-de-passagens/lista"
            f"?origem={quote_plus(origin)}&destino={quote_plus(destination)}"
        )

    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        raise ProviderError("Pássaro Marron: conector ainda não implementado (ver docstring do módulo)")
