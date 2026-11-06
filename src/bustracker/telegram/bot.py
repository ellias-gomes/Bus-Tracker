"""Bot interativo do Telegram via long-polling (getUpdates)."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import date
from typing import TYPE_CHECKING

from ..calendar_sync import trip_from_dates, trip_from_event
from ..config import Settings
from ..models import Trip, TripSource
from ..notifier import (
    booking_buttons,
    fmt_daily_summary,
    fmt_history,
    fmt_itinerary,
    fmt_recommendation,
    fmt_trip_summary,
)
from ..utils.text import city_label, fmt_date, parse_date, resolve_city
from .client import TelegramAuthError, TelegramClient, TelegramError

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

log = logging.getLogger(__name__)

BOT_COMMANDS = [
    ("status", "Próxima viagem e menor preço atual"),
    ("viagens", "Lista todas as viagens monitoradas"),
    ("adicionar", "Cadastra viagem: /adicionar IDA [VOLTA] [DESTINO]"),
    ("evento", "Cadastra pelo dia do compromisso: /evento DATA [NOME]"),
    ("importar", "Importa calendário de arquivo local: /importar ARQUIVO"),
    ("historico", "Gráfico de preços: /historico [ID] [ida|volta]"),
    ("buscar", "Busca avulsa: /buscar ORIGEM DESTINO DATA"),
    ("verificar", "Dispara coleta imediata de preços"),
    ("comprei", "Silencia alertas: /comprei ID [ida|volta]"),
    ("remover", "Remove viagem: /remover ID"),
    ("ajuda", "Exibe instruções detalhadas"),
]

HELP_TEXT = """<b>🚌 BusTracker — Comandos Disponíveis</b>

• /status — Resumo geral e detalhes da próxima viagem
• /viagens (ou /listar) — Lista as viagens ativas
• /adicionar <code>AAAA-MM-DD [AAAA-MM-DD] [destino-uf]</code>
  <i>Ex.:</i> <code>/adicionar 2026-11-23 2026-11-24</code>
  <i>Também aceita:</i> /nova_viagem
• /evento <code>AAAA-MM-DD [nome]</code>
  Cria ida/volta aplicando os deslocamentos padrão do <code>.env</code>
• /importar <code>caminho/arquivo.ics</code> — Importa arquivo local (.ics ou .json)
• /historico <code>[id] [ida|volta]</code> — Histórico dos últimos 14 dias
• /buscar <code>origem-uf destino-uf AAAA-MM-DD</code>
  <i>Ex.:</i> <code>/buscar rio-de-janeiro-rj sao-paulo-sp 2026-11-23</code>
• /verificar — Atualiza preços agora
• /comprei <code>id [ida|volta]</code> — Marca trecho como comprado
• /remover <code>id</code> — Desativa uma viagem"""


def _looks_like_date(token: str) -> bool:
    try:
        parse_date(token)
        return True
    except ValueError:
        return False


class TelegramBotHandler:
    def __init__(self, settings: Settings, orchestrator: Orchestrator, client: TelegramClient | None = None):
        self.settings = settings
        self.orchestrator = orchestrator
        self.storage = orchestrator.storage
        self.client = client

    async def handle_command(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Processa um comando de texto e retorna `(resposta_html, botoes)`."""
        parts = text.strip().split()
        if not parts:
            return HELP_TEXT, []
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]

        try:
            if cmd in ("/start", "/ajuda", "/help"):
                return HELP_TEXT, []
            if cmd == "/status":
                return self._cmd_status()
            if cmd in ("/viagens", "/listar"):
                return self._cmd_list(), []
            if cmd in ("/adicionar", "/nova_viagem"):
                return self._cmd_add(args), []
            if cmd == "/evento":
                return self._cmd_event(args), []
            if cmd == "/importar":
                return self._cmd_import(args), []
            if cmd == "/remover":
                return self._cmd_remove(args), []
            if cmd == "/comprei":
                return self._cmd_bought(args), []
            if cmd == "/historico":
                return self._cmd_history(args), []
            if cmd == "/buscar":
                return await self._cmd_search(args), []
            if cmd == "/verificar":
                return await self._cmd_check_now()
            return f"Comando não reconhecido: <code>{html.escape(cmd)}</code>\n\n{HELP_TEXT}", []
        except ValueError as exc:
            return f"⚠️ {html.escape(str(exc))}", []
        except Exception as exc:
            log.exception("Erro ao executar comando %s", cmd)
            return f"❌ Erro ao processar comando: <code>{html.escape(str(exc))}</code>", []

    def _cmd_status(self) -> tuple[str, list[tuple[str, str]]]:
        statuses = self.orchestrator.latest_status()
        if not statuses:
            return "Nenhuma viagem futura ativa. Use /adicionar ou /evento para cadastrar.", []
        bought_map = {
            (t.id, r.leg): bool(self.storage.kv_get(f"bought:{t.id}:{r.leg}"))
            for t, r in statuses
        }
        summary = fmt_daily_summary(
            statuses,
            bought_map=bought_map,
            target_good=self.settings.target_price_good,
            target_excellent=self.settings.target_price_excellent,
        )
        first_trip, first_rec = statuses[0]
        detail = fmt_recommendation(first_trip, first_rec, header="🔎 Próximo trecho:")
        return f"{summary}\n\n{detail}", booking_buttons(first_rec)

    def _cmd_list(self) -> str:
        trips = self.storage.list_trips(active_only=True)
        if not trips:
            return "Nenhuma viagem ativa no momento."
        blocks = ["<b>🗂️ Viagens Monitoradas</b>\n"]
        blocks.extend(fmt_trip_summary(t) for t in trips)
        return "\n\n".join(blocks)

    def _cmd_add(self, args: list[str]) -> str:
        if not args:
            raise ValueError("Uso: /adicionar AAAA-MM-DD [AAAA-MM-DD] [destino-uf] [nome...]")
        outbound_date: date = parse_date(args[0])
        return_date: date | None = None
        rest = args[1:]
        if rest and _looks_like_date(rest[0]):
            return_date = parse_date(rest[0])
            rest = rest[1:]

        destination: str | None = None
        if rest and "-" in rest[0] and len(rest[0].split("-")[-1]) == 2:
            destination = resolve_city(rest[0])
            rest = rest[1:]

        trip_id = Trip.new_id("tg")
        name = " ".join(rest).strip() or f"Viagem {outbound_date.strftime('%d/%m')}"
        trip = trip_from_dates(
            self.settings,
            outbound_date,
            return_date,
            trip_id=trip_id,
            name=name,
            source=TripSource.MANUAL,
            destination=destination,
        )
        self.storage.upsert_trip(trip)
        return f"✅ Viagem cadastrada com sucesso!\n\n{fmt_trip_summary(trip)}"

    def _cmd_event(self, args: list[str]) -> str:
        if not args:
            raise ValueError("Uso: /evento AAAA-MM-DD [nome do compromisso]")
        ev_date = parse_date(args[0])
        name = " ".join(args[1:]).strip() or f"Compromisso {ev_date.strftime('%d/%m')}"
        trip = trip_from_event(
            self.settings,
            ev_date,
            trip_id=Trip.new_id("ev"),
            name=name,
            source=TripSource.MANUAL,
        )
        self.storage.upsert_trip(trip)
        return f"✅ Compromisso agendado!\n\n{fmt_trip_summary(trip)}"

    def _cmd_import(self, args: list[str]) -> str:
        if not args:
            raise ValueError("Uso: /importar <caminho/arquivo.ics ou .json>")
        from pathlib import Path
        file_path = Path(" ".join(args).strip()).expanduser()
        if not file_path.exists() or not file_path.is_file():
            raise ValueError(f"Arquivo '{file_path}' não encontrado no disco do servidor.")
        imported = self.orchestrator.import_calendar(file_path)
        if not imported:
            return f"Nenhum evento importado de <code>{html.escape(file_path.name)}</code>. Verifique as palavras-chave configuradas."
        blocks = [f"✅ <b>{len(imported)} viagem(ns) importada(s) de {html.escape(file_path.name)}:</b>\n"]
        blocks.extend(fmt_trip_summary(t) for t in imported)
        return "\n\n".join(blocks)

    def _cmd_remove(self, args: list[str]) -> str:
        if not args:
            raise ValueError("Uso: /remover <id>")
        trip_id = args[0].strip()
        if not self.storage.deactivate_trip(trip_id):
            raise ValueError(f"Viagem '{trip_id}' não encontrada.")
        return f"🗑️ Viagem <code>{html.escape(trip_id)}</code> desativada."

    def _cmd_bought(self, args: list[str]) -> str:
        if not args:
            raise ValueError("Uso: /comprei <id> [ida|volta]")
        trip_id = args[0].strip()
        trip = self.storage.get_trip(trip_id)
        if not trip:
            raise ValueError(f"Viagem '{trip_id}' não encontrada.")
        legs = [args[1].lower()] if len(args) > 1 else ["ida", "volta"]
        for leg in legs:
            if leg not in ("ida", "volta"):
                raise ValueError("Trecho deve ser 'ida' ou 'volta'.")
            self.storage.kv_set(f"bought:{trip_id}:{leg}", "1")
        return f"✅ Alertas silenciados para <code>{html.escape(trip_id)}</code> ({', '.join(legs)})."

    def _cmd_history(self, args: list[str]) -> str:
        trips = self.storage.list_trips(active_only=True)
        if not trips:
            return "Nenhuma viagem ativa."
        trip = trips[0]
        leg = "ida"
        if args:
            if args[0].lower() in ("ida", "volta"):
                leg = args[0].lower()
            else:
                found = self.storage.get_trip(args[0])
                if not found:
                    raise ValueError(f"Viagem '{args[0]}' não encontrada.")
                trip = found
                if len(args) > 1 and args[1].lower() in ("ida", "volta"):
                    leg = args[1].lower()
        history = self.storage.daily_min_prices(trip.id, leg, self.settings.history_window_days)
        return fmt_history(trip, leg, history, self.settings.timezone)

    async def _cmd_search(self, args: list[str]) -> str:
        if len(args) < 3:
            raise ValueError("Uso: /buscar <origem-uf> <destino-uf> <AAAA-MM-DD>")
        origin, dest, dt = resolve_city(args[0]), resolve_city(args[1]), parse_date(args[2])
        itineraries = await self.orchestrator.search_ad_hoc(origin, dest, dt)
        header = f"🔎 <b>{html.escape(city_label(origin))} → {html.escape(city_label(dest))}</b> ({fmt_date(dt)})"
        if not itineraries:
            return f"{header}\nNenhuma opção encontrada."
        lines = [header, ""]
        for it in itineraries[:6]:
            lines.append(fmt_itinerary(it, detailed=True))
            lines.append("")
        return "\n".join(lines).strip()

    async def _cmd_check_now(self) -> tuple[str, list[tuple[str, str]]]:
        report = await self.orchestrator.check_all(notify=False)
        text = fmt_daily_summary(report.results, report.errors)
        if report.results:
            trip, rec = report.results[0]
            return f"{text}\n\n{fmt_recommendation(trip, rec)}", booking_buttons(rec)
        return text, []

    async def poll_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """Loop de long-polling do Telegram."""
        own_client = self.client is None
        tg = self.client or TelegramClient(self.settings.telegram_bot_token)
        try:
            try:
                await tg.set_commands(BOT_COMMANDS)
            except TelegramError as exc:
                log.warning("Não foi possível registrar comandos do bot: %s", exc)

            raw_offset = self.storage.kv_get("telegram_update_offset")
            offset: int | None = int(raw_offset) if raw_offset else None
            log.info("Telegram Bot aguardando comandos (offset=%s)...", offset)

            while not (stop_event and stop_event.is_set()):
                try:
                    updates = await tg.get_updates(offset=offset, timeout=25)
                except TelegramAuthError as exc:
                    log.warning("%s — encerrando polling do Telegram.", exc)
                    break
                except TelegramError as exc:
                    log.warning("Polling Telegram falhou: %s", exc)
                    await asyncio.sleep(5)
                    continue

                for upd in updates:
                    offset = int(upd["update_id"]) + 1
                    self.storage.kv_set("telegram_update_offset", str(offset))
                    msg = upd.get("message") or {}
                    chat_id = str((msg.get("chat") or {}).get("id") or "")
                    text = (msg.get("text") or "").strip()
                    if not text or not chat_id:
                        continue
                    if self.settings.telegram_chat_id and chat_id != str(self.settings.telegram_chat_id):
                        log.warning("Mensagem ignorada de chat_id não autorizado: %s", chat_id)
                        continue
                    if text.startswith("/"):
                        reply, buttons = await self.handle_command(text)
                        await tg.send_message(chat_id, reply, buttons=buttons)
        finally:
            if own_client:
                await tg.aclose()
