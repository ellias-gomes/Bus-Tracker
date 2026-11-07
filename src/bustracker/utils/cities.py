"""Catálogo de cidades rodoviárias brasileiras, resolução inteligente de nomes/números e autocompletar."""

from __future__ import annotations

import re
import unicodedata

# Cidades principais numeradas no menu rápido do terminal (1 a 12)
QUICK_CITIES: list[tuple[str, str]] = [
    ("sao-paulo-sp", "São Paulo - SP"),
    ("rio-de-janeiro-rj", "Rio de Janeiro - RJ"),
    ("belo-horizonte-mg", "Belo Horizonte - MG"),
    ("curitiba-pr", "Curitiba - PR"),
    ("campinas-sp", "Campinas - SP"),
    ("sao-jose-dos-campos-sp", "São José dos Campos - SP"),
    ("resende-rj", "Resende - RJ"),
    ("volta-redonda-rj", "Volta Redonda - RJ"),
    ("niteroi-rj", "Niterói - RJ"),
    ("santos-sp", "Santos - SP"),
    ("aparecida-sp", "Aparecida - SP"),
    ("taubate-sp", "Taubaté - SP"),
]

# Catálogo expandido para autocompletar na Web UI e resolução sem precisar digitar UF ou hífens
CITY_CATALOG: list[tuple[str, str]] = [
    *QUICK_CITIES,
    # Vale do Paraíba, Litoral Norte, Serra da Mantiqueira e Sul Fluminense
    ("jacarei-sp", "Jacarei - SP"),
    ("pindamonhangaba-sp", "Pindamonhangaba - SP"),
    ("lorena-sp", "Lorena - SP"),
    ("cruzeiro-sp", "Cruzeiro - SP"),
    ("cachoeira-paulista-sp", "Cachoeira Paulista - SP"),
    ("campos-do-jordao-sp", "Campos do Jordão - SP"),
    ("caraguatatuba-sp", "Caraguatatuba - SP"),
    ("ubatuba-sp", "Ubatuba - SP"),
    ("sao-sebastiao-sp", "São Sebastião - SP"),
    ("ilhabela-sp", "Ilhabela - SP"),
    ("barra-mansa-rj", "Barra Mansa - RJ"),
    ("itatiaia-rj", "Itatiaia - RJ"),
    ("penedo-rj", "Penedo - RJ"),
    ("paraty-rj", "Paraty - RJ"),
    ("angra-dos-reis-rj", "Angra dos Reis - RJ"),
    ("petropolis-rj", "Petrópolis - RJ"),
    ("teresopolis-rj", "Teresópolis - RJ"),
    ("nova-friburgo-rj", "Nova Friburgo - RJ"),
    ("cabo-frio-rj", "Cabo Frio - RJ"),
    ("macae-rj", "Macaé - RJ"),
    ("campos-dos-goytacazes-rj", "Campos dos Goytacazes - RJ"),
    ("duque-de-caxias-rj", "Duque de Caxias - RJ"),
    ("nova-iguacu-rj", "Nova Iguaçu - RJ"),
    # Grande SP, Interior e Litoral de SP
    ("guarulhos-sp", "Guarulhos - SP"),
    ("santo-andre-sp", "Santo André - SP"),
    ("sao-bernardo-do-campo-sp", "São Bernardo do Campo - SP"),
    ("osasco-sp", "Osasco - SP"),
    ("mogi-das-cruzes-sp", "Mogi das Cruzes - SP"),
    ("santos-sp", "Santos - SP"),
    ("sao-vicente-sp", "São Vicente - SP"),
    ("guaruja-sp", "Guarujá - SP"),
    ("praia-grande-sp", "Praia Grande - SP"),
    ("sorocaba-sp", "Sorocaba - SP"),
    ("jundiai-sp", "Jundiaí - SP"),
    ("piracicaba-sp", "Piracicaba - SP"),
    ("limeira-sp", "Limeira - SP"),
    ("americana-sp", "Americana - SP"),
    ("ribeirao-preto-sp", "Ribeirão Preto - SP"),
    ("sao-jose-do-rio-preto-sp", "São José do Rio Preto - SP"),
    ("sao-carlos-sp", "São Carlos - SP"),
    ("araraquara-sp", "Araraquara - SP"),
    ("bauru-sp", "Bauru - SP"),
    ("marilia-sp", "Marília - SP"),
    ("presidente-prudente-sp", "Presidente Prudente - SP"),
    ("franca-sp", "Franca - SP"),
    ("botucatu-sp", "Botucatu - SP"),
    ("itu-sp", "Itu - SP"),
    ("indaiatuba-sp", "Indaiatuba - SP"),
    ("atibaia-sp", "Atibaia - SP"),
    ("braganca-paulista-sp", "Bragança Paulista - SP"),
    # Minas Gerais, Sul, Centro-Oeste e Nordeste
    ("juiz-de-fora-mg", "Juiz de Fora - MG"),
    ("uberlandia-mg", "Uberlândia - MG"),
    ("uberaba-mg", "Uberaba - MG"),
    ("pouso-alegre-mg", "Pouso Alegre - MG"),
    ("varginha-mg", "Varginha - MG"),
    ("itajuba-mg", "Itajubá - MG"),
    ("pocos-de-caldas-mg", "Poços de Caldas - MG"),
    ("governador-valadares-mg", "Governador Valadares - MG"),
    ("ipatinga-mg", "Ipatinga - MG"),
    ("montes-claros-mg", "Montes Claros - MG"),
    ("ouro-preto-mg", "Ouro Preto - MG"),
    ("curitiba-pr", "Curitiba - PR"),
    ("sao-jose-dos-pinhais-pr", "São José dos Pinhais - PR"),
    ("londrina-pr", "Londrina - PR"),
    ("maringa-pr", "Maringá - PR"),
    ("foz-do-iguacu-pr", "Foz do Iguaçu - PR"),
    ("cascavel-pr", "Cascavel - PR"),
    ("ponta-grossa-pr", "Ponta Grossa - PR"),
    ("florianopolis-sc", "Florianópolis - SC"),
    ("sao-jose-sc", "São José - SC"),
    ("joinville-sc", "Joinville - SC"),
    ("blumenau-sc", "Blumenau - SC"),
    ("balneario-camboriu-sc", "Balneário Camboriú - SC"),
    ("itajai-sc", "Itajaí - SC"),
    ("porto-alegre-rs", "Porto Alegre - RS"),
    ("caxias-do-sul-rs", "Caxias do Sul - RS"),
    ("pelotas-rs", "Pelotas - RS"),
    ("vitoria-es", "Vitória - ES"),
    ("vila-velha-es", "Vila Velha - ES"),
    ("guarapari-es", "Guarapari - ES"),
    ("brasilia-df", "Brasília - DF"),
    ("goiania-go", "Goiânia - GO"),
    ("campo-grande-ms", "Campo Grande - MS"),
    ("cuiaba-mt", "Cuiabá - MT"),
    ("salvador-ba", "Salvador - BA"),
    ("feira-de-santana-ba", "Feira de Santana - BA"),
    ("vitoria-da-conquista-ba", "Vitória da Conquista - BA"),
    ("porto-seguro-ba", "Porto Seguro - BA"),
    ("recife-pe", "Recife - PE"),
    ("fortaleza-ce", "Fortaleza - CE"),
    ("natal-rn", "Natal - RN"),
    ("joao-pessoa-pb", "João Pessoa - PB"),
    ("maceio-al", "Maceió - AL"),
    ("aracaju-se", "Aracaju - SE"),
]

# Apelidos e siglas comuns
ALIASES: dict[str, str] = {
    "rj": "rio-de-janeiro-rj",
    "rio": "rio-de-janeiro-rj",
    "rio-de-janeiro": "rio-de-janeiro-rj",
    "sp": "sao-paulo-sp",
    "sao-paulo": "sao-paulo-sp",
    "sampa": "sao-paulo-sp",
    "sjc": "sao-jose-dos-campos-sp",
    "sao-jose": "sao-jose-dos-campos-sp",
    "sao-jose-dos-campos": "sao-jose-dos-campos-sp",
    "cpv": "cacapava-sp",
    "cacapava": "cacapava-sp",
    "taubate": "taubate-sp",
    "aparecida": "aparecida-sp",
    "guara": "guaratingueta-sp",
    "guaratingueta": "guaratingueta-sp",
    "campinas": "campinas-sp",
    "resende": "resende-rj",
    "vr": "volta-redonda-rj",
    "volta-redonda": "volta-redonda-rj",
    "bh": "belo-horizonte-mg",
    "belo-horizonte": "belo-horizonte-mg",
    "cwb": "curitiba-pr",
    "curitiba": "curitiba-pr",
    "bsb": "brasilia-df",
    "brasilia": "brasilia-df",
}

_SLUG_TO_NAME: dict[str, str] = dict(CITY_CATALOG)


def _norm(value: str) -> str:
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()


def resolve_city(raw: str) -> str:
    """Converte entrada livre do usuário em slug `cidade-uf`.

    Aceita:
    - Número da lista rápida (`"1"` -> `"sao-paulo-sp"`, `"2"` -> `"rio-de-janeiro-rj"`)
    - Nome com ou sem acento, com espaço ou traço (`"sao paulo sp"`, `"São Paulo - SP"`)
    - Nome sem a UF ou abreviações conhecidas (`"sao paulo"`, `"rio"`, `"sp"`, `"bh"`)
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(QUICK_CITIES):
            return QUICK_CITIES[idx][0]
    slug = _norm(raw)
    if slug in ALIASES:
        return ALIASES[slug]
    if slug in _SLUG_TO_NAME:
        return slug

    # Se o usuário digitou o nome da cidade sem o estado (ex.: "sao jose do rio preto"),
    # procura no catálogo uma cidade cujo slug comece com `<slug>-<uf>`.
    for cat_slug, _ in CITY_CATALOG:
        city_part = cat_slug.rsplit("-", 1)[0]
        if slug == city_part:
            return cat_slug
    for cat_slug, _ in CITY_CATALOG:
        if cat_slug.startswith(slug + "-"):
            return cat_slug
    return slug


def resolve_city_list(raw: str | list[str] | None) -> list[str]:
    """Converte `'3, 5'` ou `'sao jose dos campos, taubate'` em `['sao-jose-dos-campos-sp', 'taubate-sp']`."""
    if not raw:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    out: list[str] = []
    for item in items:
        resolved = resolve_city(str(item))
        if resolved and resolved not in out:
            out.append(resolved)
    return out


def search_cities(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Busca cidades no catálogo por nome ou slug (para autocompletar na Web UI)."""
    q = _norm(query)
    if not q:
        return [{"slug": s, "name": n} for s, n in QUICK_CITIES[:limit]]

    starts: list[dict[str, str]] = []
    contains: list[dict[str, str]] = []
    for slug, name in CITY_CATALOG:
        norm_name = _norm(name)
        entry = {"slug": slug, "name": name}
        if slug.startswith(q) or norm_name.startswith(q):
            starts.append(entry)
        elif q in slug or q in norm_name:
            contains.append(entry)
    return (starts + contains)[:limit]


def format_city_label(slug: str) -> str:
    """Retorna o nome bonito com acentos do catálogo se conhecido, ou capitaliza o slug."""
    if slug in _SLUG_TO_NAME:
        return _SLUG_TO_NAME[slug]
    parts = slug.split("-")
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return " ".join(p.capitalize() for p in parts[:-1]) + f" - {parts[-1].upper()}"
    return " ".join(p.capitalize() for p in parts)
