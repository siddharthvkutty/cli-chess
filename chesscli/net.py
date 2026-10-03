"""Client side of the relay protocol (see server.py)."""
import json
import re

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

DEFAULT_PORT = 8765


def normalize_url(text: str) -> str:
    """'localhost' -> ws://localhost:8765, 'https://x.trycloudflare.com' -> wss://x.trycloudflare.com"""
    url = text.strip().rstrip("/")
    url = re.sub(r"^http(s?)://", lambda m: f"ws{m.group(1)}://", url)
    if "://" not in url:
        local = re.match(r"(localhost|127\.|192\.168\.|10\.)", url)
        url = ("ws://" if local else "wss://") + url
    if url.startswith("ws://") and not re.search(r":\d+$", url):
        url += f":{DEFAULT_PORT}"
    return url


class NetClient:
    def __init__(self, ws: ClientConnection):
        self.ws = ws

    @classmethod
    async def open(cls, url: str) -> "NetClient":
        return cls(await connect(normalize_url(url), open_timeout=10))

    async def send(self, **msg) -> None:
        await self.ws.send(json.dumps(msg))

    async def messages(self):
        try:
            async for raw in self.ws:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
        except ConnectionClosed:
            return

    async def close(self) -> None:
        await self.ws.close()
