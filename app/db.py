"""Small database compatibility layer for Render PostgreSQL and local SQLite."""
import os
import sqlite3


class DatabaseConnection:
    def __init__(self, raw, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.raw.rollback()
        else:
            self.raw.commit()
        self.raw.close()

    def execute(self, sql: str, params=()):
        if not self.postgres:
            return self.raw.execute(sql, params)
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        sql = sql.replace("?", "%s")
        sql = sql.replace(
            "INSERT OR REPLACE INTO telegram_file_cache (outcome, file_id) VALUES (%s, %s)",
            "INSERT INTO telegram_file_cache (outcome, file_id) VALUES (%s, %s) ON CONFLICT (outcome) DO UPDATE SET file_id = EXCLUDED.file_id",
        )
        cursor = self.raw.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self.raw.commit()


def connect() -> DatabaseConnection:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as error:
            raise RuntimeError("psycopg2 dependency unavailable") from error
        raw = psycopg2.connect(database_url, cursor_factory=RealDictCursor, connect_timeout=10)
        return DatabaseConnection(raw, postgres=True)

    path = os.getenv("PAPER_DB_PATH", "signals.sqlite3")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    return DatabaseConnection(raw, postgres=False)


def backend_name() -> str:
    return "PostgreSQL" if os.getenv("DATABASE_URL", "").strip() else "SQLite fallback"
