"""Leitura e atualização segura do arquivo `.env` (preservando comentários e formatação)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import PROJECT_ROOT, Settings, load_settings

_KEY_RE = re.compile(r"^\s*([A-Z0-9_]+)\s*=(.*)$")


def ensure_env_file(env_path: Path | None = None) -> Path:
    path = Path(env_path) if env_path else PROJECT_ROOT / ".env"
    if not path.exists():
        example = PROJECT_ROOT / ".env.example"
        if example.exists():
            path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text("", encoding="utf-8")
    return path


def update_env_values(updates: dict[str, str], env_path: Path | None = None) -> Settings:
    """Atualiza chaves no `.env`, reflete em `os.environ` e retorna o `Settings` recarregado."""
    path = ensure_env_file(env_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        m = _KEY_RE.match(line)
        if m and m.group(1) in remaining:
            key = m.group(1)
            val = remaining.pop(key)
            new_lines.append(f"{key}={val}")
        else:
            new_lines.append(line)

    for key, val in remaining.items():
        new_lines.append(f"{key}={val}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for key, val in updates.items():
        os.environ[key] = str(val)
    return load_settings(path)


def editable_settings_dict(settings: Settings) -> dict[str, str]:
    """Retorna um dicionário enxuto com os campos editáveis nas interfaces TUI e Web."""
    return {
        "DEFAULT_ORIGIN": settings.default_origin,
        "DEFAULT_DESTINATION": settings.default_destination,
        "DEFAULT_HUBS": ",".join(settings.default_hubs),
        "DEFAULT_OUTBOUND_DEPART_AFTER": settings.default_outbound_depart_after,
        "DEFAULT_OUTBOUND_DEPART_BEFORE": settings.default_outbound_depart_before,
        "DEFAULT_OUTBOUND_ARRIVE_BEFORE": settings.default_outbound_arrive_before,
        "DEFAULT_RETURN_DEPART_AFTER": settings.default_return_depart_after,
        "DEFAULT_RETURN_DEPART_BEFORE": settings.default_return_depart_before,
        "DEFAULT_RETURN_ARRIVE_BEFORE": settings.default_return_arrive_before,
        "TARGET_PRICE_GOOD": f"{settings.target_price_good:.2f}",
        "TARGET_PRICE_EXCELLENT": f"{settings.target_price_excellent:.2f}",
        "MIN_SEATS_CRITICAL": str(settings.min_seats_critical),
        "CALENDAR_ICS_URL": settings.calendar_ics_url,
        "CALENDAR_KEYWORDS": ",".join(settings.calendar_keywords),
        "ENABLED_PROVIDERS": ",".join(settings.enabled_providers),
        "DAILY_RUN_TIMES": ",".join(settings.daily_run_times),
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
    }
