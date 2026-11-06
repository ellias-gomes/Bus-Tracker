"""Cliente mínimo da Telegram Bot API (HTTP puro via httpx, sem SDK pesado)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4000


class TelegramError(Exception):
    pass


class TelegramAuthError(TelegramError):
    """Token inválido, revogado ou não autorizado pelo Telegram (HTTP 401)."""


class TelegramClient:
    def __init__(self, token: str, timeout: float = 40.0):
        clean = (token or "").strip().strip("\"'").strip()
        if clean.lower().startswith("bot") and ":" in clean and clean[3:4].isdigit():
            clean = clean[3:]
        if not clean:
            raise TelegramError("TELEGRAM_BOT_TOKEN não configurado")
        self._token = clean
        self._client = httpx.AsyncClient(timeout=timeout)

    async def call(self, method: str, **params: Any) -> Any:
        url = API.format(token=self._token, method=method)
        try:
            resp = await self._client.post(url, json={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as exc:
            raise TelegramError(f"{method}: falha de rede ({exc.__class__.__name__})") from exc
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            desc = str(data.get("description") or resp.status_code)
            if resp.status_code == 401 or "unauthorized" in desc.lower():
                raise TelegramAuthError(
                    "Telegram: Token inválido ou revogado (401 Unauthorized). "
                    "Gere um novo token no @BotFather ou limpe TELEGRAM_BOT_TOKEN nas Configurações (.env)."
                )
            raise TelegramError(f"{method}: {desc}")
        return data["result"]

    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe")

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
    ) -> None:
        """Envia HTML; `buttons` = [(rótulo, url)] vira um teclado inline de links."""
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": label, "url": url}] for label, url in buttons if url]}
        for chunk in _split(text):
            await self.call(
                "sendMessage",
                chat_id=chat_id,
                text=chunk,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
            markup = None  # botões apenas no primeiro bloco

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        return await self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message"])

    async def set_commands(self, commands: list[tuple[str, str]]) -> None:
        await self.call(
            "setMyCommands",
            commands=[{"command": c, "description": d} for c, d in commands],
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _split(text: str) -> list[str]:
    if len(text) <= MAX_MESSAGE_LEN:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_MESSAGE_LEN:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    return chunks
