"""Modelos de domínio do BusTracker."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any

from .config import parse_hhmm
from .utils.text import resolve_city


def _t(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


@dataclass
class LegSpec:
    """Restrições de um trecho (ida ou volta).

    - `date`: data de partida de referência.
    - `depart_after` / `depart_before`: janela de embarque. Se `depart_before` < `depart_after`,
      a janela atravessa a meia-noite (ex.: 23:00 -> 02:00) e o dia seguinte também é pesquisado.
    - `arrive_before` + `arrive_day_offset`: horário limite de chegada (relativo a `date`).
    """

    date: date
    depart_after: time | None = None
    depart_before: time | None = None
    arrive_before: time | None = None
    arrive_day_offset: int = 0

    @property
    def crosses_midnight(self) -> bool:
        return bool(
            self.depart_after and self.depart_before and self.depart_before < self.depart_after
        )

    def search_dates(self) -> list[date]:
        dates = [self.date]
        if self.crosses_midnight:
            dates.append(self.date + timedelta(days=1))
        return dates

    def window(self, tzinfo) -> tuple[datetime, datetime]:
        start = datetime.combine(self.date, self.depart_after or time(0, 0), tzinfo)
        if self.depart_before:
            end_day = self.date + timedelta(days=1) if self.crosses_midnight else self.date
            end = datetime.combine(end_day, self.depart_before, tzinfo)
        else:
            end = datetime.combine(self.date, time(23, 59, 59), tzinfo)
        return start, end

    def arrival_deadline(self, tzinfo) -> datetime | None:
        if not self.arrive_before:
            return None
        day = self.date + timedelta(days=self.arrive_day_offset)
        return datetime.combine(day, self.arrive_before, tzinfo)

    def accepts(self, depart_at: datetime, arrive_at: datetime) -> bool:
        tzinfo = depart_at.tzinfo
        start, end = self.window(tzinfo)
        if not (start <= depart_at <= end):
            return False
        deadline = self.arrival_deadline(tzinfo)
        if deadline and arrive_at > deadline:
            return False
        return True

    def describe(self) -> str:
        parts = []
        if self.depart_after or self.depart_before:
            parts.append(f"saída {_t(self.depart_after) or '00:00'}–{_t(self.depart_before) or '23:59'}")
        if self.arrive_before:
            suffix = f" (D+{self.arrive_day_offset})" if self.arrive_day_offset else ""
            parts.append(f"chegada até {_t(self.arrive_before)}{suffix}")
        return ", ".join(parts) or "qualquer horário"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "depart_after": _t(self.depart_after),
            "depart_before": _t(self.depart_before),
            "arrive_before": _t(self.arrive_before),
            "arrive_day_offset": self.arrive_day_offset,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LegSpec":
        return cls(
            date=date.fromisoformat(data["date"]),
            depart_after=parse_hhmm(data.get("depart_after")),
            depart_before=parse_hhmm(data.get("depart_before")),
            arrive_before=parse_hhmm(data.get("arrive_before")),
            arrive_day_offset=int(data.get("arrive_day_offset") or 0),
        )


class TripSource(str, Enum):
    JSON = "json"
    ICS = "ics"
    MANUAL = "manual"  # Telegram ou CLI


@dataclass
class Trip:
    """Uma viagem monitorada (ida e, opcionalmente, volta)."""

    id: str
    name: str
    origin: str
    destination: str
    outbound: LegSpec | None
    return_leg: LegSpec | None = None
    hubs: list[str] = field(default_factory=list)
    source: TripSource = TripSource.MANUAL
    active: bool = True

    def __post_init__(self) -> None:
        self.origin = resolve_city(self.origin)
        self.destination = resolve_city(self.destination)
        self.hubs = [resolve_city(h) for h in self.hubs if h]

    @staticmethod
    def new_id(prefix: str = "m") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:6]}"

    def legs(self) -> list[tuple[str, str, str, LegSpec]]:
        """Retorna [(nome_leg, origem, destino, spec)]. Na volta, origem/destino são invertidos."""
        out = []
        if self.outbound:
            out.append(("ida", self.origin, self.destination, self.outbound))
        if self.return_leg:
            out.append(("volta", self.destination, self.origin, self.return_leg))
        return out

    def first_date(self) -> date | None:
        dates = [spec.date for _, _, _, spec in self.legs()]
        return min(dates) if dates else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "origin": self.origin,
            "destination": self.destination,
            "outbound": self.outbound.to_dict() if self.outbound else None,
            "return": self.return_leg.to_dict() if self.return_leg else None,
            "hubs": self.hubs,
            "source": self.source.value,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: TripSource | None = None) -> "Trip":
        return cls(
            id=str(data["id"]),
            name=data.get("name") or str(data["id"]),
            origin=data["origin"],
            destination=data["destination"],
            outbound=LegSpec.from_dict(data["outbound"]) if data.get("outbound") else None,
            return_leg=LegSpec.from_dict(data["return"]) if data.get("return") else None,
            hubs=list(data.get("hubs") or []),
            source=source or TripSource(data.get("source", TripSource.MANUAL.value)),
            active=bool(data.get("active", True)),
        )


@dataclass
class Offer:
    """Um segmento de viagem ofertado por um provedor (ou uma conexão local estimada)."""

    provider: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    price: float
    seats: int | None = None
    seats_capped: bool = False  # True quando o provedor só informa "N ou mais" vagas
    seat_type: str = ""
    company: str = ""
    boarding_point: str = ""
    alighting_point: str = ""
    url: str = ""
    is_estimate: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depart_at"] = self.depart_at.isoformat()
        data["arrive_at"] = self.arrive_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Offer":
        data = dict(data)
        data["depart_at"] = datetime.fromisoformat(data["depart_at"])
        data["arrive_at"] = datetime.fromisoformat(data["arrive_at"])
        return cls(**data)


@dataclass
class Itinerary:
    """Sequência de segmentos que leva da origem ao destino de um trecho."""

    segments: list[Offer]

    @property
    def price(self) -> float:
        return round(sum(s.price for s in self.segments), 2)

    @property
    def depart_at(self) -> datetime:
        return self.segments[0].depart_at

    @property
    def arrive_at(self) -> datetime:
        return self.segments[-1].arrive_at

    @property
    def transfers(self) -> int:
        return len(self.segments) - 1

    @property
    def seats(self) -> int | None:
        values = [s.seats for s in self.segments if not s.is_estimate and s.seats is not None]
        return min(values) if values else None

    @property
    def seats_capped(self) -> bool:
        real = [s for s in self.segments if not s.is_estimate and s.seats is not None]
        if not real:
            return False
        lowest = min(real, key=lambda s: s.seats)  # type: ignore[arg-type, return-value]
        return lowest.seats_capped

    @property
    def main_segment(self) -> Offer:
        """Segmento principal (o primeiro que não é estimativa local)."""
        for seg in self.segments:
            if not seg.is_estimate:
                return seg
        return self.segments[0]

    @property
    def duration(self) -> timedelta:
        return self.arrive_at - self.depart_at

    def key(self) -> str:
        return " + ".join(
            f"{s.provider}:{s.origin}>{s.destination}@{s.depart_at.isoformat()}:{s.seat_type}"
            for s in self.segments
        )

    def to_dict(self) -> dict[str, Any]:
        return {"segments": [s.to_dict() for s in self.segments], "price": self.price}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Itinerary":
        return cls([Offer.from_dict(s) for s in data["segments"]])


class Level(str, Enum):
    """Classificação do motor de decisão, em ordem crescente de urgência."""

    NO_DATA = "sem_dados"
    WAIT = "aguardar"
    NORMAL = "normal"
    GOOD = "bom"
    BUY_NOW = "comprar_agora"
    LAST_SEATS = "ultimas_vagas"

    @property
    def rank(self) -> int:
        return list(Level).index(self)

    @property
    def label(self) -> str:
        return {
            Level.NO_DATA: "⚪ SEM OPÇÕES NA JANELA",
            Level.WAIT: "🟡 AGUARDAR / MONITORAR",
            Level.NORMAL: "🟠 PREÇO ACIMA DO ALVO",
            Level.GOOD: "🟢 PREÇO BOM",
            Level.BUY_NOW: "🟢 COMPRA RECOMENDADA",
            Level.LAST_SEATS: "🔴 ÚLTIMAS VAGAS",
        }[self]


@dataclass
class PriceStats:
    samples: int = 0
    mean: float | None = None
    stdev: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    price_7d_ago: float | None = None


@dataclass
class Recommendation:
    trip_id: str
    leg: str
    level: Level
    reasons: list[str]
    days_left: int
    best: Itinerary | None
    alternatives: list[Itinerary]
    stats: PriceStats

    @property
    def price(self) -> float | None:
        return self.best.price if self.best else None

    @property
    def seats(self) -> int | None:
        return self.best.seats if self.best else None
