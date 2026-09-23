import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

DB_PATH = "signals.sqlite3"


def _connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS paper_signals (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            score INTEGER NOT NULL,
            timeframe TEXT NOT NULL,
            entry_price REAL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            outcome TEXT NOT NULL DEFAULT 'PENDENTE',
            closed_at TEXT
        )"""
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(paper_signals)")}
    if "entry_price" not in columns:
        connection.execute("ALTER TABLE paper_signals ADD COLUMN entry_price REAL")
    if "expires_at" not in columns:
        connection.execute("ALTER TABLE paper_signals ADD COLUMN expires_at TEXT")
    connection.commit()
    return connection


def create_signal(result: dict) -> dict:
    created_at = datetime.now(timezone.utc)
    signal = {
        "id": uuid.uuid4().hex[:8].upper(),
        "symbol": result["symbol"],
        "direction": result["decision"],
        "score": int(result["score"]),
        "timeframe": "M5",
        "entry_price": result.get("price"),
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=5)).isoformat(),
    }
    with _connect() as connection:
        connection.execute(
            "INSERT INTO paper_signals (id, symbol, direction, score, timeframe, entry_price, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(signal.values()),
        )
    return signal


def close_signal(signal_id: str, outcome: str) -> bool:
    outcome = outcome.upper()
    if outcome not in {"WIN", "LOSS", "VOID"}:
        return False
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE paper_signals SET outcome = ?, closed_at = ? WHERE id = ? AND outcome = 'PENDENTE'",
            (outcome, datetime.now(timezone.utc).isoformat(), signal_id.upper()),
        )
        return cursor.rowcount == 1


def recent_signals(limit: int = 10) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, symbol, direction, score, timeframe, entry_price, created_at, expires_at, outcome FROM paper_signals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def settle_pending(price_lookup) -> list[dict]:
    now = datetime.now(timezone.utc)
    settled = []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, symbol, direction, entry_price, expires_at FROM paper_signals WHERE outcome = 'PENDENTE' AND expires_at IS NOT NULL"
        ).fetchall()
        for row in rows:
            if datetime.fromisoformat(row["expires_at"]) > now:
                continue
            try:
                exit_price = float(price_lookup(row["symbol"]))
                entry_price = float(row["entry_price"])
                if exit_price == entry_price:
                    outcome = "VOID"
                elif (row["direction"] == "CALL" and exit_price > entry_price) or (row["direction"] == "PUT" and exit_price < entry_price):
                    outcome = "WIN"
                else:
                    outcome = "LOSS"
                connection.execute(
                    "UPDATE paper_signals SET outcome = ?, closed_at = ? WHERE id = ? AND outcome = 'PENDENTE'",
                    (outcome, now.isoformat(), row["id"]),
                )
                settled.append({"id": row["id"], "symbol": row["symbol"], "direction": row["direction"], "outcome": outcome, "entry_price": entry_price, "exit_price": exit_price})
            except (TypeError, ValueError, KeyError):
                continue
    return settled


def format_signal(signal: dict) -> str:
    return "\n".join([
        "NEXUS IA TRADER — SINAL SIMULADO",
        "",
        f"ID: {signal['id']}",
        f"Ativo: {signal['symbol']}",
        f"Direção: {signal['direction']}",
        f"Período: {signal['timeframe']}",
        f"Score: {signal['score']}/100",
        f"Preço de entrada: {signal['entry_price']}" if signal.get("entry_price") is not None else "Preço de entrada: indisponível",
        f"Expiração: {signal['expires_at']}" if signal.get("expires_at") else "Expiração: M5",
        "",
        "Registro PAPER TRADING — nenhuma ordem foi enviada.",
        "Resultado deve ser avaliado manualmente; não é garantia de lucro.",
    ])


def format_history(signals: list[dict]) -> str:
    lines = ["NEXUS IA TRADER — HISTÓRICO SIMULADO", ""]
    if not signals:
        lines.append("Nenhum sinal simulado registrado.")
    else:
        for signal in signals:
            lines.append(f"{signal['id']} | {signal['symbol']} | {signal['direction']} | {signal['score']}/100 | {signal['outcome']}")
    lines.extend(["", "PAPER TRADING — sem ordens reais."])
    return "\n".join(lines)


def statistics(symbol: str | None = None) -> dict:
    with _connect() as connection:
        if symbol:
            rows = connection.execute("SELECT outcome, COUNT(*) AS total FROM paper_signals WHERE symbol = ? GROUP BY outcome", (symbol,)).fetchall()
        else:
            rows = connection.execute("SELECT outcome, COUNT(*) AS total FROM paper_signals GROUP BY outcome").fetchall()
    counts = {row["outcome"]: row["total"] for row in rows}
    wins = counts.get("WIN", 0)
    losses = counts.get("LOSS", 0)
    decided = wins + losses
    return {"total": sum(counts.values()), "wins": wins, "losses": losses, "void": counts.get("VOID", 0), "pending": counts.get("PENDENTE", 0), "accuracy": (wins / decided * 100) if decided else None}


def format_statistics(stats: dict, symbol: str | None = None) -> str:
    accuracy = f"{stats['accuracy']:.1f}%" if stats["accuracy"] is not None else "sem amostra"
    return "\n".join([
        f"NEXUS IA TRADER — ESTATÍSTICAS PAPER{f' — {symbol}' if symbol else ''}",
        "",
        f"Total: {stats['total']}",
        f"WIN: {stats['wins']}",
        f"LOSS: {stats['losses']}",
        f"VOID: {stats['void']}",
        f"PENDENTE: {stats['pending']}",
        f"Taxa histórica da amostra: {accuracy}",
        "",
        "Amostra simulada; não representa garantia de desempenho futuro.",
    ])
