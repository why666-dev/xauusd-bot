"""
server.py — Flask API server for XAUUSD dashboard
"""

from flask import Flask, jsonify
from flask_cors import CORS
from flask_sock import Sock
import threading
import time
import logging
import sys
import os

log = logging.getLogger(__name__)
app = Flask(__name__)
CORS(app)
sock = Sock(app)

_bot        = None
_ws_clients = set()
_ws_lock    = threading.Lock()


def set_bot(bot):
    global _bot
    _bot = bot


def broadcast_loop():
    global _bot, _ws_clients, _ws_lock
    while True:
        if _bot:
            try:
                payload = _bot.get_state_json()
                dead    = set()
                with _ws_lock:
                    clients = set(_ws_clients)
                for ws in clients:
                    try:
                        ws.send(payload)
                    except Exception:
                        dead.add(ws)
                with _ws_lock:
                    _ws_clients -= dead
            except Exception as e:
                log.error(f"Broadcast error: {e}")
        time.sleep(2)


threading.Thread(target=broadcast_loop, daemon=True).start()


@app.route("/api/state")
def get_state():
    global _bot
    if not _bot:
        return jsonify({"error": "Bot not running"}), 503
    return _bot.get_state_json(), 200, {"Content-Type": "application/json"}


@app.route("/api/strategy/<name>")
def get_strategy(name):
    global _bot
    if not _bot or name not in _bot.stats:
        return jsonify({})
    return jsonify(_bot.stats[name].to_dict())


@app.route("/api/status")
def status():
    global _bot
    return jsonify({
        "running":    _bot is not None and _bot.running,
        "strategies": ["S1_Asian_Breakout", "S2_Goldmine", "S3_Silver_Bullet"],
        "symbol":     "XAUUSD"
    })


@sock.route("/ws")
def ws_handler(ws):
    global _ws_clients, _ws_lock
    with _ws_lock:
        _ws_clients.add(ws)
    try:
        while True:
            msg = ws.receive(timeout=30)
            if msg is None:
                break
    except Exception:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5051, debug=False)
