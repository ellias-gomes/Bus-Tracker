"""Formatação de mensagens e política anti-spam de alertas."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta

from .analyzer import compute_stats
from .config import Settings
from .db import Storage
from .models import Itinerary, Level, Recommendation, Trip
from .utils.text import city_label, fmt_date, fmt_money, today

REPEAT_AFTER = timedelta(hours=72)


def _e(value: str) -> str:
    return html.escape(value or "", quote=False)


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"</?[a-z][^>]*>", "", text))


def fmt_seats(it: Itinerary) -> str:
    if it.seats is None:
        return "?"
    return f"{it.seats}+" if it.seats_capped else str(it.seats)


def fmt_itinerary(it: Itinerary, detailed: bool = True) -> str:
    lines = []
    for seg in it.segments:
        dep, arr = seg.depart_at.strftime("%d/%m %H:%M"), seg.arrive_at.strftime("%d/%m %H:%M")
        if seg.is_estimate:
            lines.append(f"   ↳ <i>{_e(city_label(seg.origin))} → {_e(city_label(seg.destination))}: conexão local estimada ~{fmt_money(seg.price)}</i>")
            continue
        head = f"🚌 {dep} → {arr} | <b>{fmt_money(seg.price)}</b> | {_e(seg.company)} ({_e(seg.seat_type)})"
        lines.append(head)
        if detailed:
            lines.append(f"   🛣️ Trecho: {_e(city_label(seg.origin))} → {_e(city_label(seg.destination))}")
            if seg.boarding_point:
                lines.append(f"   📍 Embarque: {_e(seg.boarding_point)}")
            if seg.alighting_point:
                lines.append(f"   🏁 Desembarque: {_e(seg.alighting_point)}")
            if seg.url:
                lines.append(f"   🔗 Link: <a href=\"{_e(seg.url)}\">{_e(seg.url)}</a>")
    if it.transfers:
        lines.append(f"   🔁 {it.transfers} conexão(ões) • total {fmt_money(it.price)}")
    lines.append(f"   💺 Vagas: {fmt_seats(it)} • via {it.main_segment.provider}")
    return "\n".join(lines)


def fmt_recommendation(trip: Trip, rec: Recommendation, header: str | None = None) -> str:
    leg_origin, leg_dest = (trip.origin, trip.destination) if rec.leg == "ida" else (trip.destination, trip.origin)
    spec = trip.outbound if rec.leg == "ida" else trip.return_leg
    lines = []
    if header:
        lines.append(f"<b>{_e(header)}</b>\n")
    lines.append(f"<b>{rec.level.label}</b>")
    lines.append(f"🧳 {_e(trip.name)} — <b>{rec.leg.upper()}</b> <code>{trip.id}</code>")
    lines.append(f"📍 {_e(city_label(leg_origin))} → {_e(city_label(leg_dest))}")
    if spec:
        lines.append(f"📅 {fmt_date(spec.date)} • faltam {rec.days_left} dia(s)")
        lines.append(f"⏰ Janela: {spec.describe()}")
    lines.append("")
    if rec.best:
        lines.append(fmt_itinerary(rec.best))
    for reason in rec.reasons:
        lines.append(f"💡 {_e(reason)}")
    if rec.alternatives:
        lines.append("\n<b>Outras opções:</b>")
        for alt in rec.alternatives:
            seg = alt.main_segment
            price_info = (
                f"{fmt_money(seg.price)} ônibus ({fmt_money(alt.price)} total)"
                if alt.transfers
                else fmt_money(alt.price)
            )
            link_part = f" — <a href=\"{_e(seg.url)}\">link</a>" if seg.url else ""
            lines.append(
                f"• {seg.depart_at.strftime('%H:%M')} → {seg.arrive_at.strftime('%d/%m %H:%M')} "
                f"{price_info} ({_e(seg.company)}, {_e(seg.seat_type)}, {fmt_seats(alt)} vagas){link_part}"
            )
    return "\n".join(lines)


def booking_buttons(rec: Recommendation) -> list[tuple[str, str]]:
    if not rec.best:
        return []
    urls: list[tuple[str, str]] = []
    for seg in rec.best.segments:
        if not seg.is_estimate and seg.url and all(seg.url != u for _, u in urls):
            orig_short = city_label(seg.origin).split(" - ")[0]
            dest_short = city_label(seg.destination).split(" - ")[0]
            dep_hm = seg.depart_at.strftime("%H:%M")
            label = f"🔗 {seg.provider.capitalize()} ({orig_short} → {dest_short} • {dep_hm})"
            urls.append((label, seg.url))
    return urls


def fmt_trip_summary(trip: Trip) -> str:
    hubs = f" (hubs: {', '.join(city_label(h) for h in trip.hubs)})" if trip.hubs else ""
    lines = [
        f"• <code>{_e(trip.id)}</code> — <b>{_e(trip.name)}</b> [{trip.source.value}]",
        f"  📍 {_e(city_label(trip.origin))} ↔ {_e(city_label(trip.destination))}{_e(hubs)}",
    ]
    if trip.outbound:
        lines.append(f"  ➡️ Ida: {fmt_date(trip.outbound.date)} ({trip.outbound.describe()})")
    if trip.return_leg:
        lines.append(f"  ⬅️ Volta: {fmt_date(trip.return_leg.date)} ({trip.return_leg.describe()})")
    return "\n".join(lines)


def fmt_daily_summary(
    results: list[tuple[Trip, Recommendation]],
    errors: list[str] | None = None,
    bought_map: dict[tuple[str, str], bool] | None = None,
    target_good: float = 80.0,
    target_excellent: float = 70.0,
    header: str | None = None,
) -> str:
    title = header or "📋 <b>Resumo de Monitoramento</b>"
    if not results:
        return f"{title}\nNenhuma viagem ativa no horizonte configurado."

    bought_map = bought_map or {}
    lines = [f"{title}\n"]

    # Agrupa por viagem para calcular o Combo Ida + Volta e Subtotal restante
    by_trip: dict[str, list[tuple[Trip, Recommendation]]] = {}
    for trip, rec in results:
        by_trip.setdefault(trip.id, []).append((trip, rec))

    total_geral_todas = 0.0
    total_restante_todas = 0.0
    tem_algum_preco = False

    for trip_id, pair in by_trip.items():
        trip_name = pair[0][0].name
        trip_total = 0.0
        trip_pending = 0.0
        legs_with_price = 0
        total_legs = len(pair)

        for trip, rec in pair:
            spec = trip.outbound if rec.leg == "ida" else trip.return_leg
            date_str = spec.date.strftime("%d/%m") if spec else "?"
            is_bought = bought_map.get((trip.id, rec.leg), False)
            bought_badge = " [COMPRADO]" if is_bought else ""

            if rec.best:
                dep = rec.best.depart_at.strftime("%H:%M")
                arr = rec.best.arrive_at.strftime("%H:%M")
                price_val = rec.best.price
                trip_total += price_val
                total_geral_todas += price_val
                legs_with_price += 1
                tem_algum_preco = True
                if not is_bought:
                    trip_pending += price_val
                    total_restante_todas += price_val

                lines.append(
                    f"{rec.level.label.split()[0]} <b>{_e(trip.name)}</b> ({rec.leg.upper()} {date_str}, D-{rec.days_left}){bought_badge}: "
                    f"<b>{fmt_money(rec.price)}</b> ({dep}→{arr}, {fmt_seats(rec.best)} vagas) <code>{trip.id}</code>"
                )
            else:
                lines.append(
                    f"⚪ <b>{_e(trip.name)}</b> ({rec.leg.upper()} {date_str}, D-{rec.days_left}){bought_badge}: "
                    f"sem opções na janela <code>{trip.id}</code>"
                )

        # Adiciona o resumo do combo para viagens com 2 trechos (ou mais)
        if total_legs > 1 and legs_with_price > 0:
            combo_target_good = target_good * total_legs
            combo_target_exc = target_excellent * total_legs
            diff_good = trip_total - combo_target_good

            if trip_total <= combo_target_exc:
                meta_tag = f"🟢 Meta Excelente batida (≤ {fmt_money(combo_target_exc)})"
            elif trip_total <= combo_target_good:
                meta_tag = f"🟢 Meta Boa batida (≤ {fmt_money(combo_target_good)})"
            else:
                meta_tag = f"🟠 {fmt_money(diff_good)} acima do alvo bom ({fmt_money(combo_target_good)})"

            pending_info = f" • A Pagar: <b>{fmt_money(trip_pending)}</b>" if trip_pending != trip_total else ""
            lines.append(
                f"   💰 <i>Combo {total_legs} trechos: <b>{fmt_money(trip_total)}</b>{pending_info} ({meta_tag})</i>"
            )

    # Total geral consolidado
    if tem_algum_preco:
        lines.append("")
        lines.append(f"💵 <b>TOTAL GERAL ESTIMADO: {fmt_money(total_geral_todas)}</b>")
        if total_restante_todas != total_geral_todas:
            lines.append(f"💳 <b>SUBTOTAL RESTANTE (A PAGAR): {fmt_money(total_restante_todas)}</b>")

    if errors:
        lines.append("\n⚠️ <i>Avisos de coleta:</i>")
        for err in errors[:3]:
            lines.append(f"• {_e(err)}")
    return "\n".join(lines)


def export_csv_report(
    results: list[tuple[Trip, Recommendation]],
    bought_map: dict[tuple[str, str], bool] | None = None,
    target_good: float | None = None,
    target_excellent: float | None = None,
) -> str:
    """Gera um relatório estruturado em formato CSV para exportação e controle de gastos."""
    bought_map = bought_map or {}
    csv_lines = [
        "ID_VIAGEM;NOME_VIAGEM;TRECHO;ORIGEM;DESTINO;DATA_VIAGEM;STATUS;HORA_SAIDA;HORA_CHEGADA;PRECO_REAIS;ALVO_BOM;ALVO_EXCELENTE;VAGAS;EMPRESA;COMPRADO;LINK"
    ]
    tgt_good_str = f"{target_good:.2f}".replace(".", ",") if target_good is not None else ""
    tgt_exc_str = f"{target_excellent:.2f}".replace(".", ",") if target_excellent is not None else ""

    for trip, rec in results:
        spec = trip.outbound if rec.leg == "ida" else trip.return_leg
        orig = trip.origin if rec.leg == "ida" else trip.destination
        dest = trip.destination if rec.leg == "ida" else trip.origin
        dt_str = spec.date.strftime("%d/%m/%Y") if spec else ""
        is_bought = "SIM" if bought_map.get((trip.id, rec.leg), False) else "NAO"
        if rec.best:
            dep_str = rec.best.depart_at.strftime("%H:%M")
            arr_str = rec.best.arrive_at.strftime("%H:%M")
            pr_str = f"{rec.best.price:.2f}".replace(".", ",")
            vagas = fmt_seats(rec.best)
            empresa = rec.best.main_segment.company
            url = rec.best.main_segment.url or ""
        else:
            dep_str, arr_str, pr_str, vagas, empresa, url = "", "", "", "", "", ""

        csv_lines.append(
            f'"{trip.id}";"{trip.name}";"{rec.leg.upper()}";"{orig}";"{dest}";"{dt_str}";"{rec.level.value}";"{dep_str}";"{arr_str}";"{pr_str}";"{tgt_good_str}";"{tgt_exc_str}";"{vagas}";"{empresa}";"{is_bought}";"{url}"'
        )
    return "\n".join(csv_lines)


def fmt_history(trip: Trip, leg: str, history: list[tuple[date, float]], tz_name: str = "America/Sao_Paulo") -> str:
    header = f"📈 <b>Histórico — {_e(trip.name)} ({leg.upper()})</b> <code>{trip.id}</code>"
    if not history:
        return f"{header}\nAinda não há amostras registradas para este trecho."
    stats = compute_stats(history, today(tz_name))
    lo = stats.minimum or 0.0
    hi = stats.maximum or lo
    span = max(hi - lo, 1.0)
    lines = [
        header,
        f"Amostras: {stats.samples} dia(s) | Mín: <b>{fmt_money(stats.minimum)}</b> | "
        f"Méd: {fmt_money(stats.mean)} | Máx: {fmt_money(stats.maximum)}\n",
    ]
    for d, price in history[-14:]:
        bars = int(round((price - lo) / span * 10))
        bar_str = "█" * max(bars, 1)
        lines.append(f"<code>{d.strftime('%d/%m')}</code>  {fmt_money(price):>9}  <code>{bar_str}</code>")
    return "\n".join(lines)


# ----------------------------------------------------------------- política de alertas


def _milestone_due(settings: Settings, storage: Storage, rec: Recommendation) -> int | None:
    """Menor marco (D-x) já alcançado e ainda não notificado."""
    reached = sorted(m for m in settings.alert_days_before if rec.days_left <= m)
    if not reached:
        return None
    milestone = reached[0]
    return None if storage.milestone_sent(rec.trip_id, rec.leg, milestone) else milestone


def should_alert(settings: Settings, storage: Storage, rec: Recommendation) -> tuple[bool, str, int | None]:
    """Decide se um alerta deve ser enviado. Retorna (enviar, título, marco)."""
    if rec.days_left < 0 or storage.kv_get(f"bought:{rec.trip_id}:{rec.leg}"):
        return False, "", None

    milestone = _milestone_due(settings, storage, rec)
    last = storage.last_alert(rec.trip_id, rec.leg)
    level = rec.level

    if level in (Level.BUY_NOW, Level.LAST_SEATS, Level.GOOD):
        if last is None:
            return True, "Oportunidade de passagem!", milestone
        last_level = Level(last["level"])
        if level.rank > last_level.rank:
            return True, "Situação ficou mais urgente!", milestone
        if rec.price is not None and last["price"] is not None and rec.price <= last["price"] - settings.price_drop_alert:
            return True, f"Preço caiu {fmt_money(last['price'] - rec.price)}!", milestone
        if level != Level.GOOD and datetime.now() - datetime.fromisoformat(last["sent_at"]) > REPEAT_AFTER:
            return True, "Lembrete: compra ainda recomendada", milestone

    if milestone is not None:
        # Lembrete de proximidade: só quando há algo acionável (preço bom, urgência ou falta de opções).
        if level.rank >= Level.GOOD.rank or rec.days_left <= 3 or (level == Level.NO_DATA and rec.days_left <= 7):
            return True, f"Faltam {rec.days_left} dia(s) para a viagem", milestone
        # Marca o marco como "visto" para não reavaliar a cada execução.
        storage.record_alert(rec.trip_id, rec.leg, Level.NO_DATA if level == Level.NO_DATA else level, rec.price, milestone)
    return False, "", None
