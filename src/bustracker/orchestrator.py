"""Orquestrador principal: sincroniza agendas, coleta ofertas, analisa preços e dispara alertas."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from .analyzer import evaluate
from .calendar_sync import import_calendar_file, load_ics_trips, load_json_trips
from .config import Settings, parse_hhmm
from .db import Storage
from .models import Itinerary, LegSpec, Level, Recommendation, Trip, TripSource
from .notifier import (
    booking_buttons,
    fmt_daily_summary,
    fmt_recommendation,
    should_alert,
)
from .providers import HttpSession, build_providers
from .routing import OfferSearch, build_itineraries
from .telegram.client import TelegramAuthError, TelegramClient, TelegramError
from .utils.text import resolve_city, today

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    results: list[tuple[Trip, Recommendation]] = field(default_factory=list)
    alerts_sent: int = 0
    errors: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage

    async def sync_sources(self) -> dict[str, tuple[int, int]]:
        """Sincroniza viagens do arquivo JSON local e do calendário iCal (.ics)."""
        summary: dict[str, tuple[int, int]] = {}
        try:
            json_trips = load_json_trips(self.settings)
            if json_trips is not None:
                summary["json"] = self.storage.sync_source(TripSource.JSON, json_trips)
        except Exception as exc:
            log.warning("Falha ao sincronizar JSON (%s): %s", self.settings.local_trips_file, exc)

        if self.settings.calendar_ics_url:
            try:
                ics_trips = await load_ics_trips(self.settings)
                if ics_trips is not None:
                    summary["ics"] = self.storage.sync_source(TripSource.ICS, ics_trips)
            except Exception as exc:
                log.warning("Falha ao sincronizar calendário iCal: %s", exc)
        return summary

    def import_calendar(
        self,
        file_path_or_content: str | Path | bytes,
        filename_hint: str = "",
    ) -> list[Trip]:
        """Importa viagens de arquivo (.ics / .json) e grava no SQLite WAL."""
        trips = import_calendar_file(file_path_or_content, self.settings, filename_hint=filename_hint)
        for t in trips:
            self.storage.upsert_trip(t)
        return trips

    async def check_all(
        self,
        *,
        notify: bool = True,
        force_summary: bool = False,
        session: HttpSession | None = None,
    ) -> RunReport:
        """Executa um ciclo completo de coleta, avaliação, persistência e alertas."""
        await self.sync_sources()
        cur_day = today(self.settings.timezone)
        report = RunReport()

        own_session = session is None
        http = session or HttpSession(
            delay_seconds=self.settings.request_delay_seconds,
            timeout=self.settings.request_timeout_seconds,
        )
        tg: TelegramClient | None = None
        if notify and self.settings.telegram_enabled:
            tg = TelegramClient(self.settings.telegram_bot_token)

        try:
            providers = build_providers(self.settings.enabled_providers, http)
            searcher = OfferSearch(providers, on_offers=self.storage.save_offers)

            for trip in self.storage.list_trips(active_only=True):
                for leg_name, leg_origin, leg_dest, spec in trip.legs():
                    days_left = (spec.date - cur_day).days
                    if days_left < 0 or days_left > self.settings.monitor_horizon_days:
                        continue

                    itineraries = await build_itineraries(
                        leg_origin,
                        leg_dest,
                        spec,
                        trip.hubs,
                        searcher.fetch,
                        self.settings,
                    )
                    history = self.storage.daily_min_prices(
                        trip.id, leg_name, self.settings.history_window_days
                    )
                    if itineraries:
                        best_today = itineraries[0].price
                        if not history or history[-1][0] != cur_day:
                            history = [*history, (cur_day, best_today)]
                        else:
                            history[-1] = (cur_day, min(history[-1][1], best_today))

                    rec = evaluate(
                        trip.id,
                        leg_name,
                        itineraries,
                        history,
                        spec.date,
                        cur_day,
                        self.settings,
                    )
                    self.storage.save_snapshot(
                        trip.id, leg_name, rec.best, len(itineraries), rec.level
                    )
                    report.results.append((trip, rec))

                    if tg is not None:
                        send, title, milestone = should_alert(self.settings, self.storage, rec)
                        if send:
                            text = fmt_recommendation(trip, rec, header=f"🚨 {title}")
                            try:
                                await tg.send_message(
                                    self.settings.telegram_chat_id,
                                    text,
                                    buttons=booking_buttons(rec),
                                )
                                self.storage.record_alert(
                                    trip.id, leg_name, rec.level, rec.price, milestone
                                )
                                report.alerts_sent += 1
                            except TelegramAuthError as exc:
                                log.warning("%s", exc)
                                report.errors.append(str(exc))
                                await tg.aclose()
                                tg = None
                            except TelegramError as exc:
                                log.error("Falha ao enviar alerta no Telegram: %s", exc)
                                report.errors.append(str(exc))

            report.errors.extend(searcher.errors)

            if tg is not None:
                last_sum = self.storage.kv_get("last_summary_date")
                should_send_sum = force_summary or (
                    self.settings.daily_summary and last_sum != cur_day.isoformat()
                )
                if should_send_sum:
                    header = (
                        "🔄 <b>Atualização de Preços das Viagens</b>"
                        if force_summary
                        else "📋 <b>Resumo Diário de Monitoramento</b>"
                    )
                    bought_map = {
                        (t.id, r.leg): bool(self.storage.kv_get(f"bought:{t.id}:{r.leg}"))
                        for t, r in report.results
                    }
                    try:
                        summary_text = fmt_daily_summary(
                            report.results,
                            report.errors,
                            bought_map=bought_map,
                            target_good=self.settings.target_price_good,
                            target_excellent=self.settings.target_price_excellent,
                            header=header,
                        )
                        await tg.send_message(self.settings.telegram_chat_id, summary_text)
                        self.storage.kv_set("last_summary_date", cur_day.isoformat())
                        report.alerts_sent += 1
                    except TelegramAuthError as exc:
                        log.warning("%s", exc)
                        report.errors.append(str(exc))
                    except TelegramError as exc:
                        log.error("Falha ao enviar resumo no Telegram: %s", exc)
                        report.errors.append(str(exc))
        finally:
            if tg is not None:
                await tg.aclose()
            if own_session:
                await http.aclose()

        return report

    async def search_ad_hoc(
        self,
        origin: str,
        destination: str,
        travel_date: date,
        *,
        hubs: list[str] | None = None,
        depart_after: str | None = None,
        depart_before: str | None = None,
        arrive_before: str | None = None,
        arrive_day_offset: int = 0,
        session: HttpSession | None = None,
    ) -> list[Itinerary]:
        """Executa uma busca pontual sob demanda (CLI ou comando `/buscar` do Telegram)."""
        spec = LegSpec(
            date=travel_date,
            depart_after=parse_hhmm(depart_after),
            depart_before=parse_hhmm(depart_before),
            arrive_before=parse_hhmm(arrive_before),
            arrive_day_offset=arrive_day_offset,
        )
        own_session = session is None
        http = session or HttpSession(
            delay_seconds=self.settings.request_delay_seconds,
            timeout=self.settings.request_timeout_seconds,
        )
        try:
            providers = build_providers(self.settings.enabled_providers, http)
            searcher = OfferSearch(providers, on_offers=self.storage.save_offers)
            return await build_itineraries(
                resolve_city(origin),
                resolve_city(destination),
                spec,
                [resolve_city(h) for h in (hubs if hubs is not None else self.settings.default_hubs) if h],
                searcher.fetch,
                self.settings,
            )
        finally:
            if own_session:
                await http.aclose()

    def latest_status(self) -> list[tuple[Trip, Recommendation]]:
        """Reconstrói o estado mais recente de cada trecho ativo a partir do banco SQLite."""
        cur_day = today(self.settings.timezone)
        out: list[tuple[Trip, Recommendation]] = []
        for trip in self.storage.list_trips(active_only=True):
            for leg_name, _, _, spec in trip.legs():
                days_left = (spec.date - cur_day).days
                if days_left < 0:
                    continue
                snap = self.storage.last_snapshot(trip.id, leg_name)
                best = (
                    Itinerary.from_dict(json.loads(snap["best_json"]))
                    if snap and snap["best_json"]
                    else None
                )
                history = self.storage.daily_min_prices(
                    trip.id, leg_name, self.settings.history_window_days
                )
                rec = evaluate(
                    trip.id,
                    leg_name,
                    [best] if best else [],
                    history,
                    spec.date,
                    cur_day,
                    self.settings,
                )
                if snap is None:
                    rec = Recommendation(
                        trip_id=trip.id,
                        leg=leg_name,
                        level=Level.NO_DATA,
                        reasons=["Aguardando primeira coleta (use /verificar ou --run-once)."],
                        days_left=days_left,
                        best=None,
                        alternatives=[],
                        stats=rec.stats,
                    )
                out.append((trip, rec))
        return out
