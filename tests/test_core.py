import os
import tempfile
import unittest

from app.market_data import normalize_symbol
from app.news_sentinel import should_block
from app.paper_journal import close_signal, create_signal, recent_signals
from app.signal_engine import analyze
import app.paper_journal as paper_journal


class CoreTests(unittest.TestCase):
    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("eurjpy"), "EUR/JPY")
        self.assertEqual(normalize_symbol("XAUUSD"), "XAU/USD")

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
            signal = create_signal({"symbol": "EUR/JPY", "decision": "CALL", "score": 75})
            self.assertTrue(close_signal(signal["id"], "WIN"))
            self.assertFalse(close_signal(signal["id"], "LOSS"))
            self.assertEqual(recent_signals(1)[0]["outcome"], "WIN")
        finally:
            os.unlink(database)


if __name__ == "__main__":
    unittest.main()
