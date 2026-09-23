import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

DEFAULT_FEEDS = [
    "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": "ECB OR Federal Reserve OR Bank of Japan interest rates inflation forex", "hl": "en-US", "gl": "US", "ceid": "US:en"}),
]
HIGH_IMPACT_TERMS = (
    "interest rate", "rate decision", "monetary policy", "central bank", "inflation",
    "cpi", "ppi", "payroll", "nonfarm", "employment", "unemployment", "fed",
    "ecb", "boj", "bank of japan", "fomc", "press conference", "gdp",
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


def _text(element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def fetch_news(symbol: str, hours: int = 24, limit: int = 8) -> dict:
    feeds = [item.strip() for item in os.getenv("NEWS_FEEDS", "").split(",") if item.strip()] or DEFAULT_FEEDS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    terms = PAIR_TERMS.get(symbol, ())
    events = []
    errors = []

    for feed_url in feeds:
        try:
            response = requests.get(feed_url, headers={"User-Agent": "NEXUS-IA-TRADER/0.1"}, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item"):
                title = _text(item, "title")
                link = _text(item, "link")
                published = _text(item, "pubDate")
                try:
                    published_at = parsedate_to_datetime(published).astimezone(timezone.utc)
                except (TypeError, ValueError, OverflowError):
                    published_at = None
                if published_at and published_at < cutoff:
                    continue
                haystack = f"{title} {published}".lower()
                relevant = not terms or any(term in haystack for term in terms)
                high_impact = any(term in haystack for term in HIGH_IMPACT_TERMS)
                if relevant and high_impact:
                    events.append({"title": title, "link": link, "published": published, "high_impact": True})
        except (requests.RequestException, ET.ParseError, ValueError) as error:
            errors.append(type(error).__name__)

    unique = []
    seen = set()
    for event in events:
        key = event["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(event)
    unique = unique[:limit]
    return {
        "symbol": symbol,
        "status": "ALERTA" if unique else ("SEM_ALERTA" if not errors else "DADOS_PARCIAIS"),
        "events": unique,
        "errors": errors,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "Google News RSS (triagem de manchetes; protótipo)",
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
        f"Notícia de impacto no mercado {news['symbol']} 🐮🐮🐮",
        "",
        f"{title}",
        "",
        f"Não serão enviadas análises para este ativo nos próximos {block_minutes} minutos.",
        "",
        "NEXUS SENTINEL — proteção automática por risco de notícia.",
        "Triagem informativa; não é recomendação financeira.",
    ])
