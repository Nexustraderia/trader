"""Read-only IQ Option WebSocket client using the protocol validated in Colab."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import requests
import websocket

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WSS_URL = "wss://ws.iqoption.com/echo/websocket"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36"


class _IQSession:
    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.ws: Any = None
        self.request_lock = asyncio.Lock()

    def _connect_sync(self) -> Any:
        response = requests.post(
            LOGIN_URL,
            json={"identifier": self.email, "password": self.password},
            headers={"Origin": "https://iqoption.com", "User-Agent": USER_AGENT},
            timeout=25,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code != 200:
            raise RuntimeError(f"IQ login HTTP {response.status_code}: {str(payload)[:160]}")
        ssid = response.cookies.get("ssid")
        if not ssid:
            raise RuntimeError(f"IQ login sem SSID: {str(payload)[:160]}")

        ws = websocket.create_connection(
            WSS_URL,
            origin="https://iqoption.com",
            timeout=15,
        )
        ws.send(json.dumps({"name": "authenticate", "msg": {"ssid": ssid, "protocol": 3}}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ws.settimeout(max(0.1, deadline - time.monotonic()))
            message = _decode(ws.recv())
            if message.get("name") == "heartbeat":
                ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
            if message.get("name") == "authenticated":
                if not message.get("msg"):
                    raise RuntimeError("IQ WebSocket rejeitou autenticação")
                return ws
        ws.close()
        raise TimeoutError("IQ WebSocket timeout na autenticação")

    async def connect(self) -> None:
        if self.ws is None:
            self.ws = await asyncio.to_thread(self._connect_sync)

    async def close(self) -> None:
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await asyncio.to_thread(ws.close)
            except Exception:
                pass

    def _candles_sync(self, active_id: int, size: int, count: int) -> list[dict]:
        request_id = f"nexus-{int(time.time() * 1000)}"
        self.ws.send(json.dumps({
            "name": "sendMessage",
            "request_id": request_id,
            "local_time": int(time.time()),
            "msg": {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": int(active_id),
                    "size": int(size),
                    "to": int(time.time()),
                    "count": int(count),
                },
            },
        }))
        deadline = time.monotonic() + 25
        last_names: list[str] = []
        while time.monotonic() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.monotonic()))
            message = _decode(self.ws.recv())
            last_names.append(str(message.get("name", "")))
            last_names = last_names[-8:]
            if message.get("name") == "heartbeat":
                self.ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
            if message.get("request_id") == request_id or message.get("name") == "candles":
                payload = message.get("msg") or {}
                candles = list(payload.get("candles") or [])
                if not candles:
                    raise RuntimeError(
                        f"IQ candles response sem candles: name={message.get('name')} keys={sorted(payload)[:12]}"
                    )
                return candles
        raise TimeoutError(f"IQ WebSocket não retornou candles; mensagens={last_names}")

    async def candles(self, active_id: int, size: int, count: int) -> list[dict]:
        async with self.request_lock:
            await self.connect()
            try:
                return await asyncio.to_thread(self._candles_sync, active_id, size, count)
            except websocket.WebSocketTimeoutException as error:
                raise TimeoutError("IQ WebSocket sem resposta") from error


def _decode(raw: Any) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


_shared_session: _IQSession | None = None
_shared_lock: asyncio.Lock | None = None
_shared_credentials: tuple[str, str] | None = None


async def _get_shared_session(email: str, password: str) -> _IQSession:
    global _shared_session, _shared_lock, _shared_credentials
    if _shared_lock is None:
        _shared_lock = asyncio.Lock()
    async with _shared_lock:
        if _shared_session is None or _shared_credentials != (email, password):
            if _shared_session is not None:
                await _shared_session.close()
            _shared_session = _IQSession(email, password)
            _shared_credentials = (email, password)
        await _shared_session.connect()
        return _shared_session


async def _reset_shared_session(session: _IQSession) -> None:
    global _shared_session, _shared_credentials
    if _shared_session is session:
        await session.close()
        _shared_session = None
        _shared_credentials = None


async def get_candles(email: str, password: str, active_id: int, size: int, count: int) -> list[dict]:
    """Return read-only candles while reusing the authenticated WebSocket."""
    last_error: Exception | None = None
    for _ in range(2):
        session = await _get_shared_session(email.strip(), password)
        try:
            return await session.candles(active_id, size, count)
        except Exception as error:
            last_error = error
            await _reset_shared_session(session)
    raise last_error or TimeoutError("IQ WebSocket indisponível")
