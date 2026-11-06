"""Decodificador do payload `__NUXT_DATA__` (formato *devalue*) usado por sites Nuxt 3.

O Nuxt serializa o estado da página como um array JSON "achatado", onde objetos e listas
referenciam outros elementos pelo índice. Esta função reconstrói a estrutura original.
"""

from __future__ import annotations

import json
import re
from typing import Any

_NUXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NUXT_DATA__"[^>]*>(?P<data>.*?)</script>', re.DOTALL
)

# Marcadores de wrappers reativos do Vue que apenas embrulham outro valor.
_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}

# Índices negativos especiais do devalue.
_SPECIAL = {-1: None, -2: None, -3: float("nan"), -4: float("inf"), -5: float("-inf"), -6: -0.0}


def extract_nuxt_payload(html: str) -> list[Any] | None:
    match = _NUXT_DATA_RE.search(html)
    if not match:
        return None
    return json.loads(match.group("data"))


def decode_devalue(flat: list[Any]) -> Any:
    memo: dict[int, Any] = {}

    def hydrate(index: Any) -> Any:
        if isinstance(index, bool) or not isinstance(index, int):
            return index
        if index < 0:
            return _SPECIAL.get(index)
        if index >= len(flat):
            return index
        if index in memo:
            return memo[index]

        value = flat[index]
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                tag = value[0]
                if tag in _WRAPPERS:
                    result = hydrate(value[1]) if len(value) > 1 else None
                    memo[index] = result
                    return result
                if tag == "Set":
                    result = [hydrate(v) for v in value[1:]]
                    memo[index] = result
                    return result
                if tag == "Map":
                    result_map: dict[Any, Any] = {}
                    memo[index] = result_map
                    items = value[1:]
                    for k, v in zip(items[::2], items[1::2]):
                        result_map[hydrate(k)] = hydrate(v)
                    return result_map
                if tag in {"Date", "BigInt", "RegExp"}:
                    memo[index] = value[1] if len(value) > 1 else None
                    return memo[index]
                if tag in {"null", "NuxtError"}:
                    result = hydrate(value[1]) if len(value) > 1 else None
                    memo[index] = result
                    return result
            out: list[Any] = []
            memo[index] = out
            out.extend(hydrate(v) for v in value)
            return out
        if isinstance(value, dict):
            obj: dict[str, Any] = {}
            memo[index] = obj
            for key, ref in value.items():
                obj[key] = hydrate(ref)
            return obj

        memo[index] = value
        return value

    return hydrate(0)


def parse_nuxt_html(html: str) -> Any:
    flat = extract_nuxt_payload(html)
    if flat is None:
        return None
    return decode_devalue(flat)
