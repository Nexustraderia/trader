import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DB_PATH = "signals.sqlite3"
LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")


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
            entry_at TEXT,
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
    if "entry_at" not in columns:
        connection.execute("ALTER TABLE paper_signals ADD COLUMN entry_at TEXT")
    connection.commit()
    return connection


def create_signal(result: dict) -> dict:
    created_at = datetime.now(timezone.utc)
    next_minute = ((created_at.minute // 5) + 1) * 5
    entry_at = created_at.replace(second=0, microsecond=0) + timedelta(minutes=next_minute - created_at.minute)
    signal = {
        "id": uuid.uuid4().hex[:8].upper(),
        "symbol": result["symbol"],
        "direction": result["decision"],
        "score": int(result["score"]),
        "timeframe": "M5",
        "entry_price": result.get("price"),
        "created_at": created_at.isoformat(),
        "entry_at": entry_at.isoformat(),
        "expires_at": (entry_at + timedelta(minutes=5)).isoformat(),
    }
    with _connect() as connection:
        connection.execute(
            "INSERT INTO paper_signals (id, symbol, direction, score, timeframe, entry_price, created_at, entry_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            "SELECT id, symbol, direction, score, timeframe, entry_price, created_at, entry_at, expires_at, outcome FROM paper_signals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def settle_pending(price_lookup) -> list[dict]:
    now = datetime.now(timezone.utc)
    settled = []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, symbol, direction, entry_price, entry_at, expires_at FROM paper_signals WHERE outcome = 'PENDENTE' AND expires_at IS NOT NULL"
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
                settled.append({"id": row["id"], "symbol": row["symbol"], "direction": row["direction"], "entry_at": row["entry_at"], "outcome": outcome, "entry_price": entry_price, "exit_price": exit_price})
            except (TypeError, ValueError, KeyError, OSError, ConnectionError):
                continue
    return settled


def format_result(result: dict) -> str:
    entry = datetime.fromisoformat(result["entry_at"]).astimezone(LOCAL_ZONE) if result.get("entry_at") else None
    outcome = {"WIN": "Win", "LOSS": "Loss", "VOID": "Void"}.get(result["outcome"], result["outcome"])
    return "\n".join([
        "NEXUS IA TRADER ( Resultado final da nossa análise)",
        "",
        f"Ativo: {result['symbol']}",
        f"Direção: {result['direction']}",
        f"Entrada: {entry.strftime('%H:%M') if entry else 'indisponível'}",
        "Tempo Expiração: M5",
        "",
        f"O resultado desta entrada foi {outcome}.",
        "Mantenha o seu gerenciamento foque no seus objetivos.",
    ])


def format_signal(signal: dict) -> str:
    entry = datetime.fromisoformat(signal["entry_at"]).astimezone(LOCAL_ZONE) if signal.get("entry_at") else None
    return "\n".join([
        "NEXUS IA TRADER",
        "As melhores análises em tempo Real",
        "",
        f"Ativo: {signal['symbol']}",
        f"Direção: {signal['direction']}",
        f"Entrada: {entry.strftime('%H:%M') if entry else 'próxima vela'}",
        f"Tempo Expiração: {signal['timeframe']}",
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


def session_statistics(hours: int = 2) -> dict:
    """Summarize signals created in the rolling session window."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT outcome, COUNT(*) AS total FROM paper_signals WHERE created_at >= ? GROUP BY outcome",
            (since,),
        ).fetchall()
    counts = {row["outcome"]: row["total"] for row in rows}
    wins = counts.get("WIN", 0)
    losses = counts.get("LOSS", 0)
    decided = wins + losses
    return {
        "hours": hours,
        "total": sum(counts.values()),
        "wins": wins,
        "losses": losses,
        "void": counts.get("VOID", 0),
        "pending": counts.get("PENDENTE", 0),
        "accuracy": (wins / decided * 100) if decided else None,
    }


def format_session_summary(stats: dict) -> str:
    accuracy = f"{stats['accuracy']:.1f}%" if stats["accuracy"] is not None else "sem amostra"
    return "\n".join([
        "NEXUS IA TRADER — RESULTADO DA SESSÃO",
        "",
        f"Resumo das últimas {stats['hours']} horas",
        "",
        f"Análises feitas: {stats['total']}",
        f"WIN: {stats['wins']}",
        f"LOSS: {stats['losses']}",
        f"VOID: {stats['void']}",
        f"Pendentes: {stats['pending']}",
        f"Taxa da janela: {accuracy}",
        "",
        "Não usamos martingale.",
        "Mantenha seu gerenciamento e foque nos seus objetivos.",
        "",
        "Resumo baseado em paper trading; não é garantia de resultado.",
    ])


def ranking() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT symbol,
                      COUNT(*) AS total,
                      SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses
               FROM paper_signals GROUP BY symbol ORDER BY wins DESC, total DESC, symbol"""
        ).fetchall()
    result = []
    for row in rows:
        decided = row["wins"] + row["losses"]
        result.append({"symbol": row["symbol"], "total": row["total"], "wins": row["wins"], "losses": row["losses"], "accuracy": (row["wins"] / decided * 100) if decided else None})
    return result


def format_ranking(rows: list[dict]) -> str:
    lines = ["NEXUS IA TRADER — RANKING PAPER", ""]
    if not rows:
        lines.append("Nenhum resultado registrado ainda.")
    else:
        for row in rows:
            accuracy = f"{row['accuracy']:.1f}%" if row["accuracy"] is not None else "sem amostra"
            lines.append(f"{row['symbol']} | WIN {row['wins']} | LOSS {row['losses']} | Total {row['total']} | Taxa {accuracy}")
    lines.extend(["", "Ranking baseado somente em paper trading; não é garantia de lucro."])
    return "\n".join(lines)
