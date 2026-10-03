import asyncio
import json
import sys
from pathlib import Path

import chess
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from chesscli import config
from chesscli.app import ChessApp, GameScreen
from chesscli.board_view import BoardView
from chesscli.server import Server
from tests.test_server import recv


async def type_text(pilot, text):
    await pilot.click("#move-input")
    await pilot.press(*text, "enter")
    await pilot.pause()


def game(app) -> GameScreen:
    return app.screen


def test_typed_moves_in_local_game():
    async def scenario():
        app = ChessApp(ascii_only=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(GameScreen(mode="local", ascii_only=True))
            await pilot.pause()
            for move in ["e4", "e5", "Nf3", "Nc6"]:
                await type_text(pilot, move)
            assert [m.uci() for m in game(app).board.move_stack] == ["e2e4", "e7e5", "g1f3", "b8c6"]
            await type_text(pilot, "e5")  # illegal for white now? (pawn blocked) -> rejected
            assert len(game(app).board.move_stack) == 4
            await type_text(pilot, "undo")
            assert len(game(app).board.move_stack) == 3
    asyncio.run(scenario())


def test_mouse_click_move_and_promotion_dialog():
    async def scenario():
        app = ChessApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(GameScreen(mode="local"))
            await pilot.pause()
            scr = game(app)
            cw, ch = scr.view.cell  # big cells here: 7x3, left margin 2, white at bottom -> e2 is col 4, row 6
            await pilot.click(BoardView, offset=(2 + 4 * cw + 2, 6 * ch + 1))
            assert scr.view.selected == chess.E2 and chess.E4 in scr.view.targets
            await pilot.click(BoardView, offset=(2 + 4 * cw + 2, 4 * ch + 1))
            assert scr.board.peek() == chess.Move.from_uci("e2e4")

            scr.board.set_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1")
            scr.refresh_ui()
            await pilot.click(BoardView, offset=(2 + 2, 1 * ch + 1))  # a7
            await pilot.click(BoardView, offset=(2 + 2, 1))  # a8
            await pilot.press("n")
            await pilot.pause()
            assert scr.board.peek().promotion == chess.KNIGHT
    asyncio.run(scenario())


def test_keyboard_cursor_and_typing_redirect():
    async def scenario():
        app = ChessApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(GameScreen(mode="local"))
            await pilot.pause()
            scr = game(app)
            await pilot.press("tab")  # focus board; cursor starts at e2
            await pilot.press("enter", "up", "up", "enter")
            await pilot.pause()
            assert scr.board.peek() == chess.Move.from_uci("e2e4")
            await pilot.press("N", "f", "6")  # typing on the board jumps to the move box
            await pilot.press("enter")
            await pilot.pause()
            assert scr.board.peek() == chess.Move.from_uci("g8f6")
    asyncio.run(scenario())


def test_game_end_and_resign():
    async def scenario():
        app = ChessApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(GameScreen(mode="local"))
            await pilot.pause()
            for move in ["f3", "e5", "g4", "Qh4"]:
                await type_text(pilot, move)
            assert game(app).result == "Black wins by checkmate."
            await type_text(pilot, "e4")  # no moves after game over
            assert len(game(app).board.move_stack) == 4
    asyncio.run(scenario())


def test_versus_engine(monkeypatch):
    fake = Path(__file__).with_name("fake_uci.py")
    monkeypatch.setattr("chesscli.app.config.stockfish_path", lambda: [sys.executable, str(fake)])

    async def scenario():
        app = ChessApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(GameScreen(mode="engine", color="white", skill=2))
            await pilot.pause()
            await type_text(pilot, "e4")
            for _ in range(50):
                if len(game(app).board.move_stack) == 2:
                    break
                await asyncio.sleep(0.1)
            assert len(game(app).board.move_stack) == 2 and game(app).board.turn == chess.WHITE
            await type_text(pilot, "undo")
            assert len(game(app).board.move_stack) == 0
    asyncio.run(scenario())


def test_online_game_through_real_server():
    """The real GameScreen as host, a raw websocket as the opponent."""
    async def wait_for(cond):
        for _ in range(100):
            if cond():
                return
            await asyncio.sleep(0.05)
        raise AssertionError("timed out")

    async def scenario():
        async with serve(Server().handler, "localhost", 0) as srv:
            url = f"ws://localhost:{srv.sockets[0].getsockname()[1]}"
            app = ChessApp()
            async with app.run_test(size=(120, 40)) as pilot:
                await app.push_screen(GameScreen(mode="create", server=url))
                await wait_for(lambda: "Game code" in str(game(app).query_one("#status").render()))
                code = str(game(app).query_one("#status").render()).split("Game code: ")[1][:4]

                opp = await connect(url)
                await opp.send(json.dumps({"t": "join", "code": code}))
                start = await recv(opp, "start")
                await wait_for(lambda: game(app).started)
                me_white = game(app).my_color
                assert start["color"] == ("black" if me_white else "white")

                if not me_white:  # opponent (white) opens
                    await opp.send(json.dumps({"t": "move", "uci": "e2e4"}))
                    await wait_for(lambda: len(game(app).board.move_stack) == 1)
                await type_text(pilot, "e5" if not me_white else "e4")
                mine = "e7e5" if not me_white else "e2e4"
                while (await recv(opp, "move"))["uci"] != mine:  # server echoes both players' moves
                    pass
                await wait_for(lambda: len(game(app).board.move_stack) == 2 or me_white)
                assert game(app).board.peek().uci() == mine

                await type_text(pilot, "resign")
                over = await recv(opp, "over")
                assert over["reason"] == "resignation"
                await wait_for(lambda: game(app).result and "wins" in game(app).result)
            await opp.close()
    asyncio.run(scenario())


def test_menu_buttons_start_games():
    async def scenario():
        app = ChessApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#local")
            await pilot.pause()
            assert isinstance(app.screen, GameScreen) and app.screen.mode == "local"
            await type_text(pilot, "menu")
            assert not isinstance(app.screen, GameScreen)
    asyncio.run(scenario())
