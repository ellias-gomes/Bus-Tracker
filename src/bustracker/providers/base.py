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
    """Cliente HTTP assíncrono compartilhado, com intervalo mínimo entre requisições por host e retry."""

    def __init__(self, delay_seconds: float = 2.0, timeout: float = 25.0, retries: int = 2):
        self.delay = delay_seconds
        self.retries = retries
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True, http2=False
        )
        self._lock = asyncio.Lock()
        self._last_request_by_host: dict[str, float] = {}

    async def _throttle(self, url: str) -> None:
        try:
            host = httpx.URL(url).host
        except Exception:
            host = "default"
        async with self._lock:
            loop = asyncio.get_running_loop()
            last = self._last_request_by_host.get(host, 0.0)
            wait = last + self.delay - loop.time()
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, 0.2))
            self._last_request_by_host[host] = loop.time()

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._throttle(url)
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise ProviderError(f"HTTP {resp.status_code} em {url}")
                return resp
            except (httpx.HTTPError, ProviderError) as exc:
                last_exc = exc
                backoff = 2 ** attempt * 3
                if attempt < self.retries:
                    log.debug("Falha temporária ao acessar %s (tentativa %d): %s", url, attempt + 1, exc)
                    if "429" in str(exc):
                        try:
                            host = httpx.URL(url).host
                            async with self._lock:
                                self._last_request_by_host[host] = (
                                    self._last_request_by_host.get(host, asyncio.get_running_loop().time()) + 4.0
                                )
                        except Exception:
                            pass
                    await asyncio.sleep(backoff)
                else:
                    log.warning("Falha ao acessar %s após %d tentativas: %s", url, self.retries + 1, exc)
        raise ProviderError(str(last_exc))

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

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
