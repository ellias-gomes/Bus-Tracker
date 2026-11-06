from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from bustracker.analyzer import compute_stats, evaluate
from bustracker.config import Settings
from bustracker.models import Itinerary, Level, Offer

TZ = ZoneInfo("America/Sao_Paulo")


def _it(price: float, seats: int = 10, seats_capped: bool = False) -> Itinerary:
    return Itinerary(
        [
            Offer(
                provider="buser",
                origin="rio-de-janeiro-rj",
                destination="sao-jose-dos-campos-sp",
                depart_at=datetime(2026, 11, 23, 21, 0, tzinfo=TZ),
                arrive_at=datetime(2026, 11, 24, 2, 0, tzinfo=TZ),
                price=price,
                seats=seats,
                seats_capped=seats_capped,
                seat_type="semi leito",
                company="Buser",
            )
        ]
    )


def test_no_data():
    settings = Settings()
    rec = evaluate("t1", "ida", [], [], date(2026, 11, 23), date(2026, 11, 5), settings)
    assert rec.level == Level.NO_DATA


def test_last_seats_triggers_only_when_not_capped():
    settings = Settings(min_seats_critical=5)
    rec_crit = evaluate(
        "t1", "ida", [_it(95.0, seats=3, seats_capped=False)], [], date(2026, 11, 23), date(2026, 11, 5), settings
    )
    assert rec_crit.level == Level.LAST_SEATS

    # Se seats_capped=True, não dispara falso alerta de últimas vagas
    settings_high_cap = Settings(min_seats_critical=15)
    rec_capped = evaluate(
        "t1",
        "ida",
        [_it(95.0, seats=13, seats_capped=True)],
        [],
        date(2026, 11, 28),
        date(2026, 11, 5),
        settings_high_cap,
    )
    assert rec_capped.level == Level.WAIT


def test_buy_now_on_excellent_price():
    settings = Settings(target_price_good=80.0, target_price_excellent=70.0)
    rec = evaluate(
        "t1", "ida", [_it(64.90)], [], date(2026, 12, 10), date(2026, 11, 5), settings
    )
    assert rec.level == Level.BUY_NOW


def test_good_vs_buy_now_by_days_or_history():
    settings = Settings(target_price_good=80.0, target_price_excellent=70.0)
    # Preço bom (75) faltando 25 dias e sem histórico -> GOOD
    rec_good = evaluate(
        "t1", "ida", [_it(75.0)], [], date(2026, 11, 30), date(2026, 11, 5), settings
    )
    assert rec_good.level == Level.GOOD

    # Preço bom (75) faltando 10 dias (<= 15) -> BUY_NOW
    rec_buy = evaluate(
        "t1", "ida", [_it(75.0)], [], date(2026, 11, 15), date(2026, 11, 5), settings
    )
    assert rec_buy.level == Level.BUY_NOW

    # Preço bom (75) faltando 25 dias mas na mínima histórica (>=3 amostras) -> BUY_NOW
    history = [(date(2026, 11, 1), 95.0), (date(2026, 11, 2), 90.0), (date(2026, 11, 3), 85.0)]
    rec_hist = evaluate(
        "t1", "ida", [_it(75.0)], history, date(2026, 11, 30), date(2026, 11, 5), settings
    )
    assert rec_hist.level == Level.BUY_NOW


def test_wait_and_normal_and_urgent():
    settings = Settings(target_price_good=80.0, target_price_excellent=70.0)
    # Acima de 80 e faltando 20 dias -> WAIT
    rec_wait = evaluate(
        "t1", "ida", [_it(110.0)], [], date(2026, 11, 25), date(2026, 11, 5), settings
    )
    assert rec_wait.level == Level.WAIT

    # Acima de 80 e faltando 10 dias -> NORMAL
    rec_norm = evaluate(
        "t1", "ida", [_it(110.0)], [], date(2026, 11, 15), date(2026, 11, 5), settings
    )
    assert rec_norm.level == Level.NORMAL

    # Faltando 2 dias (<= 3) -> BUY_NOW
    rec_urg = evaluate(
        "t1", "ida", [_it(110.0)], [], date(2026, 11, 7), date(2026, 11, 5), settings
    )
    assert rec_urg.level == Level.BUY_NOW


def test_compute_stats_7d_ago():
    history = [
        (date(2026, 10, 28), 99.0),
        (date(2026, 10, 29), 92.0),
        (date(2026, 11, 4), 85.0),
        (date(2026, 11, 5), 78.0),
    ]
    st = compute_stats(history, date(2026, 11, 5))
    assert st.samples == 4
    assert st.minimum == 78.0
    assert st.maximum == 99.0
    assert st.price_7d_ago == 92.0
