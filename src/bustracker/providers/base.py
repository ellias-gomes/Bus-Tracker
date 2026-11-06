"""Interface comum dos provedores de passagens e infraestrutura HTTP compartilhada."""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from datetime import date

import httpx

from ..models import Offer

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
}


class ProviderError(Exception):
    """Falha recuperável de um provedor (rede, bloqueio, layout alterado...)."""


class HttpSession:
    """Cliente HTTP assíncrono compartilhado, com intervalo mínimo entre requisições e retry."""

    def __init__(self, delay_seconds: float = 2.0, timeout: float = 25.0, retries: int = 2):
        self.delay = delay_seconds
        self.retries = retries
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True, http2=False
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def _throttle(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._last_request + self.delay - loop.time()
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, 0.5))
            self._last_request = loop.time()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._throttle()
            try:
                resp = await self._client.get(url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ProviderError(f"HTTP {resp.status_code} em {url}")
                return resp
            except (httpx.HTTPError, ProviderError) as exc:
                last_exc = exc
                backoff = 2 ** attempt * 3
                log.warning("Falha ao acessar %s (tentativa %d): %s", url, attempt + 1, exc)
                if attempt < self.retries:
                    await asyncio.sleep(backoff)
        raise ProviderError(str(last_exc))

    async def aclose(self) -> None:
        await self._client.aclose()


class BaseProvider(ABC):
    """Todo provedor recebe slugs de cidade no formato `cidade-uf` (ex.: `sao-paulo-sp`)."""

    name: str = "base"
    #: Provedores experimentais não são usados a menos que habilitados explicitamente.
    experimental: bool = False

    def __init__(self, session: HttpSession):
        self.session = session

    @abstractmethod
    async def search(self, origin: str, destination: str, travel_date: date) -> list[Offer]:
        """Retorna as ofertas de `origin` para `destination` partindo em `travel_date`."""

    def booking_url(self, origin: str, destination: str, travel_date: date) -> str:
        return ""
