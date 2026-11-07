"""Registro e fábrica de provedores."""

from __future__ import annotations

import logging

from .aguia_branca import AguiaBrancaProvider
from .base import BaseProvider, HttpSession, ProviderError
from .buser import BuserProvider
from .clickbus import ClickBusProvider
from .cometa import CometaProvider
from .guanabara import GuanabaraProvider
from .passaro_marron import PassaroMarronProvider

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[BaseProvider]] = {
    BuserProvider.name: BuserProvider,
    GuanabaraProvider.name: GuanabaraProvider,
    CometaProvider.name: CometaProvider,
    AguiaBrancaProvider.name: AguiaBrancaProvider,
    ClickBusProvider.name: ClickBusProvider,
    PassaroMarronProvider.name: PassaroMarronProvider,
}


def build_providers(names: list[str], session: HttpSession) -> list[BaseProvider]:
    providers: list[BaseProvider] = []
    for name in names:
        cls = REGISTRY.get(name)
        if not cls:
            log.warning("Provedor desconhecido ignorado: %s (disponíveis: %s)", name, ", ".join(REGISTRY))
            continue
        if cls.experimental:
            log.warning("Provedor %s é EXPERIMENTAL e pode não retornar resultados.", name)
        providers.append(cls(session))
    return providers


__all__ = ["BaseProvider", "HttpSession", "ProviderError", "REGISTRY", "build_providers"]
