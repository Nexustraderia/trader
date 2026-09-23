import sqlite3
import uuid
from datetime import datetime, timezone

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
            created_at TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'PENDENTE',
            closed_at TEXT
        )"""
    )
    connection.commit()
    return connection


def create_signal(result: dict) -> dict:
    signal = {
        "id": uuid.uuid4().hex[:8].upper(),
        "symbol": result["symbol"],
        "direction": result["decision"],
        "score": int(result["score"]),
        "timeframe": "M5",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connect() as connection:
        connection.execute(
            "INSERT INTO paper_signals (id, symbol, direction, score, timeframe, created_at) VALUES (?, ?, ?, ?, ?, ?)",
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
            "SELECT id, symbol, direction, score, timeframe, created_at, outcome FROM paper_signals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def format_signal(signal: dict) -> str:
    return "\n".join([
        "NEXUS IA TRADER — SINAL SIMULADO",
        "",
        f"ID: {signal['id']}",
        f"Ativo: {signal['symbol']}",
        f"Direção: {signal['direction']}",
        f"Período: {signal['timeframe']}",
        f"Score: {signal['score']}/100",
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
