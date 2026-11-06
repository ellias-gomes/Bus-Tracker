"""Interface interativa amigável de terminal (TUI) para Linux e Termux (Android)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Callable

from .calendar_sync import trip_from_dates, trip_from_event
from .config import Settings
from .env_editor import update_env_values
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
from .utils.text import (
    COMMON_CITIES,
    city_label,
    fmt_date,
    fmt_money,
    parse_date,
    resolve_city,
    resolve_city_list,
)

# Cores ANSI leves (compatíveis com qualquer terminal Linux e Termux)
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def _clear_screen() -> None:
    """Limpa a tela do terminal para evitar acúmulo de linhas antigas."""
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def _box_title(title: str, clear: bool = True) -> str:
    if clear:
        _clear_screen()
    line = "═" * 62
    return f"\n{CYAN}{BOLD}╔{line}╗\n║ {title.ljust(60)} ║\n╚{line}╝{RESET}"


def _ask(prompt: str, default: str = "", input_fn: Callable[[str], str] = input) -> str:
    hint = f" {DIM}[Enter = {default}]{RESET}" if default else ""
    raw = input_fn(f"{BOLD}▸ {prompt}{RESET}{hint}: ").strip()
    return raw if raw else default


def _print_quick_cities() -> None:
    for idx, (slug, name) in enumerate(COMMON_CITIES[:8], start=1):
        print(f"  {CYAN}[{idx}]{RESET} {name:<26} ({slug})")


def _ask_city(
    label: str,
    default_slug: str,
    input_fn: Callable[[str], str] = input,
) -> str:
    print(f"\n{BOLD}{label}:{RESET}")
    _print_quick_cities()
    print(f"  {DIM}Digite o número (1-8), o nome (ex.: sao jose dos campos sp) ou Enter para padrão.{RESET}")
    default_disp = default_slug or COMMON_CITIES[0][0]
    ans = _ask(label, default_disp, input_fn=input_fn)
    return resolve_city(ans)


def _ask_hubs(
    default_hubs: list[str],
    input_fn: Callable[[str], str] = input,
) -> list[str]:
    print(f"\n{BOLD}Hubs alternativos (cidades próximas para desembarque/conexão):{RESET}")
    print(f"  {DIM}Você pode usar os números da lista acima (ex.: 3,5), nomes (ex.: sao jose, taubate) ou 0 para nenhum.{RESET}")
    default_str = ",".join(default_hubs)
    raw = _ask("Hubs alternativos", default_str, input_fn=input_fn)
    if raw.strip().lower() in ("0", "nenhum", "none", "-"):
        return []
    return resolve_city_list(raw)


def _pause(input_fn: Callable[[str], str] = input) -> None:
    try:
        input_fn(f"\n{DIM}[Pressione Enter para voltar ao menu...]{RESET}")
    except EOFError:
        pass


class InteractiveTUI:
    def __init__(
        self,
        settings: Settings,
        orchestrator: Orchestrator,
        env_path: Path | None = None,
        input_fn: Callable[[str], str] = input,
    ):
        self.settings = settings
        self.orchestrator = orchestrator
        self.storage = orchestrator.storage
        self.env_path = env_path
        self.input_fn = input_fn

    def _header(self) -> str:
        orig = city_label(self.settings.default_origin) if self.settings.default_origin else "Não definida"
        dest = city_label(self.settings.default_destination) if self.settings.default_destination else "Não definido"
        hubs_lbl = ", ".join(city_label(h) for h in self.settings.default_hubs) or "Nenhum"
        trips_count = len(self.storage.list_trips(active_only=True))
        tg_status = f"{GREEN}Ativo{RESET}" if self.settings.telegram_enabled else f"{YELLOW}Não configurado{RESET}"
        return (
            _box_title("🚌 BusTracker — Central Interativa de Passagens", clear=True)
            + f"\n  📍 Rota Padrão: {BOLD}{orig} ↔ {dest}{RESET}"
            + f"\n  🔀 Hubs Padrão: {DIM}{hubs_lbl}{RESET}"
            + f"\n  🎯 Preço Alvo : Bom ≤ {BOLD}{fmt_money(self.settings.target_price_good)}{RESET} | "
            f"Excelente ≤ {BOLD}{fmt_money(self.settings.target_price_excellent)}{RESET}"
            + f"\n  🗂️ Viagens    : {BOLD}{trips_count} ativa(s){RESET}   •   🤖 Telegram: {tg_status}\n"
        )

    async def run(self) -> int:
        await self.orchestrator.sync_sources()
        while True:
            print(self._header())
            print(f"  {CYAN}[1]{RESET} 📊 Ver Status e Recomendações (Última Coleta)")
            print(f"  {CYAN}[2]{RESET} 🔄 Atualizar Preços Agora (Consultar Viações)")
            print(f"  {CYAN}[3]{RESET} 🔎 Busca Rápida de Passagens (Qualquer Cidade/Data)")
            print(f"  {CYAN}[4]{RESET} 📅 Agendar Compromisso / Prova (Calcula Ida D-1 e Volta D0)")
            print(f"  {CYAN}[5]{RESET} ➕ Agendar Viagem Personalizada (Ida e Volta)")
            print(f"  {CYAN}[6]{RESET} 🗂️ Gerenciar Minhas Viagens (Listar / Já Comprei / Remover)")
            print(f"  {CYAN}[7]{RESET} 📁 Importar Calendário por Arquivo (.ics / .json)")
            print(f"  {CYAN}[8]{RESET} 📈 Ver Gráfico de Histórico de Preços")
            print(f"  {CYAN}[9]{RESET} ⚙️ Configurar Rota, Preços, Calendário (.ics) e Telegram")
            print(f"  {CYAN}[E]{RESET} 📥 Exportar Relatório em Planilha CSV")
            print(f"  {CYAN}[W]{RESET} 🌐 Abrir Ambiente Gráfico no Navegador (Web UI)")
            print(f"  {CYAN}[0]{RESET} 🚪 Sair\n")

            try:
                choice = _ask("Escolha uma opção (0-9, E, W)", "1", input_fn=self.input_fn)
            except (EOFError, KeyboardInterrupt):
                print("\nAté logo!")
                return 0

            try:
                if choice == "0" or choice.lower() in ("q", "sair", "exit"):
                    print("Até logo!")
                    return 0
                elif choice == "1":
                    await self._action_status()
                elif choice == "2":
                    await self._action_check_now()
                elif choice == "3":
                    await self._action_quick_search()
                elif choice == "4":
                    await self._action_add_event()
                elif choice == "5":
                    await self._action_add_trip()
                elif choice == "6":
                    self._action_manage_trips()
                elif choice == "7":
                    await self._action_import_file()
                elif choice == "8":
                    self._action_history()
                elif choice == "9":
                    await self._action_settings()
                elif choice.upper() in ("E", "CSV", "EXPORT"):
                    await self._action_export_csv()
                elif choice.upper() in ("W", "WEB", "GUI"):
                    await self._action_launch_web()
                else:
                    print(f"{YELLOW}Opção inválida. Digite um número de 0 a 9 (ou E, W).{RESET}")
            except Exception as exc:
                print(f"\n{RED}⚠️ Atenção: {exc}{RESET}")

            _pause(self.input_fn)

    async def _action_status(self) -> None:
        await self.orchestrator.sync_sources()
        statuses = self.orchestrator.latest_status()
        bought_map = {
            (trip.id, rec.leg): bool(self.storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
            for trip, rec in statuses
        }
        print(_box_title("📊 Status das Viagens Monitoradas"))
        print(
            strip_html(
                fmt_daily_summary(
                    statuses,
                    bought_map=bought_map,
                    target_good=self.settings.target_price_good,
                    target_excellent=self.settings.target_price_excellent,
                )
            )
        )
        for trip, rec in statuses:
            print("\n" + "─" * 62)
            print(strip_html(fmt_recommendation(trip, rec)))

    async def _action_check_now(self) -> None:
        print(_box_title("🔄 Atualizando Preços nas Viações"))
        print(f"\n{CYAN}⏳ Consultando ofertas... aguarde alguns segundos.{RESET}")
        report = await self.orchestrator.check_all(notify=True, force_summary=True)
        bought_map = {
            (trip.id, rec.leg): bool(self.storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
            for trip, rec in report.results
        }
        print(_box_title("✅ Coleta Concluída"))
        if self.settings.telegram_enabled and report.alerts_sent:
            print(f"  {GREEN}🤖 Atualização enviada com sucesso ao seu Telegram!{RESET}\n")
        print(
            strip_html(
                fmt_daily_summary(
                    report.results,
                    report.errors,
                    bought_map=bought_map,
                    target_good=self.settings.target_price_good,
                    target_excellent=self.settings.target_price_excellent,
                )
            )
        )
        for trip, rec in report.results:
            print("\n" + "─" * 62)
            print(strip_html(fmt_recommendation(trip, rec)))

    async def _action_export_csv(self) -> None:
        print(_box_title("📥 Exportar Relatório em Planilha CSV"))
        await self.orchestrator.sync_sources()
        statuses = self.orchestrator.latest_status()
        if not statuses:
            print(f"\n{YELLOW}Nenhuma viagem ativa com cotação para exportar.{RESET}")
            return
        bought_map = {
            (trip.id, rec.leg): bool(self.storage.kv_get(f"bought:{trip.id}:{rec.leg}"))
            for trip, rec in statuses
        }
        default_path = "data/relatorio_viagens.csv"
        path_str = _ask("Caminho do arquivo CSV para salvar", default_path, input_fn=self.input_fn)
        out_path = Path(path_str).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        csv_content = export_csv_report(
            statuses,
            bought_map=bought_map,
            target_good=self.settings.target_price_good,
            target_excellent=self.settings.target_price_excellent,
        )
        out_path.write_text(csv_content, encoding="utf-8")
        print(f"\n{GREEN}✅ Relatório CSV exportado com sucesso ({len(statuses)} trecho(s)):{RESET}")
        print(f"  {out_path.resolve()}")

    async def _action_quick_search(self) -> None:
        print(_box_title("🔎 Busca Rápida de Passagens"))
        origin = _ask_city("Cidade de Origem", self.settings.default_origin or "rio-de-janeiro-rj", self.input_fn)
        dest = _ask_city("Cidade de Destino", self.settings.default_destination or "cacapava-sp", self.input_fn)
        dt_raw = _ask("Data da viagem (DD/MM ou DD/MM/AAAA)", "", self.input_fn)
        dt = parse_date(dt_raw)
        after = _ask("Sair a partir de qual horário? (ex.: 18, 18h, 18:30 ou vazio)", "", self.input_fn)
        before = _ask("Sair até qual horário? (ex.: 22, 22h, 22h30 ou vazio)", "", self.input_fn)
        hubs = _ask_hubs(self.settings.default_hubs, self.input_fn)

        hubs_desc = f" (hubs: {', '.join(city_label(h) for h in hubs)})" if hubs else ""
        print(
            f"\n{CYAN}⏳ Buscando passagens para {city_label(origin)} → {city_label(dest)}"
            f"{hubs_desc} em {fmt_date(dt)}...{RESET}"
        )
        its = await self.orchestrator.search_ad_hoc(
            origin,
            dest,
            dt,
            hubs=hubs,
            depart_after=after or None,
            depart_before=before or None,
        )
        if not its:
            print(f"\n{YELLOW}Nenhuma opção encontrada dentro dos filtros informados.{RESET}")
            return
        print(f"\n{GREEN}{BOLD}Encontradas {len(its)} opções (mostrando até 8 mais baratas):{RESET}")
        for idx, it in enumerate(its[:8], start=1):
            print(f"\n{BOLD}[Opção {idx}]{RESET}")
            print(strip_html(fmt_itinerary(it, detailed=True)))

    async def _action_add_event(self) -> None:
        print(_box_title("📅 Agendar Compromisso / Prova"))
        print(
            f"  {DIM}Calcula automaticamente a IDA em D{self.settings.event_outbound_day_offset:+d} "
            f"e a VOLTA em D{self.settings.event_return_day_offset:+d} com seus horários padrão.{RESET}"
        )
        dt_raw = _ask("Data do compromisso/prova (DD/MM ou DD/MM/AAAA)", "", self.input_fn)
        ev_date: date = parse_date(dt_raw)
        name = _ask("Nome do compromisso", f"Compromisso {ev_date.strftime('%d/%m')}", self.input_fn)
        custom_route = _ask("Usar rota padrão? (s/n)", "s", self.input_fn).lower()
        origin = None
        dest = None
        if custom_route.startswith("n"):
            origin = _ask_city("Cidade de Origem", self.settings.default_origin, self.input_fn)
            dest = _ask_city("Cidade de Destino", self.settings.default_destination, self.input_fn)

        trip = trip_from_event(
            self.settings,
            ev_date,
            trip_id=Trip.new_id("ev"),
            name=name,
            source=TripSource.MANUAL,
            origin=origin,
            destination=dest,
        )
        self.storage.upsert_trip(trip)
        print(f"\n{GREEN}✅ Compromisso cadastrado com sucesso!{RESET}\n")
        print(strip_html(fmt_trip_summary(trip)))
        check_now = _ask("Deseja consultar os preços dessa viagem agora? (s/n)", "s", self.input_fn).lower()
        if check_now.startswith("s"):
            await self._action_check_now()

    async def _action_add_trip(self) -> None:
        print(_box_title("➕ Agendar Viagem Personalizada"))
        origin = _ask_city("Cidade de Origem", self.settings.default_origin or "rio-de-janeiro-rj", self.input_fn)
        dest = _ask_city("Cidade de Destino", self.settings.default_destination or "cacapava-sp", self.input_fn)
        dt_out = parse_date(_ask("Data de IDA (DD/MM ou DD/MM/AAAA)", "", self.input_fn))
        ret_raw = _ask("Data de VOLTA (DD/MM, DD/MM/AAAA ou vazio se somente ida)", "", self.input_fn)
        dt_ret = parse_date(ret_raw) if ret_raw else None
        name = _ask("Nome/Descrição da viagem", f"Viagem {dt_out.strftime('%d/%m')}", self.input_fn)

        out_before = _ask(
            "Horário máximo de saída na IDA (ex.: 22, 22h, 22:00)",
            self.settings.default_outbound_depart_before,
            self.input_fn,
        )
        ret_arrive = ""
        if dt_ret:
            ret_arrive = _ask(
                "Horário máximo de chegada na VOLTA (ex.: 7, 7h15, 07:15)",
                self.settings.default_return_arrive_before,
                self.input_fn,
            )

        trip = trip_from_dates(
            self.settings,
            dt_out,
            dt_ret,
            trip_id=Trip.new_id("tui"),
            name=name,
            source=TripSource.MANUAL,
            origin=origin,
            destination=dest,
            outbound_depart_before=out_before,
            return_arrive_before=ret_arrive if dt_ret else None,
        )
        self.storage.upsert_trip(trip)
        print(f"\n{GREEN}✅ Viagem cadastrada com sucesso!{RESET}\n")
        print(strip_html(fmt_trip_summary(trip)))

    async def _action_import_file(self) -> None:
        print(_box_title("📁 Importar Calendário por Arquivo"))
        print(f"  {DIM}Informe o caminho de um arquivo .ics (Google Calendar / iCal) ou .json local.{RESET}")
        raw_path = _ask("Caminho do arquivo", "", self.input_fn)
        if not raw_path:
            print(f"{YELLOW}Nenhum arquivo informado.{RESET}")
            return
        p = Path(raw_path).expanduser()
        if not p.exists() or not p.is_file():
            print(f"{RED}Arquivo '{raw_path}' não encontrado no disco.{RESET}")
            return
        try:
            imported = self.orchestrator.import_calendar(p)
            if not imported:
                print(f"\n{YELLOW}Nenhum evento importado. Verifique palavras-chave ou o conteúdo do arquivo.{RESET}")
                return
            print(f"\n{GREEN}✅ {len(imported)} viagem(ns) importada(s) com sucesso de '{p.name}':{RESET}\n")
            for t in imported:
                print(strip_html(fmt_trip_summary(t)))
            check_now = _ask("\nDeseja consultar os preços dessas viagens agora? (s/n)", "s", self.input_fn).lower()
            if check_now.startswith("s"):
                await self._action_check_now()
        except Exception as exc:
            print(f"{RED}Falha ao importar arquivo: {exc}{RESET}")

    def _select_trip(self, title: str) -> Trip | None:
        trips = self.storage.list_trips(active_only=True)
        print(_box_title(title))
        if not trips:
            print(f"{YELLOW}Nenhuma viagem ativa no momento.{RESET}")
            return None
        for idx, t in enumerate(trips, start=1):
            print(f"\n{CYAN}{BOLD}[{idx}]{RESET} " + strip_html(fmt_trip_summary(t)))
        sel = _ask(f"\nEscolha o número da viagem (1-{len(trips)}) ou Enter para cancelar", "", self.input_fn)
        if not sel:
            return None
        if sel.isdigit() and 1 <= int(sel) <= len(trips):
            return trips[int(sel) - 1]
        return self.storage.get_trip(sel)

    def _action_manage_trips(self) -> None:
        trip = self._select_trip("🗂️ Gerenciar Minhas Viagens")
        if not trip:
            return
        print(f"\nViagem selecionada: {BOLD}{trip.name}{RESET} ({trip.id})")
        print(f"  {CYAN}[1]{RESET} ✅ Marcar IDA como já comprada (silenciar alertas)")
        print(f"  {CYAN}[2]{RESET} ✅ Marcar VOLTA como já comprada (silenciar alertas)")
        print(f"  {CYAN}[3]{RESET} ✅ Marcar IDA e VOLTA como compradas")
        print(f"  {CYAN}[4]{RESET} 🗑️ Remover / Desativar esta viagem")
        print(f"  {CYAN}[0]{RESET} Voltar")
        act = _ask("Ação", "0", self.input_fn)
        if act == "1":
            self.storage.kv_set(f"bought:{trip.id}:ida", "1")
            print(f"{GREEN}✅ Alertas de IDA silenciados para {trip.name}.{RESET}")
        elif act == "2":
            self.storage.kv_set(f"bought:{trip.id}:volta", "1")
            print(f"{GREEN}✅ Alertas de VOLTA silenciados para {trip.name}.{RESET}")
        elif act == "3":
            self.storage.kv_set(f"bought:{trip.id}:ida", "1")
            self.storage.kv_set(f"bought:{trip.id}:volta", "1")
            print(f"{GREEN}✅ Alertas de IDA e VOLTA silenciados para {trip.name}.{RESET}")
        elif act == "4":
            self.storage.deactivate_trip(trip.id)
            print(f"{GREEN}🗑️ Viagem '{trip.name}' removida do monitoramento.{RESET}")

    def _action_history(self) -> None:
        trip = self._select_trip("📈 Histórico de Preços")
        if not trip:
            return
        leg_raw = _ask("Qual trecho? [I]da ou [V]olta", "I", self.input_fn).lower()
        leg = "volta" if leg_raw.startswith("v") else "ida"
        hist = self.storage.daily_min_prices(trip.id, leg, self.settings.history_window_days)
        print("\n" + strip_html(fmt_history(trip, leg, hist, self.settings.timezone)))

    async def _action_settings(self) -> None:
        print(_box_title("⚙️ Configurações & Calendários (.env)"))
        print(f"  {CYAN}[1]{RESET} Alterar Rota Padrão e Hubs ({self.settings.default_origin} -> {self.settings.default_destination})")
        print(
            f"  {CYAN}[2]{RESET} Alterar Preços-Alvo (Bom: {fmt_money(self.settings.target_price_good)}, "
            f"Excelente: {fmt_money(self.settings.target_price_excellent)})"
        )
        print(
            f"  {CYAN}[3]{RESET} Alterar Janelas Horárias Padrão "
            f"(Ida até {self.settings.default_outbound_depart_before or '23:59'}, "
            f"Volta chegada até {self.settings.default_return_arrive_before or 'livre'})"
        )
        print(f"  {CYAN}[4]{RESET} Configurar Calendário Google / iCal (.ics) e Sincronizar")
        print(f"  {CYAN}[5]{RESET} Configurar Bot do Telegram (Token e Chat ID)")
        print(f"  {CYAN}[0]{RESET} Voltar")

        sub = _ask("Escolha o que deseja configurar", "0", self.input_fn)
        updates: dict[str, str] = {}
        if sub == "1":
            updates["DEFAULT_ORIGIN"] = _ask_city("Nova Origem Padrão", self.settings.default_origin, self.input_fn)
            updates["DEFAULT_DESTINATION"] = _ask_city(
                "Novo Destino Padrão", self.settings.default_destination, self.input_fn
            )
            hubs = _ask_hubs(self.settings.default_hubs, self.input_fn)
            updates["DEFAULT_HUBS"] = ",".join(hubs)
        elif sub == "2":
            updates["TARGET_PRICE_GOOD"] = _ask(
                "Preço considerado BOM (R$)", f"{self.settings.target_price_good:.2f}", self.input_fn
            )
            updates["TARGET_PRICE_EXCELLENT"] = _ask(
                "Preço considerado EXCELENTE (R$)", f"{self.settings.target_price_excellent:.2f}", self.input_fn
            )
        elif sub == "3":
            updates["DEFAULT_OUTBOUND_DEPART_AFTER"] = _ask(
                "Ida - sair a partir de (ex.: 18h, 18:00)", self.settings.default_outbound_depart_after, self.input_fn
            )
            updates["DEFAULT_OUTBOUND_DEPART_BEFORE"] = _ask(
                "Ida - sair no máximo até (ex.: 22, 22h, 22:00)", self.settings.default_outbound_depart_before, self.input_fn
            )
            updates["DEFAULT_RETURN_DEPART_AFTER"] = _ask(
                "Volta - sair a partir de (ex.: 20h, 20:00)", self.settings.default_return_depart_after, self.input_fn
            )
            updates["DEFAULT_RETURN_ARRIVE_BEFORE"] = _ask(
                "Volta - chegar no máximo até (ex.: 7h15, 07:15)", self.settings.default_return_arrive_before, self.input_fn
            )
        elif sub == "4":
            updates["CALENDAR_ICS_URL"] = _ask(
                "URL ou caminho do arquivo .ics", self.settings.calendar_ics_url, self.input_fn
            )
            updates["CALENDAR_KEYWORDS"] = _ask(
                "Palavras-chave dos eventos (separadas por vírgula)",
                ",".join(self.settings.calendar_keywords),
                self.input_fn,
            )
        elif sub == "5":
            updates["TELEGRAM_BOT_TOKEN"] = _ask(
                "TELEGRAM_BOT_TOKEN", self.settings.telegram_bot_token, self.input_fn
            )
            updates["TELEGRAM_CHAT_ID"] = _ask(
                "TELEGRAM_CHAT_ID", self.settings.telegram_chat_id, self.input_fn
            )
        else:
            return

        self.settings = update_env_values(updates, self.env_path)
        self.orchestrator.settings = self.settings
        sync_res = await self.orchestrator.sync_sources()
        print(f"\n{GREEN}✅ Configurações salvas no .env com sucesso!{RESET}")
        if sync_res:
            for src, (up, rm) in sync_res.items():
                print(f"  • Fonte [{src}]: {up} viagem(ns) sincronizada(s), {rm} desativada(s).")

    async def _action_launch_web(self) -> None:
        from .web import serve_web_ui

        await serve_web_ui(self.settings, self.orchestrator, host="127.0.0.1", port=8080, open_browser=True)
