"""Motor de decisão de compra.

Modelo determinístico (baseado em regras + estatística simples), avaliado nesta ordem:

| # | Condição                                                                          | Nível          |
|---|-----------------------------------------------------------------------------------|----------------|
| 0 | Nenhum itinerário válido na janela                                                | SEM DADOS      |
| 1 | Melhor opção com vagas <= MIN_SEATS_CRITICAL (contagem real, não limitada)        | ÚLTIMAS VAGAS  |
| 2a| Preço <= TARGET_PRICE_EXCELLENT                                                    | COMPRAR AGORA  |
| 2b| Preço <= TARGET_PRICE_GOOD e (faltam <= 15 dias OU mínima histórica OU             | COMPRAR AGORA  |
|   | preço <= média - 0,5·desvio)                                                       |                |
| 2c| Faltam <= 3 dias (não compensa esperar)                                            | COMPRAR AGORA  |
| 2d| Faltam <= 7 dias, >= 3 amostras e preço <= mínima histórica                        | COMPRAR AGORA  |
| 3 | Preço <= TARGET_PRICE_GOOD                                                          | BOM            |
| 4 | Faltam > 15 dias                                                                    | AGUARDAR       |
| 5 | Caso contrário (acima do alvo e janela se fechando)                                 | NORMAL         |

A série histórica usa o menor preço válido por dia de coleta (tabela `leg_snapshots`).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from .config import Settings
from .models import Itinerary, Level, PriceStats, Recommendation
from .utils.text import fmt_money

URGENT_DAYS = 3
CLOSING_DAYS = 7
COMFORT_DAYS = 15
MIN_SAMPLES = 3


def compute_stats(history: list[tuple[date, float]], today: date) -> PriceStats:
    if not history:
        return PriceStats()
    prices = [p for _, p in history]
    stats = PriceStats(
        samples=len(prices),
        mean=round(statistics.fmean(prices), 2),
        stdev=round(statistics.pstdev(prices), 2) if len(prices) >= 2 else 0.0,
        minimum=min(prices),
        maximum=max(prices),
    )
    target = today - timedelta(days=7)
    older = [(d, p) for d, p in history if d <= target]
    if older:
        stats.price_7d_ago = older[-1][1]
    return stats


def evaluate(
    trip_id: str,
    leg: str,
    itineraries: list[Itinerary],
    history: list[tuple[date, float]],
    travel_date: date,
    today: date,
    settings: Settings,
) -> Recommendation:
    days_left = (travel_date - today).days
    stats = compute_stats(history, today)
    best = itineraries[0] if itineraries else None
    alternatives = itineraries[1:4]
    reasons: list[str] = []

    def rec(level: Level) -> Recommendation:
        return Recommendation(trip_id, leg, level, reasons, days_left, best, alternatives, stats)

    if best is None:
        reasons.append("Nenhuma opção encontrada dentro da janela de horários configurada.")
        return rec(Level.NO_DATA)

    price = best.price
    good, excellent = settings.target_price_good, settings.target_price_excellent
    has_history = stats.samples >= MIN_SAMPLES
    at_historic_low = has_history and stats.minimum is not None and price <= stats.minimum
    below_band = (
        has_history
        and stats.mean is not None
        and stats.stdev is not None
        and stats.stdev > 0
        and price <= stats.mean - 0.5 * stats.stdev
    )

    # Contexto (sempre útil na mensagem)
    if has_history and stats.mean:
        diff = (price - stats.mean) / stats.mean * 100
        reasons.append(f"{abs(diff):.0f}% {'abaixo' if diff < 0 else 'acima'} da média de {stats.samples} dias ({fmt_money(stats.mean)}).")
    if stats.price_7d_ago is not None and stats.price_7d_ago != price:
        trend = "caiu" if price < stats.price_7d_ago else "subiu"
        reasons.append(f"Preço {trend} em relação a 7 dias atrás ({fmt_money(stats.price_7d_ago)}).")

    # 1) Últimas vagas
    seats = best.seats
    if seats is not None and not best.seats_capped and seats <= settings.min_seats_critical:
        reasons.insert(0, f"Apenas {seats} vaga(s) na opção mais barata da janela.")
        return rec(Level.LAST_SEATS)

    # 2) Comprar agora
    if price <= excellent:
        reasons.insert(0, f"Preço excelente: {fmt_money(price)} (alvo ≤ {fmt_money(excellent)}).")
        return rec(Level.BUY_NOW)
    if price <= good and (days_left <= COMFORT_DAYS or at_historic_low or below_band):
        why = []
        if days_left <= COMFORT_DAYS:
            why.append(f"faltam {days_left} dias")
        if at_historic_low:
            why.append("mínima do histórico")
        elif below_band:
            why.append("bem abaixo da média")
        reasons.insert(0, f"Preço bom ({fmt_money(price)}) e {', '.join(why)}.")
        return rec(Level.BUY_NOW)
    if days_left <= URGENT_DAYS:
        reasons.insert(0, f"Faltam só {days_left} dia(s): esperar tende a encarecer ou esgotar.")
        return rec(Level.BUY_NOW)
    if days_left <= CLOSING_DAYS and at_historic_low:
        reasons.insert(0, f"Faltam {days_left} dias e o preço está na mínima observada.")
        return rec(Level.BUY_NOW)

    # 3) Bom
    if price <= good:
        reasons.insert(0, f"Preço dentro do alvo ({fmt_money(price)} ≤ {fmt_money(good)}), ainda com folga de datas.")
        return rec(Level.GOOD)

    # 4) Aguardar
    if days_left > COMFORT_DAYS:
        reasons.insert(0, f"Acima do alvo ({fmt_money(good)}) e ainda faltam {days_left} dias.")
        return rec(Level.WAIT)

    # 5) Normal
    reasons.insert(0, f"Acima do alvo ({fmt_money(good)}) com {days_left} dias restantes; considere comprar até D-{CLOSING_DAYS}.")
    return rec(Level.NORMAL)
