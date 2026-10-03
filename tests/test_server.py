import asyncio
import json
import sys
from pathlib import Path

import chess
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from chesscli.engine import Engine
from chesscli.server import Server


async def recv(ws, kind):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if msg["t"] == kind:
            return msg


async def pair(port):
    host = await connect(f"ws://localhost:{port}")
    await host.send(json.dumps({"t": "create"}))
    code = (await recv(host, "created"))["code"]
    guest = await connect(f"ws://localhost:{port}")
    await guest.send(json.dumps({"t": "join", "code": code.lower()}))
    h, g = await recv(host, "start"), await recv(guest, "start")
    assert {h["color"], g["color"]} == {"white", "black"}
    white, black = (host, guest) if h["color"] == "white" else (guest, host)
    return white, black


def run_with_server(coro_fn):
    async def main():
        async with serve(Server().handler, "localhost", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            await coro_fn(port)
    asyncio.run(main())


def test_fools_mate_over_the_wire():
    async def scenario(port):
        white, black = await pair(port)
        for ws, uci in [(white, "f2f3"), (black, "e7e5"), (white, "g2g4"), (black, "d8h4")]:
            await ws.send(json.dumps({"t": "move", "uci": uci}))
            for peer in (white, black):
                assert (await recv(peer, "move"))["uci"] == uci
        for peer in (white, black):
            over = await recv(peer, "over")
            assert over["result"] == "0-1" and over["reason"] == "checkmate"
    run_with_server(scenario)


def test_rejects_illegal_and_out_of_turn_moves():
    async def scenario(port):
        white, black = await pair(port)
        await black.send(json.dumps({"t": "move", "uci": "e7e5"}))
        assert "not your turn" in (await recv(black, "error"))["msg"]
        await white.send(json.dumps({"t": "move", "uci": "e2e5"}))
        assert "Illegal" in (await recv(white, "error"))["msg"]
    run_with_server(scenario)


def test_bad_code_and_malformed_message():
    async def scenario(port):
        ws = await connect(f"ws://localhost:{port}")
        await ws.send(json.dumps({"t": "join", "code": "ZZZZ"}))
        assert "No open game" in (await recv(ws, "error"))["msg"]
        await ws.send("not json")
        assert "Malformed" in (await recv(ws, "error"))["msg"]
    run_with_server(scenario)


def test_resign_draw_and_disconnect():
    async def scenario(port):
        white, black = await pair(port)
        await white.send(json.dumps({"t": "draw"}))
        await recv(black, "draw_offered")
        await black.send(json.dumps({"t": "draw"}))
        assert (await recv(white, "over"))["reason"] == "agreement"
        white2, black2 = await pair(port)
        await white2.send(json.dumps({"t": "resign"}))
        assert (await recv(black2, "over"))["result"] == "0-1"
        white3, black3 = await pair(port)
        await white3.close()
        await recv(black3, "opponent_left")
    run_with_server(scenario)


def test_engine_wrapper_with_fake_uci_engine():
    async def scenario():
        fake = Path(__file__).with_name("fake_uci.py")
        engine = Engine([sys.executable, str(fake)], skill=3)
        await engine.start()
        board = chess.Board()
        board.push_san("e4")
        move = await engine.best_move(board, 0.1)
        assert board.is_legal(move)
        await engine.close()
    asyncio.run(scenario())
