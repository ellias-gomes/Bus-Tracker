from __future__ import annotations

import asyncio
import json
from datetime import date, time, timedelta
from pathlib import Path

from bustracker.config import Settings, parse_hhmm
from bustracker.db import Storage
from bustracker.models import Level
from bustracker.orchestrator import Orchestrator
from bustracker.tui import InteractiveTUI
from bustracker.utils.text import parse_date, resolve_city, resolve_city_list, search_cities
from bustracker.web import WebApp


def test_short_dd_mm_date_parsing():
    fut = date.today() + timedelta(days=10)
    short = fut.strftime("%d/%m")
    assert parse_date(short) == fut


def test_flexible_time_and_city_resolution():
    assert parse_hhmm("22") == time(22, 0)
    assert parse_hhmm("22h") == time(22, 0)
    assert parse_hhmm("22h30") == time(22, 30)
    assert parse_hhmm("7h15") == time(7, 15)
    assert parse_hhmm("22:00") == time(22, 0)

    assert resolve_city("1") == "sao-paulo-sp"
    assert resolve_city("2") == "rio-de-janeiro-rj"
    assert resolve_city("sao jose dos campos") == "sao-jose-dos-campos-sp"
    assert resolve_city("sao jose dos campos sp") == "sao-jose-dos-campos-sp"
    assert resolve_city("cacapava") == "cacapava-sp"
    assert resolve_city_list("1,2") == ["sao-paulo-sp", "rio-de-janeiro-rj"]

    suggestions = search_cities("sao jose")
    slugs = [c["slug"] for c in suggestions]
    assert "sao-jose-dos-campos-sp" in slugs
    assert "sao-jose-do-rio-preto-sp" in slugs


def test_telegram_placeholder_and_token_validation():
    # Placeholders do .env.example não devem ativar o Telegram
    s_placeholder = Settings(
        telegram_bot_token="seu_bot_token_aqui",
        telegram_chat_id="seu_chat_id_aqui",
    )
    assert s_placeholder.telegram_enabled is False

    # Token malformado não deve ativar
    s_bad = Settings(telegram_bot_token="invalido", telegram_chat_id="123456")
    assert s_bad.telegram_enabled is False

    # Token com formato válido (mesmo se o usuário colar 'bot' na frente) deve ser aceito
    s_valid = Settings(
        telegram_bot_token="bot123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        telegram_chat_id="987654321",
    )
    assert s_valid.telegram_enabled is True


def test_interactive_tui_flow(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEFAULT_ORIGIN=sao-paulo-sp\nDEFAULT_DESTINATION=rio-de-janeiro-rj\nTARGET_PRICE_GOOD=80.00\nTARGET_PRICE_EXCELLENT=70.00\n",
        encoding="utf-8",
    )
    settings = Settings(
        default_origin="sao-paulo-sp",
        default_destination="rio-de-janeiro-rj",
        default_hubs=[],
        default_outbound_depart_before="22:00",
        default_return_arrive_before="07:15",
    )
    storage = Storage(tmp_path / "tui.db")
    try:
        orch = Orchestrator(settings, storage)
        ev_day = (date.today() + timedelta(days=20)).strftime("%d/%m/%Y")
        inputs = iter(
            [
                # 1) Escolhe opção 4 (Agendar Compromisso / Prova)
                "4",
                ev_day,
                "Prova TUI",
                "s",  # usar rota padrão
                "n",  # não consultar agora
                "",   # Enter no pause
                # 2) Escolhe opção 6 (Gerenciar Minhas Viagens) -> seleciona viagem 1 -> ação 1 (marcar IDA comprada)
                "6",
                "1",
                "1",
                "",   # Enter no pause
                # 3) Escolhe opção 9 (Configurações) -> sub 2 (Preços-Alvo)
                "9",
                "2",
                "85.00",
                "72.00",
                "",   # Enter no pause
                # 4) Escolhe opção 1 (Ver Status)
                "1",
                "",   # Enter no pause
                # 5) Sair
                "0",
            ]
        )
        tui = InteractiveTUI(settings, orch, env_path=env_file, input_fn=lambda _p="": next(inputs))
        rc = asyncio.run(tui.run())
        assert rc == 0

        trips = storage.list_trips()
        assert len(trips) == 1
        assert trips[0].name == "Prova TUI"
        assert storage.kv_get(f"bought:{trips[0].id}:ida") == "1"
        assert tui.settings.target_price_good == 85.0
        assert tui.settings.target_price_excellent == 72.0
    finally:
        storage.close()


def test_web_app_api_endpoints(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEFAULT_ORIGIN=sao-paulo-sp\nDEFAULT_DESTINATION=rio-de-janeiro-rj\n",
        encoding="utf-8",
    )
    settings = Settings(
        default_origin="sao-paulo-sp",
        default_destination="rio-de-janeiro-rj",
        default_hubs=[],
    )
    storage = Storage(tmp_path / "web.db")
    try:
        orch = Orchestrator(settings, storage)
        web = WebApp(settings, orch, env_path=env_file)

        # 1) Página HTML principal e autocompletar de cidades
        status, ctype, html_bytes = asyncio.run(web.dispatch("GET", "/", {}, b""))
        assert status == 200
        assert "text/html" in ctype
        assert b"BusTracker" in html_bytes

        status, _, cities_body = asyncio.run(web.dispatch("GET", "/api/cities", {"q": ["sao jose"]}, b""))
        assert status == 200
        cities_data = json.loads(cities_body)["cities"]
        assert any(c["slug"] == "sao-jose-dos-campos-sp" for c in cities_data)
        assert any(c["slug"] == "sao-jose-do-rio-preto-sp" for c in cities_data)

        # 2) Agendar compromisso via API Web
        ev_date = (date.today() + timedelta(days=15)).isoformat()
        status, _, body = asyncio.run(
            web.dispatch(
                "POST",
                "/api/trips/event",
                {},
                json.dumps({"event_date": ev_date, "name": "Prova Web"}).encode(),
            )
        )
        assert status == 200
        data = json.loads(body)
        assert len(data["state"]["trips"]) == 1
        tid = data["state"]["trips"][0]["id"]

        # 3) Salvar amostra e consultar gráfico de histórico
        storage.save_snapshot(tid, "ida", None, 0, Level.NO_DATA)
        status, _, hist_body = asyncio.run(
            web.dispatch("GET", "/api/history", {"trip_id": [tid], "leg": ["ida"]}, b"")
        )
        assert status == 200
        hist_data = json.loads(hist_body)
        assert hist_data["trip_id"] == tid

        # 4) Marcar como comprada e remover
        status, _, _ = asyncio.run(
            web.dispatch("POST", "/api/trips/bought", {}, json.dumps({"trip_id": tid, "leg": "ida", "bought": True}).encode())
        )
        assert status == 200
        assert storage.kv_get(f"bought:{tid}:ida") == "1"

        status, _, del_body = asyncio.run(
            web.dispatch("POST", "/api/trips/delete", {}, json.dumps({"trip_id": tid}).encode())
        )
        assert status == 200
        assert len(json.loads(del_body)["state"]["trips"]) == 0

        # 5) Importar calendário via API Web (conteúdo .ics)
        sample_ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:prova-123\r\n"
            "SUMMARY:Prova Semestral Presencial\r\n"
            f"DTSTART:{(date.today() + timedelta(days=25)).strftime('%Y%m%d')}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        status, _, imp_body = asyncio.run(
            web.dispatch(
                "POST",
                "/api/calendar/import",
                {},
                json.dumps({"filename": "calendario.ics", "content": sample_ics}).encode(),
            )
        )
        assert status == 200
        imp_data = json.loads(imp_body)
        assert imp_data["ok"] is True
        assert imp_data["count"] == 1
        assert "Prova Semestral Presencial" in imp_data["trips"]

        # 6) Exportar CSV via API Web
        csv_resp = asyncio.run(web.dispatch("GET", "/api/export/csv", {}, b""))
        assert len(csv_resp) == 4
        assert csv_resp[0] == 200
        assert "text/csv" in csv_resp[1]
        csv_bytes = csv_resp[2]
        assert csv_bytes.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
        csv_decoded = csv_bytes.decode("utf-8")
        assert "ID_VIAGEM;NOME_VIAGEM;TRECHO" in csv_decoded
        assert "Content-Disposition" in csv_resp[3]

        # 7) Agendar viagem customizada com limite de ida e volta independentes
        dt_out = (date.today() + timedelta(days=30)).isoformat()
        dt_ret = (date.today() + timedelta(days=32)).isoformat()
        status, _, add_body = asyncio.run(
            web.dispatch(
                "POST",
                "/api/trips/add",
                {},
                json.dumps({
                    "name": "Férias Teste",
                    "outbound_date": dt_out,
                    "return_date": dt_ret,
                    "outbound_depart_before": "21h30",
                    "return_depart_before": "19h00",
                    "return_arrive_before": "06h30",
                }).encode(),
            )
        )
        assert status == 200
        state_dict = json.loads(add_body)["state"]
        assert "recs" in state_dict
        assert "recommendations" in state_dict
        assert state_dict["recs"] == state_dict["recommendations"]
        assert "lowest_price" in state_dict
        added_trip = [t for t in state_dict["trips"] if t["name"] == "Férias Teste"][0]
        assert added_trip["outbound"]["depart_before"] == "21:30"
        assert added_trip["return"]["depart_before"] == "19:00"
        assert added_trip["return"]["arrive_before"] == "06:30"

        # 8) Salvar configurações com DEFAULT_RETURN_DEPART_BEFORE
        status, _, set_body = asyncio.run(
            web.dispatch(
                "POST",
                "/api/settings",
                {},
                json.dumps({
                    "updates": {
                        "DEFAULT_OUTBOUND_DEPART_BEFORE": "21:00",
                        "DEFAULT_RETURN_DEPART_BEFORE": "20:00",
                    }
                }).encode(),
            )
        )
        assert status == 200
        saved_cfg = json.loads(set_body)["state"]["settings"]
        assert saved_cfg["DEFAULT_OUTBOUND_DEPART_BEFORE"] == "21:00"
        assert saved_cfg["DEFAULT_RETURN_DEPART_BEFORE"] == "20:00"
    finally:
        storage.close()
