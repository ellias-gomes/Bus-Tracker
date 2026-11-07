"""Carregamento e validação das configurações a partir de variáveis de ambiente (.env)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from dotenv import load_dotenv

from .utils.text import resolve_city, resolve_city_list

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TG_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
_TG_PLACEHOLDERS = {
    "seu_bot_token_aqui",
    "seu_chat_id_aqui",
    "your_bot_token",
    "your_chat_id",
    "none",
    "null",
}


def _clean_tg_token(raw: str) -> str:
    val = (raw or "").strip().strip("\"'").strip()
    if val.lower() in _TG_PLACEHOLDERS:
        return ""
    if val.lower().startswith("bot") and ":" in val and val[3:4].isdigit():
        val = val[3:]
    return val


def _clean_tg_chat_id(raw: str) -> str:
    val = (raw or "").strip().strip("\"'").strip()
    if val.lower() in _TG_PLACEHOLDERS:
        return ""
    return val


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Variável {name} deve ser numérica (recebido: {raw!r})") from exc


def _int(name: str, default: int) -> int:
    raw = _str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Variável {name} deve ser inteira (recebido: {raw!r})") from exc


def _bool(name: str, default: bool) -> bool:
    raw = _str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "sim", "on"}


def _list(name: str, default: str = "") -> list[str]:
    raw = _str(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_hhmm(value: str | None) -> time | None:
    """Converte horários flexíveis ('22', '22h', '22h30', '22:30', '7h15') em `datetime.time`."""
    if not value:
        return None
    s = value.strip().lower()
    if not s:
        return None
    try:
        # Formato 22:30 ou 22h30 ou 22h
        m = re.fullmatch(r"(\d{1,2})\s*[:h]\s*(\d{1,2})?\s*m?", s)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
            return time(hour, minute)
        # Apenas hora: "22" ou "7"
        if re.fullmatch(r"\d{1,2}", s):
            return time(int(s), 0)
        # 4 dígitos: "2230" ou "0715"
        if re.fullmatch(r"\d{4}", s):
            return time(int(s[:2]), int(s[2:]))
    except ValueError as exc:
        raise ValueError(f"Horário fora da faixa 00:00–23:59: {value!r}") from exc
    raise ValueError(f"Horário inválido (use ex.: 22, 22h, 22h30 ou 22:30): {value!r}")


@dataclass(frozen=True)
class LocalConnection:
    """Conexão local estimada entre duas cidades próximas (ex.: ônibus urbano/intermunicipal, app)."""

    city_a: str
    city_b: str
    cost: float
    minutes: int

    def matches(self, a: str, b: str) -> bool:
        return {a, b} == {self.city_a, self.city_b}


def _parse_local_connections(raw: str) -> list[LocalConnection]:
    """Formato: `cidade-a|cidade-b|custo|minutos;cidade-c|cidade-d|custo|minutos`."""
    connections: list[LocalConnection] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) != 4:
            raise ValueError(
                f"LOCAL_CONNECTIONS inválido: {chunk!r}. Use cidade-a|cidade-b|custo|minutos"
            )
        connections.append(
            LocalConnection(
                resolve_city(parts[0]),
                resolve_city(parts[1]),
                float(parts[2].replace(",", ".")),
                int(parts[3]),
            )
        )
    return connections


DEFAULT_LOCAL_CONNECTIONS = (
    "campinas-sp|jundiai-sp|15.00|30;"
    "aparecida-sp|guaratingueta-sp|6.50|15"
)


@dataclass
class Settings:
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Fontes de viagens
    calendar_ics_url: str = ""
    calendar_keywords: list[str] = field(default_factory=list)
    local_trips_file: Path = PROJECT_ROOT / "data" / "viagens.json"

    # Rota padrão (usada por eventos de calendário e comandos rápidos)
    default_origin: str = "sao-paulo-sp"
    default_destination: str = "rio-de-janeiro-rj"
    default_hubs: list[str] = field(default_factory=list)
    event_outbound_day_offset: int = -1
    event_return_day_offset: int = 0
    default_outbound_depart_after: str = ""
    default_outbound_depart_before: str = "22:00"
    default_outbound_arrive_before: str = ""
    default_return_depart_after: str = "20:00"
    default_return_depart_before: str = "23:59"
    default_return_arrive_before: str = "07:15"
    default_return_arrive_day_offset: int = 1

    # Roteamento
    max_transfers: int = 1
    min_connection_minutes: int = 30
    local_connections: list[LocalConnection] = field(
        default_factory=lambda: _parse_local_connections(DEFAULT_LOCAL_CONNECTIONS)
    )

    # Preço / decisão
    target_price_good: float = 80.0
    target_price_excellent: float = 70.0
    alert_days_before: list[int] = field(default_factory=lambda: [30, 15, 7, 3, 1])
    min_seats_critical: int = 5
    history_window_days: int = 30
    price_drop_alert: float = 5.0
    monitor_horizon_days: int = 120

    # Provedores
    enabled_providers: list[str] = field(default_factory=lambda: ["buser"])
    request_delay_seconds: float = 2.0
    request_timeout_seconds: float = 25.0

    # Agendamento
    daily_run_times: list[str] = field(default_factory=lambda: ["07:30"])
    check_interval_hours: float = 0.0
    daily_summary: bool = True

    # Infra
    database_path: Path = PROJECT_ROOT / "data" / "bustracker.db"
    log_level: str = "INFO"
    timezone: str = "America/Sao_Paulo"

    @property
    def telegram_enabled(self) -> bool:
        token = _clean_tg_token(self.telegram_bot_token)
        chat_id = _clean_tg_chat_id(self.telegram_chat_id)
        return bool(token and chat_id and _TG_TOKEN_RE.match(token))

    def local_connection(self, a: str, b: str) -> LocalConnection | None:
        for conn in self.local_connections:
            if conn.matches(a, b):
                return conn
        return None

    def validate(self) -> None:
        if self.target_price_excellent > self.target_price_good:
            raise ValueError("TARGET_PRICE_EXCELLENT não pode ser maior que TARGET_PRICE_GOOD")
        if self.max_transfers not in (0, 1):
            raise ValueError("MAX_TRANSFERS suporta apenas 0 ou 1 nesta versão")
        for t in self.daily_run_times:
            parse_hhmm(t)
        for t in (
            self.default_outbound_depart_after,
            self.default_outbound_depart_before,
            self.default_outbound_arrive_before,
            self.default_return_depart_after,
            self.default_return_depart_before,
            self.default_return_arrive_before,
        ):
            parse_hhmm(t)


def _resolve_path(raw: str, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _database_path(raw: str, default: Path) -> Path:
    # Aceita tanto caminho simples quanto o formato `sqlite:///caminho.db`.
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///"):]
    return _resolve_path(raw, default)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Lê o `.env` (criando-o a partir do `.env.example` se não existir) e monta o `Settings`."""
    target_env = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if env_file is None and not target_env.exists():
        example = PROJECT_ROOT / ".env.example"
        if example.exists():
            target_env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    load_dotenv(target_env, override=False)
    defaults = Settings()

    raw_origin = _str("DEFAULT_ORIGIN", defaults.default_origin)
    raw_dest = _str("DEFAULT_DESTINATION", defaults.default_destination)
    raw_hubs = _str("DEFAULT_HUBS", ",".join(defaults.default_hubs))
    raw_local_conn = _str("LOCAL_CONNECTIONS", DEFAULT_LOCAL_CONNECTIONS)

    settings = Settings(
        telegram_bot_token=_clean_tg_token(_str("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=_clean_tg_chat_id(_str("TELEGRAM_CHAT_ID")),
        calendar_ics_url=_str("CALENDAR_ICS_URL"),
        calendar_keywords=[k.lower() for k in _list("CALENDAR_KEYWORDS")],
        local_trips_file=_resolve_path(_str("LOCAL_TRIPS_FILE"), defaults.local_trips_file),
        default_origin=resolve_city(raw_origin) if raw_origin else defaults.default_origin,
        default_destination=resolve_city(raw_dest) if raw_dest else defaults.default_destination,
        default_hubs=resolve_city_list(raw_hubs) if raw_hubs else list(defaults.default_hubs),
        event_outbound_day_offset=_int("EVENT_OUTBOUND_DAY_OFFSET", -1),
        event_return_day_offset=_int("EVENT_RETURN_DAY_OFFSET", 0),
        default_outbound_depart_after=_str("DEFAULT_OUTBOUND_DEPART_AFTER"),
        default_outbound_depart_before=(
            _str("DEFAULT_OUTBOUND_DEPART_BEFORE")
            or _str("MAX_DEPARTURE_TIME")
            or _str("MAX_DEPARTURE_TIME_RIO")
            or defaults.default_outbound_depart_before
        ),
        default_outbound_arrive_before=_str("DEFAULT_OUTBOUND_ARRIVE_BEFORE"),
        default_return_depart_after=_str("DEFAULT_RETURN_DEPART_AFTER", defaults.default_return_depart_after),
        default_return_depart_before=_str("DEFAULT_RETURN_DEPART_BEFORE", defaults.default_return_depart_before),
        default_return_arrive_before=(
            _str("DEFAULT_RETURN_ARRIVE_BEFORE")
            or _str("MAX_ARRIVAL_TIME")
            or _str("MAX_ARRIVAL_TIME_RIO")
            or defaults.default_return_arrive_before
        ),
        default_return_arrive_day_offset=_int("DEFAULT_RETURN_ARRIVE_DAY_OFFSET", 1),
        max_transfers=_int("MAX_TRANSFERS", 1),
        min_connection_minutes=_int("MIN_CONNECTION_MINUTES", 30),
        local_connections=_parse_local_connections(raw_local_conn),
        target_price_good=_float("TARGET_PRICE_GOOD", 80.0),
        target_price_excellent=_float("TARGET_PRICE_EXCELLENT", 70.0),
        alert_days_before=[int(x) for x in _list("ALERT_DAYS_BEFORE", "30,15,7,3,1")],
        min_seats_critical=_int("MIN_SEATS_CRITICAL", 5),
        history_window_days=_int("HISTORY_WINDOW_DAYS", 30),
        price_drop_alert=_float("PRICE_DROP_ALERT", 5.0),
        monitor_horizon_days=_int("MONITOR_HORIZON_DAYS", 120),
        enabled_providers=[p.lower() for p in _list("ENABLED_PROVIDERS", "buser")],
        request_delay_seconds=_float("REQUEST_DELAY_SECONDS", 2.0),
        request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 25.0),
        daily_run_times=_list("DAILY_RUN_TIMES") or _list("DAILY_RUN_TIME", "07:30"),
        check_interval_hours=_float("CHECK_INTERVAL_HOURS", 0.0),
        daily_summary=_bool("DAILY_SUMMARY", True),
        database_path=_database_path(_str("DATABASE_URL"), defaults.database_path),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        timezone=_str("TZ_NAME", "America/Sao_Paulo"),
    )
    settings.validate()
    return settings
