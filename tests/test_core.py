import os
import tempfile
import time
import unittest

from app.market_data import is_fresh, normalize_symbol
from app.news_sentinel import should_block
from app.paper_journal import close_signal, create_signal, ranking, recent_signals, settle_pending, statistics
from app.signal_engine import analyze
import app.paper_journal as paper_journal


class CoreTests(unittest.TestCase):
    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("eurjpy"), "EUR/JPY")
        self.assertEqual(normalize_symbol("XAUUSD"), "XAU/USD")

    def test_stale_market_data_is_rejected(self):
        self.assertTrue(is_fresh([{"timestamp": time.time()}], 60))
        self.assertFalse(is_fresh([{"timestamp": time.time() - 120}], 60))

    def test_signal_engine_can_choose_wait(self):
        candles = [{"close": value} for value in range(100, 130)]
        result = analyze("EUR/JPY", candles)
        self.assertIn(result["decision"], {"CALL", "PUT", "AGUARDAR"})
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_news_alert_blocks(self):
        self.assertTrue(should_block({"status": "ALERTA"}))
        self.assertFalse(should_block({"status": "SEM_ALERTA"}))

    def test_paper_signal_lifecycle(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as file:
            database = file.name
        try:
            paper_journal.DB_PATH = database
            signal = create_signal({"symbol": "EUR/JPY", "decision": "CALL", "score": 75, "price": 180.12})
            self.assertEqual(signal["entry_price"], 180.12)
            self.assertIn("expires_at", signal)
            self.assertTrue(close_signal(signal["id"], "WIN"))
            self.assertFalse(close_signal(signal["id"], "LOSS"))
            self.assertEqual(recent_signals(1)[0]["outcome"], "WIN")
            self.assertEqual(statistics()["accuracy"], 100.0)
            self.assertEqual(statistics("EUR/JPY")["wins"], 1)
            self.assertEqual(statistics("GBP/USD")["total"], 0)
            self.assertEqual(ranking()[0]["symbol"], "EUR/JPY")

            connection_signal = create_signal({"symbol": "EUR/USD", "decision": "PUT", "score": 80, "price": 1.1000})
            with paper_journal._connect() as connection:
                connection.execute("UPDATE paper_signals SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", connection_signal["id"]))
            settled = settle_pending(lambda symbol: 1.0990)
            self.assertEqual(settled[0]["outcome"], "WIN")
        finally:
            os.unlink(database)


if __name__ == "__main__":
    unittest.main()
