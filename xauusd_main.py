"""
main.py — XAUUSD Bot entry point
Launches bot + Flask server together
"""

import threading
import logging
from xauusd_bot import XAUUSDBot
import server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("xauusd_bot.log"), logging.StreamHandler()]
)

def run_server(bot):
    server.set_bot(bot)
    server.app.run(host="0.0.0.0", port=5051, debug=False, use_reloader=False)


if __name__ == "__main__":
    bot = XAUUSDBot()

    t = threading.Thread(target=run_server, args=(bot,), daemon=True)
    t.start()

    print("=" * 62)
    print("  XAUUSD TRADING BOT — QQQ Bot Style")
    print("  Strategies: Asian Breakout | Goldmine | Silver Bullet")
    print("  Dashboard API: http://localhost:5051")
    print("  WebSocket:     ws://localhost:5051/ws")
    print("=" * 62)

    bot.run()
