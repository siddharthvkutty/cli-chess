"""Relay server. Pairs two players by game code and validates every move (server is authoritative).

Protocol: JSON text frames with a "t" field.
  client -> server: create | join{code} | move{uci} | resign | draw | decline
  server -> client: created{code} | start{color} | move{uci,san} | over{result,reason}
                    | draw_offered | draw_declined | opponent_left | error{msg}
"""
import asyncio
import json
import random
import secrets
from dataclasses import dataclass, field

import chess
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


@dataclass
class Room:
    code: str
    host: ServerConnection
    guest: ServerConnection | None = None
    board: chess.Board = field(default_factory=chess.Board)
    colors: dict = field(default_factory=dict)  # connection -> chess.WHITE / chess.BLACK
    over: bool = False
    draw_from: ServerConnection | None = None

    def other(self, ws):
        return self.guest if ws is self.host else self.host

    @property
    def started(self) -> bool:
        return self.guest is not None


async def send(ws, **msg) -> None:
    try:
        await ws.send(json.dumps(msg))
    except ConnectionClosed:
        pass


class Server:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if code not in self.rooms:
                return code

    async def handler(self, ws: ServerConnection) -> None:
        room: Room | None = None
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    kind = msg["t"]
                except (ValueError, KeyError, TypeError):
                    await send(ws, t="error", msg="Malformed message.")
                    continue
                if room is None:
                    room = await self.lobby(ws, kind, msg)
                else:
                    await self.in_game(room, ws, kind, msg)
        except ConnectionClosed:
            pass
        finally:
            if room:
                await self.leave(room, ws)

    async def lobby(self, ws, kind, msg) -> Room | None:
        if kind == "create":
            room = Room(self.new_code(), host=ws)
            self.rooms[room.code] = room
            await send(ws, t="created", code=room.code)
            return room
        if kind == "join":
            code = str(msg.get("code", "")).strip().upper()
            room = self.rooms.get(code)
            if room is None or room.started:
                await send(ws, t="error", msg=f"No open game with code {code or '(empty)'}.")
                return None
            room.guest = ws
            host_color = random.choice([chess.WHITE, chess.BLACK])
            room.colors = {room.host: host_color, ws: not host_color}
            for conn in (room.host, ws):
                await send(conn, t="start", color="white" if room.colors[conn] else "black")
            return room
        await send(ws, t="error", msg="Create or join a game first.")
        return None

    async def in_game(self, room: Room, ws, kind, msg) -> None:
        if not room.started:
            await send(ws, t="error", msg="Waiting for an opponent.")
        elif room.over:
            await send(ws, t="error", msg="The game is over.")
        elif kind == "move":
            await self.move(room, ws, str(msg.get("uci", "")))
        elif kind == "resign":
            winner = "0-1" if room.colors[ws] else "1-0"
            await self.finish(room, winner, "resignation")
        elif kind == "draw":
            if room.board.can_claim_draw() or room.draw_from is room.other(ws):
                await self.finish(room, "1/2-1/2", "agreement")
            else:
                room.draw_from = ws
                await send(room.other(ws), t="draw_offered")
        elif kind == "decline":
            if room.draw_from is room.other(ws):
                room.draw_from = None
                await send(room.other(ws), t="draw_declined")
        else:
            await send(ws, t="error", msg=f"Unknown message type {kind!r}.")

    async def move(self, room: Room, ws, uci: str) -> None:
        if room.board.turn != room.colors[ws]:
            await send(ws, t="error", msg="It's not your turn.")
            return
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            move = None
        if move is None or not room.board.is_legal(move):
            await send(ws, t="error", msg=f"Illegal move {uci!r}.")
            return
        san = room.board.san(move)
        room.board.push(move)
        room.draw_from = None
        for conn in (room.host, room.guest):
            await send(conn, t="move", uci=uci, san=san)
        if outcome := room.board.outcome(claim_draw=True):
            await self.finish(room, outcome.result(), outcome.termination.name.replace("_", " ").lower())

    async def finish(self, room: Room, result: str, reason: str) -> None:
        room.over = True
        for conn in (room.host, room.guest):
            await send(conn, t="over", result=result, reason=reason)

    async def leave(self, room: Room, ws) -> None:
        other = room.other(ws)
        if room.started and not room.over:
            room.over = True
            await send(other, t="opponent_left")
        if self.rooms.get(room.code) is room:
            del self.rooms[room.code]


async def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = Server()
    async with serve(server.handler, host, port, max_size=2**12) as ws_server:
        print(f"cli-chess server listening on ws://{host}:{port}  (Ctrl+C to stop)", flush=True)
        await ws_server.serve_forever()
