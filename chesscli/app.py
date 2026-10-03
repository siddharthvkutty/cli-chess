"""Textual UI: menu screen and game screen (local, vs engine, online)."""
from pathlib import Path

import chess
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static

from . import config
from .board_view import BoardView
from .core import MoveError, describe_outcome, parse_move, save_pgn
from .engine import Engine
from .net import NetClient

HELP = (
    "Type a move (e4, Nf3, O-O, e8=Q, e2e4) or click/arrow-select squares.\n"
    "Commands: undo, flip, resign, draw, decline, save, menu, help"
)


class PromotionScreen(ModalScreen[int]):
    BINDINGS = [Binding(k, f"pick('{k}')", show=False) for k in "qrbn"]
    DEFAULT_CSS = """
    PromotionScreen { align: center middle; }
    PromotionScreen > Vertical { width: 36; height: auto; padding: 1 2; background: $surface; border: thick $primary; }
    """
    PIECES = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Promote to: (Q)ueen  (R)ook  (B)ishop  k(N)ight")

    def action_pick(self, key: str) -> None:
        self.dismiss(self.PIECES[key])


class MenuScreen(Screen):
    DEFAULT_CSS = """
    MenuScreen { align: center middle; }
    MenuScreen > VerticalScroll { width: 60; height: auto; max-height: 100%; padding: 0 2; }
    MenuScreen Button, MenuScreen Input, MenuScreen Select { margin-bottom: 1; width: 100%; }
    #title { text-style: bold; margin-bottom: 1; }
    """

    def compose(self) -> ComposeResult:
        has_engine = config.stockfish_path() is not None
        with VerticalScroll():
            yield Label("♚ cli-chess", id="title")
            yield Button("Local game (two players, one keyboard)", id="local", variant="primary")
            yield Button(
                "Play vs Stockfish" if has_engine else "Play vs Stockfish (not installed - see README)",
                id="engine", disabled=not has_engine,
            )
            yield Select([("Play as White", "white"), ("Play as Black", "black"), ("Random color", "random")],
                         value="white", allow_blank=False, id="color")
            yield Select([(f"Stockfish skill {n}" + (" (weakest)" if n == 0 else " (strongest)" if n == 20 else ""), n)
                          for n in range(0, 21)], value=8, allow_blank=False, id="skill")
            yield Input(value=config.load().get("server_url", config.DEFAULT_SERVER), id="server",
                        placeholder="server URL, e.g. wss://xyz.trycloudflare.com")
            yield Button("Online: create game", id="create")
            yield Input(placeholder="game code", id="code", max_length=4)
            yield Button("Online: join game", id="join")
            yield Button("Quit", id="quit")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "quit":
            self.app.exit()
            return
        server = self.query_one("#server", Input).value
        options = {}
        if bid == "engine":
            options = {"color": self.query_one("#color", Select).value,
                       "skill": self.query_one("#skill", Select).value}
        elif bid in ("create", "join"):
            config.save(server_url=server)
            options = {"server": server, "code": self.query_one("#code", Input).value}
        self.app.push_screen(GameScreen(mode=bid, ascii_only=self.app.ascii_only, **options))


class GameScreen(Screen):
    BINDINGS = [Binding("tab", "toggle_focus", "Board/Move box"), Binding("ctrl+b", "leave", "Back to menu")]
    DEFAULT_CSS = """
    #main { height: 1fr; }
    #side { width: 34; padding: 0 2; }
    #status { height: auto; margin-bottom: 1; text-style: bold; }
    #moves-box { height: 1fr; border: round $primary-darken-2; padding: 0 1; }
    #message { height: auto; color: $warning; }
    #move-input { dock: bottom; }
    BoardView { margin: 1 2; }
    """

    def __init__(self, mode: str, ascii_only=False, color="white", skill=8, server="", code=""):
        super().__init__()
        self.mode = mode  # local | engine | create | join
        self.online = mode in ("create", "join")
        self.ascii_only = ascii_only
        self.board = chess.Board()
        self.result: str | None = None
        self.skill = skill
        self.server, self.code = server, code
        self.my_color: bool | None = None
        if mode == "engine":
            import random
            self.my_color = {"white": True, "black": False}.get(color, random.choice([True, False]))
        self.engine: Engine | None = None
        self.net: NetClient | None = None
        self.thinking = False
        self.started = mode in ("local", "engine")
        self.status_text = ""
        self.draw_pending = False
        self.closing = False

    # --- layout ---------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield BoardView(self.board, self.ascii_only)
            with Vertical(id="side"):
                yield Static(id="status")
                with VerticalScroll(id="moves-box"):
                    yield Static(id="moves")
                yield Static(HELP, id="message")
        yield Input(placeholder="Your move (e4, Nf3, O-O...) or a command (help)", id="move-input",
                    select_on_focus=False)
        yield Footer()

    @property
    def view(self) -> BoardView:
        return self.query_one(BoardView)

    async def on_mount(self) -> None:
        self.query_one("#move-input").focus()
        if self.mode == "engine":
            self.view.orientation = self.my_color
            self.engine = Engine(config.stockfish_path(), self.skill)
            try:
                await self.engine.start()
            except Exception as e:  # engine missing/crashed: back to menu rather than a broken game
                self.app.notify(f"Could not start Stockfish: {e}", severity="error")
                self.app.pop_screen()
                return
        elif self.online:
            self.run_worker(self.net_session(), exclusive=True)
        self.refresh_ui()
        self.maybe_engine_move()

    async def on_unmount(self) -> None:
        self.closing = True
        if self.engine:
            await self.engine.close()
        if self.net:
            await self.net.close()

    # --- state / display ------------------------------------------------------------------
    def can_move_now(self) -> bool:
        if self.result or not self.started or self.thinking:
            return False
        return self.my_color is None or self.board.turn == self.my_color

    def refresh_ui(self) -> None:
        self.view.last_move = self.board.peek() if self.board.move_stack else None
        self.view.selected, self.view.targets = None, set()
        self.view.refresh()
        moves = self.board.root().variation_san(self.board.move_stack) if self.board.move_stack else "(no moves yet)"
        self.query_one("#moves", Static).update(moves)
        self.query_one("#moves-box").scroll_end(animate=False)
        self.query_one("#status", Static).update(self.status())
        self.sub_title = {"local": "Local game", "engine": f"vs Stockfish (skill {self.skill})",
                          "create": "Online", "join": "Online"}[self.mode]

    def status(self) -> str:
        if self.status_text and not self.started:
            return self.status_text
        if self.result:
            return self.result
        side = "White" if self.board.turn else "Black"
        mine = "" if self.my_color is None else (" (you)" if self.board.turn == self.my_color else " (opponent)")
        note = "  CHECK!" if self.board.is_check() else ""
        you = ""
        if self.my_color is not None:
            you = f"You are {'White' if self.my_color else 'Black'}\n"
        return f"{you}{side} to move{mine}{note}" + ("\nThinking..." if self.thinking else "") + (
            "\nOpponent offers a draw: type 'draw' to accept" if self.draw_pending else "")

    def say(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def end_game(self, text: str) -> None:
        self.result = text
        self.refresh_ui()

    # --- making moves ---------------------------------------------------------------------
    async def submit_move(self, move: chess.Move) -> None:
        """A move chosen by the local human (typed or clicked)."""
        if self.online:
            await self.net.send(t="move", uci=move.uci())  # applied when the server echoes it back
        else:
            self.apply_move(move)

    def apply_move(self, move: chess.Move) -> None:
        self.board.push(move)
        self.draw_pending = False
        if not self.online and (outcome := self.board.outcome(claim_draw=True)):
            self.end_game(describe_outcome(outcome))
        else:
            self.refresh_ui()
        self.maybe_engine_move()

    def maybe_engine_move(self) -> None:
        if self.mode == "engine" and not self.result and self.board.turn != self.my_color and not self.thinking:
            self.thinking = True
            self.refresh_ui()
            self.run_worker(self.engine_move(), exclusive=True)

    async def engine_move(self) -> None:
        try:
            move = await self.engine.best_move(self.board, seconds=0.5)
        except Exception as e:
            self.thinking = False
            self.app.notify(f"Engine error: {e}", severity="error")
            return
        self.thinking = False
        self.apply_move(move)

    # --- typed input ----------------------------------------------------------------------
    @on(Input.Submitted, "#move-input")
    async def typed(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        command = text.lower()
        if command in COMMANDS:
            await getattr(self, f"cmd_{command}")()
            return
        if not self.can_move_now():
            self.say("Not your turn." if self.started and not self.result else "No move can be made right now.")
            return
        try:
            move = parse_move(self.board, text)
        except MoveError as e:
            self.say(str(e))
            return
        self.say("")
        await self.submit_move(move)

    # --- mouse / cursor input -------------------------------------------------------------
    @on(BoardView.Cleared)
    def cleared(self) -> None:
        self.view.selected, self.view.targets = None, set()
        self.view.refresh()

    @on(BoardView.SquareChosen)
    async def square_chosen(self, event: BoardView.SquareChosen) -> None:
        sq, view = event.square, self.view
        if not self.can_move_now():
            return
        if view.selected is not None and sq in view.targets:
            moves = [m for m in self.board.legal_moves if m.from_square == view.selected and m.to_square == sq]
            if moves[0].promotion:
                self.app.push_screen(PromotionScreen(), lambda piece, ms=moves: self.run_worker(
                    self.submit_move(next(m for m in ms if m.promotion == piece))))
            else:
                await self.submit_move(moves[0])
            return
        piece = self.board.piece_at(sq)
        if piece and piece.color == self.board.turn:
            view.selected = sq
            view.targets = {m.to_square for m in self.board.legal_moves if m.from_square == sq}
        else:
            view.selected, view.targets = None, set()
        view.refresh()

    # --- commands -------------------------------------------------------------------------
    async def cmd_help(self) -> None:
        self.say(HELP)

    async def cmd_flip(self) -> None:
        self.view.orientation = not self.view.orientation
        self.view.refresh()

    async def cmd_undo(self) -> None:
        if self.online or self.thinking:
            self.say("Undo isn't available right now.")
            return
        pops = 1 if self.mode == "local" or self.board.turn != self.my_color else 2
        if len(self.board.move_stack) < pops:
            self.say("Nothing to undo.")
            return
        for _ in range(pops):
            self.board.pop()
        self.result = None
        self.refresh_ui()

    async def cmd_resign(self) -> None:
        if self.result or not self.started:
            return
        if self.online:
            await self.net.send(t="resign")
        elif self.mode == "engine":
            self.end_game(f"You resigned. {'Black' if self.my_color else 'White'} wins.")
        else:
            self.end_game(f"{'White' if self.board.turn else 'Black'} resigned. "
                          f"{'Black' if self.board.turn else 'White'} wins.")

    async def cmd_draw(self) -> None:
        if self.result or not self.started:
            return
        if self.online:
            await self.net.send(t="draw")
            self.say("Draw offered." if not self.draw_pending else "")
        elif self.mode == "engine":
            self.say("Stockfish doesn't accept draw offers.")
        else:
            self.end_game("Draw by agreement.")

    async def cmd_decline(self) -> None:
        if self.online and self.draw_pending:
            self.draw_pending = False
            await self.net.send(t="decline")
            self.refresh_ui()

    async def cmd_save(self) -> None:
        path = save_pgn(self.board, Path.cwd())
        self.say(f"Saved {path}")

    async def cmd_menu(self) -> None:
        await self.action_leave()

    async def action_leave(self) -> None:
        self.app.pop_screen()

    def action_toggle_focus(self) -> None:
        box = self.query_one("#move-input")
        (self.view if box.has_focus else box).focus()

    # --- online ---------------------------------------------------------------------------
    async def net_session(self) -> None:
        self.status_text = f"Connecting to {self.server} ..."
        self.refresh_ui()
        try:
            self.net = await NetClient.open(self.server)
        except Exception as e:
            self.app.notify(f"Could not connect: {e}", severity="error")
            self.app.pop_screen()
            return
        await self.net.send(t="create") if self.mode == "create" else await self.net.send(t="join", code=self.code)
        async for msg in self.net.messages():
            self.handle_net(msg)
        if not self.result and not self.closing:
            self.end_game("Disconnected from server.")

    def handle_net(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "created":
            self.status_text = f"Game code: {msg['code']}\nWaiting for opponent to join..."
            self.say(f"Tell your opponent to join with code {msg['code']}.")
        elif kind == "start":
            self.my_color = msg["color"] == "white"
            self.view.orientation = self.my_color
            self.started = True
            self.say("Game started. " + HELP.splitlines()[0])
        elif kind == "move":
            self.apply_move(chess.Move.from_uci(msg["uci"]))
            return
        elif kind == "over":
            reasons = {"1-0": "White wins", "0-1": "Black wins", "1/2-1/2": "Draw"}
            self.end_game(f"{reasons.get(msg['result'], msg['result'])} by {msg['reason']}.")
            return
        elif kind == "draw_offered":
            self.draw_pending = True
            self.say("Your opponent offers a draw. Type 'draw' to accept or 'decline'.")
        elif kind == "draw_declined":
            self.say("Your draw offer was declined.")
        elif kind == "opponent_left":
            self.end_game("Your opponent left the game.")
            return
        elif kind == "error":
            if not self.started:
                self.app.notify(msg.get("msg", "Server error"), severity="error")
                self.app.pop_screen()
                return
            self.say(msg.get("msg", "Server error"))
        self.refresh_ui()


COMMANDS = {n[4:] for n in dir(GameScreen) if n.startswith("cmd_")}


class ChessApp(App):
    TITLE = "cli-chess"

    def __init__(self, ascii_only: bool = False):
        super().__init__()
        self.ascii_only = ascii_only

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())
