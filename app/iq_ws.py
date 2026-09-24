"""Read-only IQ Option WebSocket client with one reusable authenticated session."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp
import websockets

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WSS_URL = "wss://ws.iqoption.com/echo/websocket"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36"


class _IQSession:
    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.ws: Any = None
        self.request_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.ws is not None:
            return
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        ) as session:
            async with session.post(
                LOGIN_URL,
                json={"identifier": self.email, "password": self.password},
                headers={
                    "Origin": "https://iqoption.com",
                    "Content-Type": "application/json",
                },
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except Exception:
                    payload = {}
                if response.status != 200:
                    raise RuntimeError(f"IQ login HTTP {response.status}: {str(payload)[:160]}")
                cookie = response.cookies.get("ssid")
                if cookie is None:
                    raise RuntimeError(f"IQ login sem SSID: {str(payload)[:160]}")
                ssid = cookie.value

        ws = await websockets.connect(
            WSS_URL,
            origin="https://iqoption.com",
            user_agent_header=USER_AGENT,
            open_timeout=20,
            close_timeout=5,
            ping_interval=20,
        )
        try:
            await ws.send(json.dumps({"name": "authenticate", "msg": {"ssid": ssid, "protocol": 3}}))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
                message = _decode(raw)
                if message.get("name") == "heartbeat":
                    await ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
                if message.get("name") == "authenticated":
                    if not message.get("msg"):
                        raise RuntimeError("IQ WebSocket rejeitou autenticação")
                    self.ws = ws
                    return
            raise TimeoutError("IQ WebSocket timeout na autenticação")
        except BaseException:
            await ws.close()
            raise

    async def close(self) -> None:
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def candles(self, active_id: int, size: int, count: int) -> list[dict]:
        async with self.request_lock:
            await self.connect()
            request_id = f"nexus-{int(time.time() * 1000)}"
            await self.ws.send(json.dumps({
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
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
                except asyncio.TimeoutError as error:
                    raise TimeoutError(f"IQ WebSocket sem resposta; mensagens={last_names}") from error
                message = _decode(raw)
                last_names.append(str(message.get("name", "")))
                last_names = last_names[-8:]
                if message.get("name") == "heartbeat":
                    await self.ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
                if message.get("request_id") == request_id or message.get("name") == "candles":
                    payload = message.get("msg") or {}
                    candles = list(payload.get("candles") or [])
                    if not candles:
                        raise RuntimeError(
                            f"IQ candles response sem candles: name={message.get('name')} keys={sorted(payload)[:12]}"
                        )
                    return candles
            raise TimeoutError(f"IQ WebSocket não retornou candles; mensagens={last_names}")


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
