"""Interface de linha de comando (CLI) do BusTracker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .calendar_sync import trip_from_dates, trip_from_event
from .config import load_settings
from .db import Storage
from .models import Trip, TripSource
from .notifier import (
    export_csv_report,
    fmt_daily_summary,
    fmt_history,
    fmt_itinerary,
    fmt_recommendation,
    fmt_trip_summary,
    strip_html,
)
from .orchestrator import Orchestrator
from .scheduler import run_daemon
from .tui import InteractiveTUI
from .utils.text import city_label, fmt_date, parse_date, resolve_city, resolve_city_list
from .web import serve_web_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bustracker",
        description="Monitor inteligente e preditor de passagens rodoviárias (Menu TUI, Painel Web e CLI).",
    )
    parser.add_argument("--env-file", help="Caminho para arquivo .env customizado")
    parser.add_argument("-i", "--interactive", "--menu", action="store_true", help="Abre o menu interativo no terminal (padrão)")
    parser.add_argument("--gui", "--web", action="store_true", help="Abre o ambiente gráfico no navegador (Web UI)")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor gráfico (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Porta do servidor gráfico (padrão: 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Não abre o navegador automaticamente no modo --gui")
    parser.add_argument("--run-once", action="store_true", help="Executa uma coleta única e encerra")
    parser.add_argument("--daemon", action="store_true", help="Executa continuamente (agendador + bot Telegram)")
    parser.add_argument("--no-notify", action="store_true", help="Não envia alertas ao Telegram durante --run-once")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("menu", help="Abre o menu interativo amigável no terminal (ideal para Termux/Linux)")
    p_gui = sub.add_parser("gui", aliases=["web"], help="Abre o ambiente gráfico visual no navegador (Web UI)")
    p_gui.add_argument("--host", default="127.0.0.1", help="Host (use 0.0.0.0 para acessar de outro dispositivo)")
    p_gui.add_argument("--port", type=int, default=8080, help="Porta (padrão: 8080)")
    p_gui.add_argument("--no-browser", action="store_true", help="Não tenta abrir o navegador automaticamente")

    p_check = sub.add_parser("check", help="Executa uma coleta única (equivalente a --run-once)")
    p_check.add_argument("--no-notify", action="store_true", help="Não envia alertas ao Telegram")
    sub.add_parser("daemon", help="Executa o modo contínuo (equivalente a --daemon)")
    sub.add_parser("status", help="Exibe o último estado salvo das viagens ativas")
    sub.add_parser("list", help="Lista as viagens ativas cadastradas")
    sub.add_parser("sync", help="Sincroniza viagens do JSON local e do calendário iCal (.ics)")

    p_import = sub.add_parser("import", help="Importa viagens de arquivo de calendário (.ics ou .json)")
    p_import.add_argument("file", help="Caminho do arquivo (.ics ou .json)")

    p_add = sub.add_parser("add", help="Adiciona uma viagem manualmente")
    p_add.add_argument("outbound_date", help="Data de ida (AAAA-MM-DD ou DD/MM/AAAA)")
    p_add.add_argument("return_date", nargs="?", help="Data de volta opcional (AAAA-MM-DD ou DD/MM/AAAA)")
    p_add.add_argument("--origin", help="Cidade de origem (ex.: rio-de-janeiro-rj)")
    p_add.add_argument("--dest", help="Cidade de destino (ex.: cacapava-sp)")
    p_add.add_argument("--hubs", help="Hubs separados por vírgula (ex.: sao-jose-dos-campos-sp)")
    p_add.add_argument("--name", help="Nome/descrição da viagem")

    p_ev = sub.add_parser("event", help="Adiciona viagem a partir da data do compromisso")
    p_ev.add_argument("event_date", help="Data do compromisso (AAAA-MM-DD ou DD/MM/AAAA)")
    p_ev.add_argument("--name", default="Compromisso", help="Nome do compromisso")
    p_ev.add_argument("--origin", help="Cidade de origem")
    p_ev.add_argument("--dest", help="Cidade de destino")
    p_ev.add_argument("--one-way", action="store_true", help="Somente ida")

    p_rm = sub.add_parser("remove", help="Desativa uma viagem pelo ID")
    p_rm.add_argument("trip_id", help="ID da viagem")

    p_bought = sub.add_parser("bought", help="Marca trecho como comprado para silenciar alertas")
    p_bought.add_argument("trip_id", help="ID da viagem")
    p_bought.add_argument("leg", nargs="?", choices=["ida", "volta"], help="Trecho (padrão: ambos)")

    p_hist = sub.add_parser("history", help="Exibe histórico de preços de uma viagem")
    p_hist.add_argument("trip_id", nargs="?", help="ID da viagem (padrão: próxima ativa)")
    p_hist.add_argument("leg", nargs="?", default="ida", choices=["ida", "volta"], help="Trecho")

    p_export = sub.add_parser("export", help="Exporta relatório de viagens e preços em planilha CSV")
    p_export.add_argument(
        "--output",
        "-o",
        default="data/relatorio_viagens.csv",
        help="Caminho do arquivo CSV de saída (padrão: data/relatorio_viagens.csv)",
    )

    p_search = sub.add_parser("search", help="Busca pontual de passagens em tempo real")
    p_search.add_argument("origin", help="Origem (ex.: rio-de-janeiro-rj)")
    p_search.add_argument("destination", help="Destino (ex.: sao-paulo-sp)")
    p_search.add_argument("date", help="Data (AAAA-MM-DD ou DD/MM/AAAA)")
    p_search.add_argument("--hubs", help="Hubs alternativos separados por vírgula")
    p_search.add_argument("--after", help="Horário mínimo de partida (HH:MM)")
    p_search.add_argument("--before", help="Horário máximo de partida (HH:MM)")
    p_search.add_argument("--arrive-before", help="Horário máximo de chegada (HH:MM)")
    p_search.add_argument("--arrive-day-offset", type=int, default=0, help="Dia da chegada máxima (0 ou 1)")

    return parser


async def _run_async(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    log_level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if log_level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    storage = Storage(settings.database_path)
    orchestrator = Orchestrator(settings, storage)
    env_path = Path(args.env_file) if args.env_file else None
    cmd = args.command
    if args.run_once:
        cmd = "check"
    elif args.daemon:
        cmd = "daemon"
    elif args.gui:
        cmd = "gui"
    elif args.interactive or (cmd is None and sys.stdin.isatty()):
        cmd = "menu"

    try:
        if cmd == "menu":
            tui = InteractiveTUI(settings, orchestrator, env_path=env_path)
            return await tui.run()

        if cmd in ("gui", "web"):
            await serve_web_ui(
                settings,
                orchestrator,
                host=getattr(args, "host", "127.0.0.1"),
                port=getattr(args, "port", 8080),
                open_browser=not getattr(args, "no_browser", False),
                env_path=env_path,
            )
            return 0

        if cmd == "daemon":
            await run_daemon(settings, orchestrator)
            return 0

        if cmd == "check":
            report = await orchestrator.check_all(notify=not args.no_notify, force_summary=not args.no_notify)
            bought_map = {
                (trip.id, rec.leg): bool(storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
                for trip, rec in report.results
            }
            print(
                strip_html(
                    fmt_daily_summary(
                        report.results,
                        report.errors,
                        bought_map=bought_map,
                        target_good=settings.target_price_good,
                        target_excellent=settings.target_price_excellent,
                    )
                )
            )
            for trip, rec in report.results:
                print("\n" + "-" * 60)
                print(strip_html(fmt_recommendation(trip, rec)))
            return 0

        if cmd == "sync":
            summary = await orchestrator.sync_sources()
            for src, (upserted, removed) in summary.items():
                print(f"[{src}] {upserted} viagem(ns) sincronizada(s), {removed} desativada(s).")
            if not summary:
                print("Nenhuma fonte externa (JSON/ICS) ativa para sincronizar.")
            return 0

        if cmd == "import":
            file_path = Path(args.file).expanduser()
            if not file_path.exists():
                print(f"Erro: Arquivo '{args.file}' não encontrado.", file=sys.stderr)
                return 1
            imported = orchestrator.import_calendar(file_path)
            if not imported:
                print(f"Nenhum evento/viagem importado de '{file_path.name}'. Verifique o filtro de palavras-chave ou o formato.")
                return 0
            print(f"✅ {len(imported)} viagem(ns) importada(s) com sucesso de '{file_path.name}':")
            for t in imported:
                print("\n" + strip_html(fmt_trip_summary(t)))
            return 0

        if cmd == "status":
            await orchestrator.sync_sources()
            statuses = orchestrator.latest_status()
            bought_map = {
                (trip.id, rec.leg): bool(storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
                for trip, rec in statuses
            }
            print(
                strip_html(
                    fmt_daily_summary(
                        statuses,
                        bought_map=bought_map,
                        target_good=settings.target_price_good,
                        target_excellent=settings.target_price_excellent,
                    )
                )
            )
            for trip, rec in statuses:
                print("\n" + "-" * 60)
                print(strip_html(fmt_recommendation(trip, rec)))
            return 0

        if cmd == "export":
            await orchestrator.sync_sources()
            statuses = orchestrator.latest_status()
            if not statuses:
                print("Nenhuma viagem ativa com cotação para exportar.")
                return 0
            bought_map = {
                (trip.id, rec.leg): bool(storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
                for trip, rec in statuses
            }
            csv_content = export_csv_report(
                statuses,
                bought_map=bought_map,
                target_good=settings.target_price_good,
                target_excellent=settings.target_price_excellent,
            )
            out_path = Path(args.output).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(csv_content, encoding="utf-8")
            print(f"✅ Relatório CSV exportado com sucesso ({len(statuses)} trechos):\n   {out_path.resolve()}")
            return 0

        if cmd == "list":
            await orchestrator.sync_sources()
            trips = storage.list_trips(active_only=True)
            if not trips:
                print("Nenhuma viagem ativa.")
                return 0
            for t in trips:
                print(strip_html(fmt_trip_summary(t)))
                print()
            return 0

        if cmd == "add":
            dt_out = parse_date(args.outbound_date)
            dt_ret = parse_date(args.return_date) if args.return_date else None
            hubs = resolve_city_list(args.hubs) if args.hubs else None
            trip = trip_from_dates(
                settings,
                dt_out,
                dt_ret,
                trip_id=Trip.new_id("cli"),
                name=args.name or f"Viagem {dt_out.strftime('%d/%m')}",
                source=TripSource.MANUAL,
                origin=args.origin,
                destination=args.dest,
                hubs=hubs,
            )
            storage.upsert_trip(trip)
            print("Viagem cadastrada:\n" + strip_html(fmt_trip_summary(trip)))
            return 0

        if cmd == "event":
            dt_ev = parse_date(args.event_date)
            trip = trip_from_event(
                settings,
                dt_ev,
                trip_id=Trip.new_id("ev"),
                name=args.name,
                source=TripSource.MANUAL,
                origin=args.origin,
                destination=args.dest,
                one_way=args.one_way,
            )
            storage.upsert_trip(trip)
            print("Compromisso cadastrado:\n" + strip_html(fmt_trip_summary(trip)))
            return 0

        if cmd == "remove":
            if storage.deactivate_trip(args.trip_id):
                print(f"Viagem {args.trip_id} desativada.")
                return 0
            print(f"Viagem {args.trip_id} não encontrada.", file=sys.stderr)
            return 1

        if cmd == "bought":
            legs = [args.leg] if args.leg else ["ida", "volta"]
            for leg in legs:
                storage.kv_set(f"bought:{args.trip_id}:{leg}", "1")
            print(f"Alertas silenciados para {args.trip_id} ({', '.join(legs)}).")
            return 0

        if cmd == "history":
            trips = storage.list_trips(active_only=True)
            trip = storage.get_trip(args.trip_id) if args.trip_id else (trips[0] if trips else None)
            if not trip:
                print("Nenhuma viagem encontrada.", file=sys.stderr)
                return 1
            hist = storage.daily_min_prices(trip.id, args.leg, settings.history_window_days)
            print(strip_html(fmt_history(trip, args.leg, hist, settings.timezone)))
            return 0

        if cmd == "search":
            dt = parse_date(args.date)
            hubs = resolve_city_list(args.hubs) if args.hubs is not None else None
            its = await orchestrator.search_ad_hoc(
                args.origin,
                args.destination,
                dt,
                hubs=hubs,
                depart_after=args.after,
                depart_before=args.before,
                arrive_before=args.arrive_before,
                arrive_day_offset=args.arrive_day_offset,
            )
            orig_lbl = city_label(resolve_city(args.origin))
            dest_lbl = city_label(resolve_city(args.destination))
            print(f"Busca: {orig_lbl} -> {dest_lbl} em {fmt_date(dt)} ({len(its)} opções)")
            for it in its[:10]:
                print("\n" + strip_html(fmt_itinerary(it, detailed=True)))
            return 0

        build_parser().print_help()
        return 0
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run_async(args))
