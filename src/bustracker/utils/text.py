"""Utilitários de texto, cidades e tempo."""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from .cities import (
    CITY_CATALOG,
    QUICK_CITIES as COMMON_CITIES,
    format_city_label as city_label,
    resolve_city,
    resolve_city_list,
    search_cities,
)


def slugify(value: str) -> str:
    """Converte nome, número ou apelido de cidade em slug `cidade-uf`."""
    return resolve_city(value)


@lru_cache(maxsize=4)
def tz(name: str = "America/Sao_Paulo") -> ZoneInfo:
    return ZoneInfo(name)


def now(tz_name: str = "America/Sao_Paulo") -> datetime:
    return datetime.now(tz(tz_name))


def today(tz_name: str = "America/Sao_Paulo") -> date:
    return now(tz_name).date()


def parse_date(value: str) -> date:
    """Aceita AAAA-MM-DD, DD/MM/AAAA ou DD/MM (assume ano atual ou próximo)."""
    value = value.strip()
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", value):
        d, m, y = value.split("/")
        return date(int(y), int(m), int(d))
    if re.fullmatch(r"\d{1,2}/\d{1,2}", value):
        d_str, m_str = value.split("/")
        cur = today()
        candidate = date(cur.year, int(m_str), int(d_str))
        if candidate < cur:
            candidate = date(cur.year + 1, int(m_str), int(d_str))
        return candidate
    return date.fromisoformat(value)


WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def fmt_date(d: date) -> str:
    return f"{d.strftime('%d/%m/%Y')} ({WEEKDAYS_PT[d.weekday()]})"


def fmt_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


__all__ = [
    "CITY_CATALOG",
    "COMMON_CITIES",
    "WEEKDAYS_PT",
    "city_label",
    "fmt_date",
    "fmt_money",
    "now",
    "parse_date",
    "resolve_city",
    "resolve_city_list",
    "search_cities",
    "slugify",
    "today",
    "tz",
]
