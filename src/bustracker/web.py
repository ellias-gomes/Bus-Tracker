"""Servidor HTTP assíncrono ultra-leve para o Ambiente Gráfico (Web UI) do BusTracker."""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analyzer import compute_stats
from .calendar_sync import trip_from_dates, trip_from_event
from .config import Settings
from .env_editor import editable_settings_dict, update_env_values
from .models import Itinerary, Recommendation, Trip, TripSource
from .notifier import export_csv_report, fmt_seats
from .orchestrator import Orchestrator
from .telegram.client import TelegramClient
from .utils.text import (
    CITY_CATALOG,
    city_label,
    fmt_date,
    parse_date,
    resolve_city,
    resolve_city_list,
    search_cities,
    today,
)

log = logging.getLogger(__name__)

UI_HTML_PATH = Path(__file__).resolve().parent / "web_ui.html"


def _serialize_itinerary(it: Itinerary | None) -> dict[str, Any] | None:
    if it is None:
        return None
    main = it.main_segment
    return {
        "price": it.price,
        "depart_at": it.depart_at.strftime("%d/%m %H:%M"),
        "depart_time": it.depart_at.strftime("%H:%M"),
        "arrive_at": it.arrive_at.strftime("%d/%m %H:%M"),
        "arrive_time": it.arrive_at.strftime("%H:%M"),
        "transfers": it.transfers,
        "seats": it.seats,
        "seats_display": fmt_seats(it),
        "provider": main.provider,
        "company": main.company,
        "seat_type": main.seat_type,
        "boarding_point": main.boarding_point,
        "alighting_point": main.alighting_point,
        "url": main.url,
        "segments": [
            {
                "provider": s.provider,
                "origin": s.origin,
                "destination": s.destination,
                "origin_label": city_label(s.origin),
                "dest_label": city_label(s.destination),
                "origin_short": city_label(s.origin).split(" - ")[0],
                "dest_short": city_label(s.destination).split(" - ")[0],
                "depart_at": s.depart_at.strftime("%d/%m %H:%M"),
                "depart_time": s.depart_at.strftime("%H:%M"),
                "arrive_at": s.arrive_at.strftime("%d/%m %H:%M"),
                "arrive_time": s.arrive_at.strftime("%H:%M"),
                "price": s.price,
                "company": s.company,
                "seat_type": s.seat_type,
                "boarding_point": s.boarding_point,
                "alighting_point": s.alighting_point,
                "is_estimate": s.is_estimate,
                "url": s.url,
            }
            for s in it.segments
        ],
    }


def _serialize_rec(trip: Trip, rec: Recommendation, bought: bool) -> dict[str, Any]:
    leg_origin, leg_dest = (
        (trip.origin, trip.destination) if rec.leg == "ida" else (trip.destination, trip.origin)
    )
    spec = trip.outbound if rec.leg == "ida" else trip.return_leg
    return {
        "trip_id": trip.id,
        "trip_name": trip.name,
        "leg": rec.leg,
        "origin": leg_origin,
        "origin_label": city_label(leg_origin),
        "destination": leg_dest,
        "dest_label": city_label(leg_dest),
        "date": spec.date.isoformat() if spec else "",
        "date_formatted": fmt_date(spec.date) if spec else "",
        "window_desc": spec.describe() if spec else "",
        "days_left": rec.days_left,
        "level": rec.level.value,
        "level_label": rec.level.label,
        "reasons": rec.reasons,
        "price": rec.price,
        "best": _serialize_itinerary(rec.best),
        "alternatives": [_serialize_itinerary(a) for a in rec.alternatives],
        "stats": {
            "samples": rec.stats.samples,
            "mean": rec.stats.mean,
            "minimum": rec.stats.minimum,
            "maximum": rec.stats.maximum,
            "price_7d_ago": rec.stats.price_7d_ago,
        },
        "bought": bought,
    }


class WebApp:
    def __init__(self, settings: Settings, orchestrator: Orchestrator, env_path: Path | None = None):
        self.settings = settings
        self.orchestrator = orchestrator
        self.storage = orchestrator.storage
        self.env_path = env_path

    def build_state(self) -> dict[str, Any]:
        statuses = self.orchestrator.latest_status()

        # Agrupar recomendações por viagem para combos e totais
        recs_by_trip: dict[str, list[tuple[Recommendation, bool]]] = {}
        recs_out = []
        total_geral = 0.0
        total_restante = 0.0
        tem_preco = False

        for trip, rec in statuses:
            bought = bool(self.storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
            recs_out.append(_serialize_rec(trip, rec, bought))
            recs_by_trip.setdefault(trip.id, []).append((rec, bought))
            if rec.price is not None:
                tem_preco = True
                total_geral += rec.price
                if not bought:
                    total_restante += rec.price

        trips_out = []
        for t in self.storage.list_trips(active_only=True):
            d = t.to_dict()
            d["origin_label"] = city_label(t.origin)
            d["destination_label"] = city_label(t.destination)
            d["hubs_label"] = [city_label(h) for h in t.hubs]
            d["bought_ida"] = bool(self.storage.kv_get(f"bought:{t.id}:ida"))
            d["bought_volta"] = bool(self.storage.kv_get(f"bought:{t.id}:volta"))

            trip_recs = recs_by_trip.get(t.id, [])
            expected_legs = 2 if (t.outbound and t.return_leg) else 1
            if trip_recs:
                combo_price = 0.0
                combo_remaining = 0.0
                priced_legs = 0
                bought_count = 0
                for rec, bought in trip_recs:
                    if bought:
                        bought_count += 1
                    if rec.price is not None:
                        combo_price += rec.price
                        priced_legs += 1
                        if not bought:
                            combo_remaining += rec.price
                d["combo"] = {
                    "has_combo": expected_legs >= 2,
                    "legs_count": len(trip_recs),
                    "expected_legs": expected_legs,
                    "all_priced": priced_legs == expected_legs,
                    "combo_price": combo_price if priced_legs > 0 else None,
                    "combo_remaining": combo_remaining,
                    "bought_count": bought_count,
                    "is_fully_bought": bought_count >= expected_legs,
                    "target_good": self.settings.target_price_good * expected_legs,
                    "target_excellent": self.settings.target_price_excellent * expected_legs,
                }
            else:
                d["combo"] = None

            trips_out.append(d)

        return {
            "settings": editable_settings_dict(self.settings),
            "telegram_enabled": self.settings.telegram_enabled,
            "target_price_good": self.settings.target_price_good,
            "target_price_excellent": self.settings.target_price_excellent,
            "event_outbound_day_offset": self.settings.event_outbound_day_offset,
            "event_return_day_offset": self.settings.event_return_day_offset,
            "cities": [{"slug": s, "name": n} for s, n in CITY_CATALOG],
            "trips": trips_out,
            "recommendations": recs_out,
            "total_geral": round(total_geral, 2) if tem_preco else None,
            "total_restante": round(total_restante, 2) if tem_preco else None,
        }

    async def dispatch(
        self, method: str, path: str, query: dict[str, list[str]], body: bytes
    ) -> tuple[int, str, bytes] | tuple[int, str, bytes, dict[str, str]]:
        if method == "GET" and path in ("/", "/index.html"):
            html_bytes = UI_HTML_PATH.read_bytes()
            return HTTPStatus.OK, "text/html; charset=utf-8", html_bytes

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
            if method == "GET" and path == "/api/state":
                await self.orchestrator.sync_sources()
                return self._json(self.build_state())

            if method == "GET" and path == "/api/export/csv":
                await self.orchestrator.sync_sources()
                statuses = self.orchestrator.latest_status()
                bought_map = {
                    (trip.id, rec.leg): bool(self.storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
                    for trip, rec in statuses
                }
                csv_text = export_csv_report(
                    statuses,
                    bought_map=bought_map,
                    target_good=self.settings.target_price_good,
                    target_excellent=self.settings.target_price_excellent,
                )
                csv_bytes = ("\ufeff" + csv_text).encode("utf-8")
                return (
                    int(HTTPStatus.OK),
                    "text/csv; charset=utf-8",
                    csv_bytes,
                    {"Content-Disposition": 'attachment; filename="relatorio_bustracker.csv"'},
                )

            if method == "GET" and path == "/api/cities":
                q = (query.get("q") or [""])[0]
                return self._json({"cities": search_cities(q, limit=12)})

            if method == "POST" and path == "/api/check":
                report = await self.orchestrator.check_all(notify=True, force_summary=True)
                state = self.build_state()
                state["alerts_sent"] = report.alerts_sent
                state["errors"] = report.errors
                return self._json(state)

            if method == "POST" and path == "/api/search":
                origin = resolve_city(
                    payload.get("origin") or self.settings.default_origin or "rio-de-janeiro-rj"
                )
                dest = resolve_city(
                    payload.get("destination") or self.settings.default_destination or "cacapava-sp"
                )
                dt_str = str(payload.get("date") or "").strip()
                dt: date = parse_date(dt_str) if dt_str else today(self.settings.timezone)
                hubs_raw = payload.get("hubs")
                if hubs_raw is None or hubs_raw == "":
                    hubs = list(self.settings.default_hubs)
                else:
                    hubs = resolve_city_list(hubs_raw)

                its = await self.orchestrator.search_ad_hoc(
                    origin,
                    dest,
                    dt,
                    hubs=hubs,
                    depart_after=payload.get("depart_after") or None,
                    depart_before=payload.get("depart_before") or None,
                    arrive_before=payload.get("arrive_before") or None,
                    arrive_day_offset=int(payload.get("arrive_day_offset") or 0),
                )
                return self._json(
                    {
                        "origin": origin,
                        "destination": dest,
                        "origin_label": city_label(origin),
                        "dest_label": city_label(dest),
                        "date_formatted": fmt_date(dt),
                        "count": len(its),
                        "itineraries": [_serialize_itinerary(it) for it in its[:25]],
                    }
                )

            if method == "POST" and path == "/api/trips/add":
                dt_out = parse_date(str(payload["outbound_date"]))
                ret_raw = str(payload.get("return_date") or "").strip()
                dt_ret = parse_date(ret_raw) if ret_raw else None
                hubs_raw = str(payload.get("hubs") or "").strip()
                hubs = resolve_city_list(hubs_raw) if hubs_raw else None
                orig = resolve_city(payload.get("origin") or self.settings.default_origin or "rio-de-janeiro-rj")
                dest = resolve_city(payload.get("destination") or self.settings.default_destination or "cacapava-sp")
                trip = trip_from_dates(
                    self.settings,
                    dt_out,
                    dt_ret,
                    trip_id=Trip.new_id("web"),
                    name=str(payload.get("name") or f"Viagem {dt_out.strftime('%d/%m')}").strip(),
                    source=TripSource.MANUAL,
                    origin=orig,
                    destination=dest,
                    hubs=hubs,
                    outbound_depart_after=payload.get("outbound_depart_after") or None,
                    outbound_depart_before=payload.get("outbound_depart_before") or None,
                    return_depart_after=payload.get("return_depart_after") or None,
                    return_arrive_before=payload.get("return_arrive_before") or None,
                )
                self.storage.upsert_trip(trip)
                return self._json({"ok": True, "state": self.build_state()})

            if method == "POST" and path == "/api/trips/event":
                ev_date = parse_date(str(payload["event_date"]))
                orig = resolve_city(payload.get("origin") or self.settings.default_origin or "rio-de-janeiro-rj")
                dest = resolve_city(payload.get("destination") or self.settings.default_destination or "cacapava-sp")
                trip = trip_from_event(
                    self.settings,
                    ev_date,
                    trip_id=Trip.new_id("ev"),
                    name=str(payload.get("name") or f"Compromisso {ev_date.strftime('%d/%m')}").strip(),
                    source=TripSource.MANUAL,
                    origin=orig,
                    destination=dest,
                    one_way=bool(payload.get("one_way")),
                )
                self.storage.upsert_trip(trip)
                return self._json({"ok": True, "state": self.build_state()})

            if method == "POST" and path == "/api/trips/delete":
                trip_id = str(payload.get("trip_id") or "")
                self.storage.deactivate_trip(trip_id)
                return self._json({"ok": True, "state": self.build_state()})

            if method == "POST" and path == "/api/trips/bought":
                trip_id = str(payload.get("trip_id") or "")
                leg = str(payload.get("leg") or "ida")
                bought = bool(payload.get("bought", True))
                self.storage.kv_set(f"bought:{trip_id}:{leg}", "1" if bought else "")
                return self._json({"ok": True, "state": self.build_state()})

            if method == "GET" and path == "/api/history":
                trips = self.storage.list_trips(active_only=True)
                trip_id = (query.get("trip_id") or [""])[0]
                leg = (query.get("leg") or ["ida"])[0]
                trip = self.storage.get_trip(trip_id) if trip_id else (trips[0] if trips else None)
                if not trip:
                    return self._json({"points": [], "stats": {}})
                hist = self.storage.daily_min_prices(trip.id, leg, self.settings.history_window_days)
                st = compute_stats(hist, today(self.settings.timezone))
                return self._json(
                    {
                        "trip_id": trip.id,
                        "trip_name": trip.name,
                        "leg": leg,
                        "target_good": self.settings.target_price_good,
                        "target_excellent": self.settings.target_price_excellent,
                        "stats": {
                            "samples": st.samples,
                            "mean": st.mean,
                            "minimum": st.minimum,
                            "maximum": st.maximum,
                        },
                        "points": [
                            {"date": d.isoformat(), "label": d.strftime("%d/%m"), "price": p}
                            for d, p in hist
                        ],
                    }
                )

            if method == "POST" and path == "/api/settings":
                updates = {str(k): str(v) for k, v in (payload.get("updates") or {}).items()}
                self.settings = update_env_values(updates, self.env_path)
                self.orchestrator.settings = self.settings
                synced = await self.orchestrator.sync_sources()
                return self._json({"ok": True, "synced": synced, "state": self.build_state()})

            if method == "POST" and path == "/api/telegram/test":
                token = str(payload.get("token") or self.settings.telegram_bot_token).strip()
                chat_id = str(payload.get("chat_id") or self.settings.telegram_chat_id).strip()
                if not token:
                    raise ValueError("Informe o TELEGRAM_BOT_TOKEN antes de testar.")
                tg = TelegramClient(token, timeout=15.0)
                try:
                    me = await tg.get_me()
                    sent = False
                    if chat_id:
                        await tg.send_message(
                            chat_id,
                            "✅ <b>BusTracker:</b> Conexão com o Telegram testada e funcionando!",
                        )
                        sent = True
                    return self._json(
                        {
                            "ok": True,
                            "bot_username": me.get("username") or me.get("first_name") or "Bot",
                            "sent": sent,
                        }
                    )
                finally:
                    await tg.aclose()

            if method == "POST" and path == "/api/sync":
                synced = await self.orchestrator.sync_sources()
                return self._json({"ok": True, "synced": synced, "state": self.build_state()})

            if method == "POST" and path == "/api/calendar/import":
                # Aceita JSON: {"content": "...", "filename": "calendario.ics"} ou {"path": "/caminho/arquivo.ics"}
                filename = str(payload.get("filename") or "calendario.ics")
                file_content = payload.get("content")
                file_path = payload.get("path")
                
                if file_path:
                    p = Path(file_path).expanduser()
                    if not p.exists():
                        raise ValueError(f"Arquivo '{file_path}' não encontrado no disco.")
                    trips = self.orchestrator.import_calendar(p, filename_hint=p.name)
                elif file_content is not None:
                    trips = self.orchestrator.import_calendar(file_content.encode("utf-8"), filename_hint=filename)
                else:
                    raise ValueError("Informe o conteúdo do arquivo ('content') ou o caminho local ('path').")

                return self._json({
                    "ok": True,
                    "count": len(trips),
                    "trips": [t.name for t in trips],
                    "state": self.build_state(),
                })

            return self._json({"error": f"Rota não encontrada: {path}"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            log.exception("Erro na API Web (%s %s)", method, path)
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    @staticmethod
    def _json(data: Any, status: HTTPStatus = HTTPStatus.OK) -> tuple[int, str, bytes]:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return int(status), "application/json; charset=utf-8", raw


async def _handle_client(app: WebApp, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not request_line:
            return
        parts = request_line.decode("latin-1").strip().split(" ")
        if len(parts) < 2:
            return
        method, raw_target = parts[0].upper(), parts[1]

        content_length = 0
        while True:
            header_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not header_line or header_line in (b"\r\n", b"\n"):
                break
            h_str = header_line.decode("latin-1").strip()
            if h_str.lower().startswith("content-length:"):
                content_length = int(h_str.split(":", 1)[1].strip())

        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=15.0) if content_length > 0 else b""
        parsed = urlparse(raw_target)
        res = await app.dispatch(method, parsed.path, parse_qs(parsed.query), body)
        if len(res) == 4:
            status, content_type, resp_body, extra_headers = res  # type: ignore[misc]
        else:
            status, content_type, resp_body = res  # type: ignore[misc]
            extra_headers = {}

        phrase = HTTPStatus(status).phrase
        extra_hdrs_str = "".join(f"{k}: {v}\r\n" for k, v in (extra_headers or {}).items())
        headers = (
            f"HTTP/1.1 {status} {phrase}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(resp_body)}\r\n"
            f"{extra_hdrs_str}"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(headers.encode("latin-1") + resp_body)
        await writer.drain()
    except Exception:
        log.debug("Conexão HTTP encerrada prematuramente", exc_info=True)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def serve_web_ui(
    settings: Settings,
    orchestrator: Orchestrator,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    env_path: Path | None = None,
) -> None:
    """Inicia o servidor do Ambiente Gráfico e abre o navegador padrão."""
    app = WebApp(settings, orchestrator, env_path=env_path)
    server = None
    actual_port = port
    for candidate in range(port, port + 10):
        try:
            server = await asyncio.start_server(
                lambda r, w: _handle_client(app, r, w), host=host, port=candidate
            )
            actual_port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError(f"Não foi possível encontrar porta livre entre {port} e {port + 9}")

    url = f"http://{host}:{actual_port}"
    print(f"\n🌐 Ambiente Gráfico BusTracker disponível em: {url}")
    print("   (Pressione Ctrl+C para encerrar o servidor gráfico)\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        async with server:
            await server.serve_forever()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nEncerrando servidor gráfico...")
