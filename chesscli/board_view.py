"""Board widget: renders the position, handles mouse clicks and keyboard-cursor selection."""
import chess
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget

GLYPHS = {"K": "♚", "Q": "♛", "R": "♜", "B": "♝", "N": "♞", "P": "♟"}
LIGHT, DARK = "#d2b48c", "#7b5b3f"
LAST_LIGHT, LAST_DARK = "#cdd26a", "#aaa23a"
SELECTED, CURSOR, TARGET_CAPTURE, CHECK = "#f6f669", "#6aa84f", "#d9776b", "#e03c31"
LEFT_MARGIN = 2


class BoardView(Widget, can_focus=True):
    BINDINGS = [
        Binding("up", "cursor(0,1)", show=False),
        Binding("down", "cursor(0,-1)", show=False),
        Binding("left", "cursor(-1,0)", show=False),
        Binding("right", "cursor(1,0)", show=False),
        Binding("enter,space", "choose", "Select square", show=False),
        Binding("escape", "clear", show=False),
    ]
    DEFAULT_CSS = "BoardView { width: auto; height: auto; }"

    class SquareChosen(Message):
        def __init__(self, square: int):
            super().__init__()
            self.square = square

    class Cleared(Message):
        pass

    def __init__(self, board: chess.Board, ascii_only: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.board = board
        self.ascii_only = ascii_only
        self.orientation = chess.WHITE  # color at the bottom
        self.selected: int | None = None
        self.targets: set[int] = set()
        self.cursor = chess.E2
        self.last_move: chess.Move | None = None

    # --- geometry -------------------------------------------------------------------------
    @property
    def cell(self) -> tuple[int, int]:
        """(width, height) of a square: big on roomy terminals, compact otherwise."""
        size = self.app.size
        return (7, 3) if size.height >= 34 and size.width >= 90 else (3, 1)

    def get_content_width(self, container, viewport) -> int:
        return LEFT_MARGIN + 8 * self.cell[0]

    def get_content_height(self, container, viewport, width) -> int:
        return 8 * self.cell[1] + 1

    def _square_at(self, col: int, row: int) -> int:
        file, rank = (col, 7 - row) if self.orientation == chess.WHITE else (7 - col, row)
        return chess.square(file, rank)

    # --- rendering ------------------------------------------------------------------------
    def _bg(self, sq: int) -> str:
        light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
        piece = self.board.piece_at(sq)
        if self.board.is_check() and piece == chess.Piece(chess.KING, self.board.turn):
            return CHECK
        if sq == self.selected:
            return SELECTED
        if self.has_focus and sq == self.cursor:
            return CURSOR
        if sq in self.targets and piece:
            return TARGET_CAPTURE
        if self.last_move and sq in (self.last_move.from_square, self.last_move.to_square):
            return LAST_LIGHT if light else LAST_DARK
        return LIGHT if light else DARK

    def _symbol(self, sq: int) -> tuple[str, str]:
        piece = self.board.piece_at(sq)
        if piece is None:
            return ("•" if sq in self.targets else " "), "#3a3a3a"
        char = piece.symbol() if self.ascii_only else GLYPHS[piece.symbol().upper()]
        return char, ("#ffffff" if piece.color else "#000000")

    def render(self) -> Text:
        cw, ch = self.cell
        text = Text(no_wrap=True)
        for row in range(8):
            for line in range(ch):
                text.append(f"{(7 - row if self.orientation else row) + 1} " if line == ch // 2 else "  ",
                            style="dim")
                for col in range(8):
                    sq = self._square_at(col, row)
                    symbol, fg = self._symbol(sq)
                    body = symbol.center(cw) if line == ch // 2 else " " * cw
                    text.append(body, style=f"bold {fg} on {self._bg(sq)}")
                text.append("\n")
        files = "abcdefgh" if self.orientation == chess.WHITE else "hgfedcba"
        text.append(" " * LEFT_MARGIN + "".join(f.center(cw) for f in files), style="dim")
        return text

    # --- input ----------------------------------------------------------------------------
    def on_click(self, event: events.Click) -> None:
        cw, ch = self.cell
        col, row = (event.x - LEFT_MARGIN) // cw, event.y // ch
        if 0 <= col < 8 and 0 <= row < 8:
            self.cursor = self._square_at(col, row)
            self.post_message(self.SquareChosen(self.cursor))
            self.refresh()

    def on_key(self, event: events.Key) -> None:
        """Typing while the board is focused jumps to the move box, so typed moves always work."""
        if event.is_printable and event.character and event.key not in ("space", "enter"):
            box = self.screen.query_one("#move-input")
            box.focus()
            box.insert_text_at_cursor(event.character)
            event.stop()

    def action_cursor(self, dx: int, dy: int) -> None:
        sign = 1 if self.orientation == chess.WHITE else -1
        file = min(7, max(0, chess.square_file(self.cursor) + dx * sign))
        rank = min(7, max(0, chess.square_rank(self.cursor) + dy * sign))
        self.cursor = chess.square(file, rank)
        self.refresh()

    def action_choose(self) -> None:
        self.post_message(self.SquareChosen(self.cursor))

    def action_clear(self) -> None:
        self.post_message(self.Cleared())
