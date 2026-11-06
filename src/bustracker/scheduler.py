"""Agendador leve em asyncio para modo daemon (Linux e Termux)."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta

from .config import Settings, parse_hhmm
from .orchestrator import Orchestrator
from .telegram.bot import TelegramBotHandler
from .utils.text import now

log = logging.getLogger(__name__)


def next_scheduled_run(current: datetime, run_times: list[str], interval_hours: float = 0.0) -> datetime:
    """Calcula o próximo instante de execução a partir de horários fixos (HH:MM) e/ou intervalo."""
    candidates: list[datetime] = []
    for raw in run_times:
        t = parse_hhmm(raw)
        if t is None:
            continue
        target = current.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if target <= current:
            target += timedelta(days=1)
        candidates.append(target)

    if interval_hours > 0:
        candidates.append(current + timedelta(hours=interval_hours))

    if not candidates:
        return current + timedelta(hours=12)
    return min(candidates)


async def _scheduler_loop(
    settings: Settings,
    orchestrator: Orchestrator,
    stop_event: asyncio.Event,
) -> None:
    cur = now(settings.timezone)
    last_check = orchestrator.storage.kv_get("last_check_date")
    if last_check != cur.date().isoformat():
        log.info("Executando verificação inicial na partida do daemon...")
        try:
            await orchestrator.check_all(notify=True)
            orchestrator.storage.kv_set("last_check_date", cur.date().isoformat())
        except Exception:
            log.exception("Erro na verificação inicial")

    while not stop_event.is_set():
        cur = now(settings.timezone)
        nxt = next_scheduled_run(cur, settings.daily_run_times, settings.check_interval_hours)
        wait_seconds = max(1.0, (nxt - cur).total_seconds())
        log.info("Próxima coleta automática agendada para %s (em %.0f min)", nxt.strftime("%d/%m %H:%M"), wait_seconds / 60)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
            break
        except asyncio.TimeoutError:
            pass

        log.info("Iniciando coleta agendada...")
        try:
            report = await orchestrator.check_all(notify=True)
            orchestrator.storage.kv_set("last_check_date", now(settings.timezone).date().isoformat())
            log.info(
                "Coleta concluída: %d trecho(s) avaliado(s), %d alerta(s) enviado(s)",
                len(report.results),
                report.alerts_sent,
            )
        except Exception:
            log.exception("Falha durante a coleta agendada")


async def run_daemon(settings: Settings, orchestrator: Orchestrator) -> None:
    """Inicia o agendador periódico e, se configurado, o bot interativo do Telegram em paralelo."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    tasks = [asyncio.create_task(_scheduler_loop(settings, orchestrator, stop_event))]
    if settings.telegram_bot_token:
        bot = TelegramBotHandler(settings, orchestrator)
        tasks.append(asyncio.create_task(bot.poll_forever(stop_event)))
    else:
        log.info("TELEGRAM_BOT_TOKEN não configurado; rodando apenas agendador local.")

    await stop_event.wait()
    log.info("Encerrando daemon...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
