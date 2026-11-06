"""Fontes de viagens: arquivo JSON local, calendário iCal (.ics) e viagens derivadas de eventos."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from .config import Settings, parse_hhmm
from .models import LegSpec, Trip, TripSource
from .utils.text import today

log = logging.getLogger(__name__)


def trip_from_event(
    settings: Settings,
    event_date: date,
    *,
    trip_id: str,
    name: str,
    source: TripSource,
    origin: str | None = None,
    destination: str | None = None,
    hubs: list[str] | None = None,
    one_way: bool = False,
) -> Trip:
    """Cria uma viagem a partir da data de um compromisso, usando os padrões do `.env`.

    Ida em `event_date + EVENT_OUTBOUND_DAY_OFFSET` e volta em `event_date + EVENT_RETURN_DAY_OFFSET`,
    com as janelas DEFAULT_OUTBOUND_* / DEFAULT_RETURN_*.
    """
    origin = origin or settings.default_origin
    destination = destination or settings.default_destination
    if not origin or not destination:
        raise ValueError("Defina DEFAULT_ORIGIN e DEFAULT_DESTINATION no .env ou informe origem/destino.")

    outbound = LegSpec(
        date=event_date + timedelta(days=settings.event_outbound_day_offset),
        depart_after=parse_hhmm(settings.default_outbound_depart_after),
        depart_before=parse_hhmm(settings.default_outbound_depart_before),
        arrive_before=parse_hhmm(settings.default_outbound_arrive_before),
        arrive_day_offset=-settings.event_outbound_day_offset if settings.default_outbound_arrive_before else 0,
    )
    return_leg = None
    if not one_way:
        return_leg = LegSpec(
            date=event_date + timedelta(days=settings.event_return_day_offset),
            depart_after=parse_hhmm(settings.default_return_depart_after),
            depart_before=parse_hhmm(settings.default_return_depart_before),
            arrive_before=parse_hhmm(settings.default_return_arrive_before),
            arrive_day_offset=settings.default_return_arrive_day_offset,
        )
    return Trip(
        id=trip_id,
        name=name,
        origin=origin,
        destination=destination,
        outbound=outbound,
        return_leg=return_leg,
        hubs=hubs if hubs is not None else list(settings.default_hubs),
        source=source,
    )


def trip_from_dates(
    settings: Settings,
    outbound_date: date,
    return_date: date | None = None,
    *,
    trip_id: str,
    name: str,
    source: TripSource,
    origin: str | None = None,
    destination: str | None = None,
    hubs: list[str] | None = None,
    outbound_depart_after: str | None = None,
    outbound_depart_before: str | None = None,
    outbound_arrive_before: str | None = None,
    return_depart_after: str | None = None,
    return_depart_before: str | None = None,
    return_arrive_before: str | None = None,
    return_arrive_day_offset: int | None = None,
) -> Trip:
    """Cria uma viagem informando diretamente a data de ida (e opcionalmente a de volta)."""
    origin = origin or settings.default_origin
    destination = destination or settings.default_destination
    if not origin or not destination:
        raise ValueError("Defina DEFAULT_ORIGIN e DEFAULT_DESTINATION no .env ou informe origem/destino.")

    out_arr = outbound_arrive_before if outbound_arrive_before is not None else settings.default_outbound_arrive_before
    outbound = LegSpec(
        date=outbound_date,
        depart_after=parse_hhmm(
            outbound_depart_after if outbound_depart_after is not None else settings.default_outbound_depart_after
        ),
        depart_before=parse_hhmm(
            outbound_depart_before if outbound_depart_before is not None else settings.default_outbound_depart_before
        ),
        arrive_before=parse_hhmm(out_arr),
        arrive_day_offset=-settings.event_outbound_day_offset if out_arr else 0,
    )
    return_leg = None
    if return_date is not None:
        ret_arr = return_arrive_before if return_arrive_before is not None else settings.default_return_arrive_before
        return_leg = LegSpec(
            date=return_date,
            depart_after=parse_hhmm(
                return_depart_after if return_depart_after is not None else settings.default_return_depart_after
            ),
            depart_before=parse_hhmm(
                return_depart_before if return_depart_before is not None else settings.default_return_depart_before
            ),
            arrive_before=parse_hhmm(ret_arr),
            arrive_day_offset=(
                return_arrive_day_offset
                if return_arrive_day_offset is not None
                else settings.default_return_arrive_day_offset
            ),
        )
    return Trip(
        id=trip_id,
        name=name,
        origin=origin,
        destination=destination,
        outbound=outbound,
        return_leg=return_leg,
        hubs=hubs if hubs is not None else list(settings.default_hubs),
        source=source,
    )


# --------------------------------------------------------------------------- JSON


def _extract_hubs(item: dict) -> list[str] | None:
    if "hubs" in item and item["hubs"] is not None:
        val = item["hubs"]
        return [val] if isinstance(val, str) else list(val)
    if "hub_alternativo" in item and item["hub_alternativo"]:
        val = item["hub_alternativo"]
        return [val] if isinstance(val, str) else list(val)
    return None


def load_json_trips(settings: Settings) -> list[Trip] | None:
    """Lê `LOCAL_TRIPS_FILE`. Retorna None se o arquivo não existir (fonte desativada)."""
    path: Path = settings.local_trips_file
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido em {path}: {exc}") from exc

    items = raw.get("viagens", raw) if isinstance(raw, dict) else raw
    trips: list[Trip] = []
    for item in items:
        raw_id = str(item["id"])
        trip_id = raw_id if raw_id.startswith("json-") else f"json-{raw_id}"
        if item.get("active") is False:
            continue
        name = item.get("name") or item.get("nome") or raw_id
        origin = item.get("origin") or item.get("origem")
        destination = item.get("destination") or item.get("destino")
        hubs = _extract_hubs(item)
        event_date_raw = item.get("event_date") or item.get("data_evento")
        outbound_date_raw = item.get("data_ida") or item.get("outbound_date")
        return_date_raw = item.get("data_volta") or item.get("return_date")

        if event_date_raw:
            trips.append(
                trip_from_event(
                    settings,
                    date.fromisoformat(event_date_raw),
                    trip_id=trip_id,
                    name=name,
                    source=TripSource.JSON,
                    origin=origin,
                    destination=destination,
                    hubs=hubs,
                    one_way=bool(item.get("one_way") or item.get("somente_ida")),
                )
            )
        elif outbound_date_raw:
            trips.append(
                trip_from_dates(
                    settings,
                    date.fromisoformat(outbound_date_raw),
                    date.fromisoformat(return_date_raw) if return_date_raw else None,
                    trip_id=trip_id,
                    name=name,
                    source=TripSource.JSON,
                    origin=origin,
                    destination=destination,
                    hubs=hubs,
                    outbound_depart_after=item.get("inicio_partida_ida") or item.get("outbound_depart_after"),
                    outbound_depart_before=item.get("limite_partida_ida") or item.get("outbound_depart_before"),
                    outbound_arrive_before=item.get("limite_chegada_ida") or item.get("outbound_arrive_before"),
                    return_depart_after=item.get("inicio_partida_volta") or item.get("return_depart_after"),
                    return_depart_before=item.get("limite_partida_volta") or item.get("return_depart_before"),
                    return_arrive_before=item.get("limite_chegada_volta") or item.get("return_arrive_before"),
                )
            )
        else:
            data = dict(item, id=trip_id, name=name)
            if origin:
                data["origin"] = origin
            if destination:
                data["destination"] = destination
            if hubs is not None:
                data["hubs"] = hubs
            else:
                data.setdefault("hubs", settings.default_hubs)
            trips.append(Trip.from_dict(data, source=TripSource.JSON))
    return trips


def import_calendar_file(
    file_path_or_content: str | Path | bytes,
    settings: Settings,
    filename_hint: str = "",
) -> list[Trip]:
    """Importa viagens diretamente de um arquivo de calendário (.ics ou .json).
    
    Aceita caminho do arquivo (Path/str) ou os bytes/texto do conteúdo diretamente.
    Retorna a lista de objetos `Trip` parseados prontos para persistência.
    """
    hint = str(filename_hint or file_path_or_content).lower()
    
    # Se for caminho de arquivo existente em disco
    if isinstance(file_path_or_content, (str, Path)):
        p = Path(file_path_or_content).expanduser()
        if p.exists() and p.is_file():
            hint = p.name.lower()
            if hint.endswith(".json"):
                # Cria uma cópia temporária de settings com local_trips_file apontando para este arquivo
                from dataclasses import replace
                custom_settings = replace(settings, local_trips_file=p)
                trips = load_json_trips(custom_settings)
                return trips or []
            else:
                return parse_ics(p.read_bytes(), settings)
    
    # Se for conteúdo bruto em bytes ou string
    raw_bytes = file_path_or_content if isinstance(file_path_or_content, bytes) else str(file_path_or_content).encode("utf-8")
    
    # Tenta detectar se é JSON
    stripped = raw_bytes.strip()
    if hint.endswith(".json") or stripped.startswith((b"{", b"[")):
        try:
            import tempfile
            with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = Path(tmp.name)
            try:
                from dataclasses import replace
                custom_settings = replace(settings, local_trips_file=tmp_path)
                trips = load_json_trips(custom_settings)
                return trips or []
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        except Exception as exc:
            raise ValueError(f"Falha ao processar arquivo JSON: {exc}") from exc

    # Caso contrário, trata como .ics (iCalendar)
    return parse_ics(raw_bytes, settings)

_OVERRIDE_RE = re.compile(r"^\s*(origem|destino|hubs)\s*[:=]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _event_overrides(description: str) -> dict[str, str]:
    """Permite sobrescrever a rota pela descrição do evento: `destino: sao-paulo-sp`."""
    return {m.group(1).lower(): m.group(2) for m in _OVERRIDE_RE.finditer(description or "")}


def parse_ics(content: bytes | str, settings: Settings) -> list[Trip]:
    from icalendar import Calendar  # import tardio: só carrega se a fonte estiver em uso

    cal = Calendar.from_ical(content)
    horizon = today(settings.timezone) + timedelta(days=settings.monitor_horizon_days)
    start_limit = today(settings.timezone) - timedelta(days=1)
    trips: list[Trip] = []

    for event in cal.walk("VEVENT"):
        summary = str(event.get("SUMMARY", "")).strip()
        if settings.calendar_keywords and not any(k in summary.lower() for k in settings.calendar_keywords):
            continue
        dtstart = event.get("DTSTART")
        if dtstart is None:
            continue
        value = dtstart.dt
        event_date = value.date() if isinstance(value, datetime) else value
        if not (start_limit <= event_date <= horizon):
            continue

        uid = str(event.get("UID", f"{summary}-{event_date}"))
        digest = hashlib.sha1(f"{uid}-{event_date}".encode()).hexdigest()[:10]
        overrides = _event_overrides(str(event.get("DESCRIPTION", "")))
        hubs = [h.strip() for h in overrides["hubs"].split(",")] if "hubs" in overrides else None
        try:
            trips.append(
                trip_from_event(
                    settings,
                    event_date,
                    trip_id=f"ics-{digest}",
                    name=summary or "Evento do calendário",
                    source=TripSource.ICS,
                    origin=overrides.get("origem"),
                    destination=overrides.get("destino"),
                    hubs=hubs,
                )
            )
        except ValueError as exc:
            log.warning("Evento '%s' ignorado: %s", summary, exc)
    return trips


async def load_ics_trips(settings: Settings) -> list[Trip] | None:
    """Baixa/lê o calendário. Retorna None se não configurado; levanta exceção em falha de leitura."""
    source = settings.calendar_ics_url
    if not source:
        return None
    if source.startswith(("http://", "https://", "webcal://")):
        url = source.replace("webcal://", "https://", 1)
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content: bytes = resp.content
    else:
        content = Path(source).expanduser().read_bytes()
    return parse_ics(content, settings)
