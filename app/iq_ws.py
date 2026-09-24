import asyncio
import json
import time

import aiohttp
import websockets

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WSS_URL = "wss://ws.iqoption.com/echo/websocket"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36"


async def _login(email: str, password: str) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=timeout) as session:
        async with session.post(LOGIN_URL, data={"identifier": email, "password": password}) as response:
            payload = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"IQ login HTTP {response.status}")
            cookie = response.cookies.get("ssid")
            if cookie is None:
                raise RuntimeError(f"IQ login sem SSID ({payload.get('code', 'unknown')})")
            return cookie.value


async def get_candles(email: str, password: str, active_id: int, size: int, count: int) -> list[dict]:
    ssid = await _login(email, password)
    request_id = f"nexus-{int(time.time() * 1000)}"
    async with websockets.connect(
        WSS_URL,
        origin="https://iqoption.com",
        user_agent_header=USER_AGENT,
        open_timeout=15,
        close_timeout=5,
        ping_interval=20,
    ) as ws:
        await ws.send(json.dumps({
            "name": "authenticate",
            "msg": {"ssid": ssid, "protocol": 3},
        }))
        authenticated = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            message = json.loads(raw)
            if message.get("name") == "heartbeat":
                await ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
            if message.get("name") == "authenticated":
                authenticated = bool(message.get("msg"))
                break
        if not authenticated:
            raise RuntimeError("IQ WebSocket rejeitou autenticação")
        await ws.send(json.dumps({
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
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            message = json.loads(raw)
            if message.get("name") == "heartbeat":
                await ws.send(json.dumps({"name": "heartbeat", "msg": message.get("msg")}))
            if message.get("request_id") == request_id:
                payload = message.get("msg") or {}
                candles = list(payload.get("candles") or [])
                if not candles:
                    raise RuntimeError(
                        f"IQ candles response sem candles: name={message.get('name')} keys={sorted(payload)[:12]}"
                    )
                return candles
        raise TimeoutError("IQ WebSocket não retornou candles")
