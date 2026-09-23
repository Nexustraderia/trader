import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": "ECB OR Federal Reserve OR Bank of Japan interest rates inflation forex", "hl": "en-US", "gl": "US", "ceid": "US:en"}),
]
TRADING_ECONOMICS_URL = "https://api.tradingeconomics.com/calendar"
_CALENDAR_CACHE = {"checked_at": None, "events": []}
HIGH_IMPACT_TERMS = (
    "interest rate", "rate decision", "monetary policy", "cpi", "consumer price index",
    "ppi", "nonfarm payroll", "nfp", "fomc", "federal reserve", "ecb", "boj",
    "bank of japan", "bank of england", "rba", "bank of canada", "gdp",
)
PAIR_TERMS = {
    "EUR/JPY": ("euro", "ecb", "europe", "japan", "boj", "yen"),
    "EUR/USD": ("euro", "ecb", "europe", "fed", "fomc", "dollar", "usd"),
    "USD/JPY": ("fed", "fomc", "dollar", "usd", "japan", "boj", "yen"),
    "GBP/USD": ("boe", "bank of england", "britain", "uk", "fed", "dollar", "usd"),
    "GBP/JPY": ("boe", "bank of england", "britain", "uk", "japan", "boj", "yen"),
    "AUD/USD": ("rba", "australia", "australian", "fed", "fomc", "dollar", "usd"),
    "USD/CAD": ("bank of canada", "canada", "oil", "fed", "fomc", "dollar", "usd"),
}
PAIR_COUNTRIES = {
    "EUR/JPY": ("euro area", "japan"),
    "EUR/USD": ("euro area", "united states"),
    "USD/JPY": ("united states", "japan"),
    "GBP/USD": ("united kingdom", "united states"),
    "GBP/JPY": ("united kingdom", "japan"),
    "AUD/USD": ("australia", "united states"),
    "USD/CAD": ("united states", "canada"),
}


def _text(element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def _parse_calendar_date(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _fetch_structured_calendar() -> tuple[list[dict], str | None]:
    """Fetch high-impact events from a structured economic calendar."""
    api_key = os.getenv("TRADING_ECONOMICS_API_KEY", "").strip()
    if not api_key:
        return [], None
    now = datetime.now(timezone.utc)
    cached_at = _CALENDAR_CACHE.get("checked_at")
    if cached_at and (now - cached_at).total_seconds() < 120:
        return _CALENDAR_CACHE["events"], "Trading Economics Calendar API"
    response = requests.get(
        TRADING_ECONOMICS_URL,
        params={"c": api_key, "f": "json"},
        headers={"User-Agent": "NEXUS-IA-TRADER/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Calendário estruturado retornou formato inesperado")
    events = []
    for item in payload:
        importance = int(item.get("Importance") or 0)
        event_date = _parse_calendar_date(item.get("Date"))
        if importance < 3 or not event_date or abs((event_date - now).total_seconds()) > 30 * 60:
            continue
        events.append({
            "title": item.get("Event") or item.get("Category") or "Evento macroeconômico",
            "country": item.get("Country", ""),
            "currency": item.get("Currency", ""),
            "published": event_date.isoformat(),
            "importance": importance,
            "actual": item.get("Actual", ""),
            "forecast": item.get("Forecast", ""),
            "previous": item.get("Previous", ""),
            "source_url": item.get("SourceURL", ""),
            "high_impact": True,
        })
    _CALENDAR_CACHE.update({"checked_at": now, "events": events})
    return events, "Trading Economics Calendar API"


def _structured_news(symbol: str) -> dict | None:
    try:
        events, source = _fetch_structured_calendar()
    except (requests.RequestException, ValueError, KeyError, TypeError, RuntimeError):
        return None
    if source is None:
        return None
    countries = {value.lower() for value in PAIR_COUNTRIES.get(symbol, ())}
    matching = [event for event in events if event["country"].lower() in countries]
    return {
        "symbol": symbol,
        "status": "ALERTA" if matching else "SEM_ALERTA",
        "events": matching[:8],
        "errors": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


def fetch_news(symbol: str, hours: float = 0.75, limit: int = 4) -> dict:
    structured = _structured_news(symbol)
    if structured is not None:
        return structured
    return {
        "symbol": symbol,
        "status": "SEM_FONTE",
        "events": [],
        "errors": ["TRADING_ECONOMICS_API_KEY ausente"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Trading Economics Calendar API não configurada",
    }


def should_block(news: dict) -> bool:
    return news.get("status") == "ALERTA"


def format_news(news: dict) -> str:
    lines = ["NEXUS SENTINEL — NOTÍCIAS", "", f"Ativo: {news['symbol']}", f"Status: {news['status']}"]
    if news["events"]:
        lines.append("\nEventos relevantes recentes:")
        lines.extend(f"• {event['title']}" for event in news["events"])
        lines.extend(["", "Proteção: possíveis sinais devem ser bloqueados até nova avaliação."])
    else:
        lines.extend(["", "Nenhum evento macro de alto impacto foi identificado na triagem."])
    lines.extend(["", f"Fonte: {news['source']}", "Modo TESTE — triagem informativa, não é recomendação financeira."])
    return "\n".join(lines)


def format_channel_alert(news: dict, block_minutes: int = 30) -> str:
    event = news.get("events", [{}])[0]
    title = event.get("title", "Evento macroeconômico de alto impacto")
    return "\n".join([
        "Perigo 🚨 NEXUS TRADER informa:",
        "",
        f"Risco macro detectado no mercado {news['symbol']}",
        "",
        f"{title}",
        "",
        f"Não serão enviadas análises para este ativo nos próximos {block_minutes} minutos.",
        "",
        "NEXUS SENTINEL — baseado no calendário Trading Economics.",
        "Triagem informativa; não é recomendação financeira.",
    ])
