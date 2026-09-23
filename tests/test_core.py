import os
import tempfile
import time
import unittest
from datetime import datetime

from app.market_data import is_fresh, market_data_source, normalize_symbol
from app.news_sentinel import format_channel_alert, should_block
from app.paper_journal import close_signal, create_signal, format_result, format_session_summary, format_signal, mark_result_delivered, pending_result_deliveries, ranking, recent_signals, session_statistics, settle_pending, statistics
from app.signal_engine import analyze, analyze_with_confirmation
import app.paper_journal as paper_journal


class CoreTests(unittest.TestCase):
    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("eurjpy"), "EUR/JPY")
        self.assertEqual(normalize_symbol("XAUUSD"), "XAU/USD")
        self.assertEqual(normalize_symbol("usdjpy"), "USD/JPY")
        self.assertEqual(normalize_symbol("GBPJPY"), "GBP/JPY")
        self.assertEqual(normalize_symbol("audusd"), "AUD/USD")
        self.assertEqual(normalize_symbol("USDCAD"), "USD/CAD")

    def test_stale_market_data_is_rejected(self):
        self.assertTrue(is_fresh([{"timestamp": time.time()}], 60))
        self.assertFalse(is_fresh([{"timestamp": time.time() - 120}], 60))

    def test_market_source_fallback_is_explicit(self):
        os.environ.pop("TWELVEDATA_API_KEY", None)
        self.assertIn("fallback", market_data_source())

    def test_signal_engine_can_choose_wait(self):
        candles = [{"close": value} for value in range(100, 130)]
        result = analyze("EUR/JPY", candles)
        self.assertIn(result["decision"], {"CALL", "PUT", "AGUARDAR"})
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_full_timeframe_confluence_is_required(self):
        rising = [{"close": value} for value in range(100, 180)]
        result = analyze_with_confirmation("EUR/JPY", rising, rising, rising)
        self.assertTrue(result["confluence_ok"])

    def test_flat_market_is_blocked_by_volatility_filter(self):
        flat = [{"close": 100.0 + (index * 0.00001)} for index in range(80)]
        result = analyze_with_confirmation("EUR/JPY", flat, flat, flat)
        self.assertFalse(result["volatility_ok"])
        self.assertFalse(result["confluence_ok"])
        self.assertEqual(result["decision"], "AGUARDAR")

    def test_news_alert_blocks(self):
        self.assertTrue(should_block({"status": "ALERTA"}))
        self.assertFalse(should_block({"status": "SEM_ALERTA"}))
        alert = format_channel_alert({"symbol": "EUR/JPY", "events": [{"title": "ECB rate decision"}]})
        self.assertIn("EUR/JPY", alert)
        self.assertIn("calendário Trading Economics", alert)
        self.assertIn("30 minutos", alert)

    def test_paper_signal_lifecycle(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as file:
            database = file.name
        try:
            paper_journal.DB_PATH = database
            signal = create_signal({"symbol": "EUR/JPY", "decision": "CALL", "score": 75, "price": 180.12})
            self.assertEqual(signal["entry_price"], 180.12)
            duplicate = create_signal({"symbol": "EUR/JPY", "decision": "CALL", "score": 75, "price": 180.12})
            self.assertTrue(duplicate.get("_duplicate"))
            self.assertIn("expires_at", signal)
            self.assertEqual((datetime.fromisoformat(signal["expires_at"]) - datetime.fromisoformat(signal["entry_at"])).seconds, 300)
            formatted = format_signal(signal)
            self.assertIn("NEXUS IA TRADER", formatted)
            self.assertIn("As melhores análises em tempo Real", formatted)
            self.assertIn("Entrada:", formatted)
            self.assertIn("Tempo Expiração: M5", formatted)
            self.assertNotIn("BRT", formatted)
            self.assertNotIn("PAPER TRADING", formatted)
            self.assertNotIn("ID:", formatted)
            self.assertTrue(close_signal(signal["id"], "WIN"))
            self.assertFalse(close_signal(signal["id"], "LOSS"))
            self.assertEqual(pending_result_deliveries()[0]["id"], signal["id"])
            self.assertTrue(mark_result_delivered(signal["id"]))
            self.assertEqual(pending_result_deliveries(), [])
            self.assertEqual(recent_signals(1)[0]["outcome"], "WIN")
            self.assertEqual(statistics()["accuracy"], 100.0)
            self.assertEqual(statistics("EUR/JPY")["wins"], 1)
            self.assertEqual(statistics("GBP/USD")["total"], 0)
            self.assertEqual(ranking()[0]["symbol"], "EUR/JPY")
            summary = format_session_summary(session_statistics(2))
            self.assertIn("Análises feitas: 1", summary)
            self.assertIn("WIN: 1", summary)
            self.assertIn("Não usamos martingale.", summary)

            connection_signal = create_signal({"symbol": "EUR/USD", "decision": "PUT", "score": 80, "price": 1.1000})
            with paper_journal._connect() as connection:
                connection.execute("UPDATE paper_signals SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", connection_signal["id"]))
            settled = settle_pending(lambda symbol: 1.0990)
            self.assertEqual(settled[0]["outcome"], "WIN")
            result_text = format_result(settled[0])
            self.assertIn("NEXUS IA TRADER ( Resultado final da nossa análise)", result_text)
            self.assertIn("O resultado desta entrada foi Win.", result_text)
        finally:
            os.unlink(database)


if __name__ == "__main__":
    unittest.main()
