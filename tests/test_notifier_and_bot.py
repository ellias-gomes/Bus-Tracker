from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bustracker.config import Settings
from bustracker.db import Storage
from bustracker.models import Itinerary, LegSpec, Level, Offer, PriceStats, Recommendation, Trip, TripSource
from bustracker.notifier import export_csv_report, fmt_daily_summary, should_alert
from bustracker.orchestrator import Orchestrator
from bustracker.scheduler import next_scheduled_run
from bustracker.telegram.bot import TelegramBotHandler

TZ = ZoneInfo("America/Sao_Paulo")


def _rec(level: Level, price: float = 69.90, days_left: int = 10) -> Recommendation:
    it = Itinerary(
        [
            Offer(
                provider="buser",
                origin="rio-de-janeiro-rj",
                destination="cacapava-sp",
                depart_at=datetime(2026, 11, 23, 21, 0, tzinfo=TZ),
                arrive_at=datetime(2026, 11, 24, 2, 0, tzinfo=TZ),
                price=price,
                seats=8,
                url="https://www.buser.com.br/",
            )
        ]
    )
    return Recommendation(
        trip_id="t1",
        leg="ida",
        level=level,
        reasons=["Teste"],
        days_left=days_left,
        best=it,
        alternatives=[],
        stats=PriceStats(samples=5, mean=85.0, minimum=69.90, maximum=99.0),
    )


def test_should_alert_deduplication_and_price_drop(tmp_path: Path):
    settings = Settings(price_drop_alert=5.0)
    storage = Storage(tmp_path / "alerts.db")
    try:
        r1 = _rec(Level.BUY_NOW, price=69.90)
        send, _, milestone = should_alert(settings, storage, r1)
        assert send is True
        storage.record_alert("t1", "ida", r1.level, r1.price, milestone)

        # Mesmo nível e mesmo preço logo em seguida -> não reenvia
        send_again, _, _ = should_alert(settings, storage, r1)
        assert send_again is False

        # Queda de mais de R$ 5 -> envia novo alerta!
        r_drop = _rec(Level.BUY_NOW, price=62.00)
        send_drop, title, _ = should_alert(settings, storage, r_drop)
        assert send_drop is True
        assert "caiu" in title

        # Se marcado como comprado (/comprei), silencia alertas
        storage.kv_set("bought:t1:ida", "1")
        send_bought, _, _ = should_alert(settings, storage, _rec(Level.LAST_SEATS, price=50.0))
        assert send_bought is False
    finally:
        storage.close()


def test_telegram_bot_commands(tmp_path: Path):
    settings = Settings(
        default_origin="rio-de-janeiro-rj",
        default_destination="cacapava-sp",
        default_hubs=["sao-jose-dos-campos-sp"],
        default_outbound_depart_before="22:00",
        default_return_arrive_before="07:15",
    )
    storage = Storage(tmp_path / "bot.db")
    try:
        orch = Orchestrator(settings, storage)
        bot = TelegramBotHandler(settings, orch)

        d_ida = (date.today() + timedelta(days=14)).isoformat()
        d_volta = (date.today() + timedelta(days=15)).isoformat()

        reply_add, _ = asyncio.run(bot.handle_command(f"/adicionar {d_ida} {d_volta} Viagem Teste"))
        assert "cadastrada com sucesso" in reply_add

        reply_list, _ = asyncio.run(bot.handle_command("/viagens"))
        assert "Viagem Teste" in reply_list

        reply_status, _ = asyncio.run(bot.handle_command("/status"))
        assert "Viagem Teste" in reply_status

        trips = storage.list_trips()
        assert len(trips) == 1
        tid = trips[0].id

        reply_bought, _ = asyncio.run(bot.handle_command(f"/comprei {tid} ida"))
        assert "silenciados" in reply_bought

        reply_rm, _ = asyncio.run(bot.handle_command(f"/remover {tid}"))
        assert "desativada" in reply_rm
        assert len(storage.list_trips()) == 0
    finally:
        storage.close()


def test_next_scheduled_run():
    cur = datetime(2026, 11, 5, 8, 0, tzinfo=TZ)
    nxt = next_scheduled_run(cur, ["07:30", "19:30"])
    assert nxt == datetime(2026, 11, 5, 19, 30, tzinfo=TZ)


def test_fmt_daily_summary_totals_and_combos():
    trip = Trip(
        id="t-combo",
        name="Viagem Fim de Semana",
        source=TripSource.MANUAL,
        origin="rio-de-janeiro-rj",
        destination="cacapava-sp",
        outbound=LegSpec(date=date(2026, 11, 20)),
        return_leg=LegSpec(date=date(2026, 11, 22)),
    )
    rec_ida = _rec(Level.GOOD, price=75.00, days_left=15)
    rec_ida.leg = "ida"
    rec_ida.trip_id = "t-combo"

    rec_volta = _rec(Level.BUY_NOW, price=65.00, days_left=17)
    rec_volta.leg = "volta"
    rec_volta.trip_id = "t-combo"

    results = [(trip, rec_ida), (trip, rec_volta)]
    bought_map = {("t-combo", "ida"): True, ("t-combo", "volta"): False}

    summary = fmt_daily_summary(
        results,
        bought_map=bought_map,
        target_good=80.0,
        target_excellent=70.0,
    )

    # Verifica totais gerais
    assert "TOTAL GERAL ESTIMADO: R$ 140,00" in summary
    assert "SUBTOTAL RESTANTE (A PAGAR): R$ 65,00" in summary
    # Verifica combo ida + volta
    assert "Combo 2 trechos: <b>R$ 140,00</b>" in summary
    assert "A Pagar: <b>R$ 65,00</b>" in summary


def test_export_csv_report():
    trip = Trip(
        id="t-csv",
        name="Viagem Prova",
        source=TripSource.MANUAL,
        origin="rio-de-janeiro-rj",
        destination="cacapava-sp",
        outbound=LegSpec(date=date(2026, 11, 20)),
    )
    rec = _rec(Level.BUY_NOW, price=69.90, days_left=10)
    rec.trip_id = "t-csv"

    csv_text = export_csv_report(
        [(trip, rec)],
        bought_map={("t-csv", "ida"): True},
        target_good=80.0,
        target_excellent=70.0,
    )

    assert "ID_VIAGEM;NOME_VIAGEM;TRECHO;ORIGEM;DESTINO;DATA_VIAGEM;STATUS" in csv_text
    assert '"t-csv";"Viagem Prova";"IDA";"rio-de-janeiro-rj";"cacapava-sp"' in csv_text
    assert '"69,90";"80,00";"70,00"' in csv_text
    assert '"SIM"' in csv_text


def test_check_all_force_summary_sends_telegram(tmp_path: Path, monkeypatch):
    settings = Settings(
        telegram_bot_token="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ",
        telegram_chat_id="987654321",
        default_origin="rio-de-janeiro-rj",
        default_destination="cacapava-sp",
    )
    storage = Storage(tmp_path / "force_sum.db")
    try:
        orch = Orchestrator(settings, storage)
        trip = Trip(
            id="t-force",
            name="Viagem Force",
            source=TripSource.MANUAL,
            origin="rio-de-janeiro-rj",
            destination="cacapava-sp",
            outbound=LegSpec(date=date.today() + timedelta(days=10)),
        )
        storage.upsert_trip(trip)

        sent_messages = []

        async def fake_send(self, chat_id, text, **kwargs):
            sent_messages.append((chat_id, text))
            return {"message_id": 1}

        from bustracker.telegram.client import TelegramClient

        monkeypatch.setattr(TelegramClient, "send_message", fake_send)

        report = asyncio.run(orch.check_all(notify=True, force_summary=True))
        assert report.alerts_sent >= 1
        assert len(sent_messages) >= 1
        assert "Atualização de Preços das Viagens" in sent_messages[-1][1]
        assert "Viagem Force" in sent_messages[-1][1]
    finally:
        storage.close()
