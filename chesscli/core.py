"""Pure game helpers: typed-move parsing, result text, PGN export. No I/O besides the PGN file."""
import re
from datetime import datetime
from pathlib import Path

import chess
import chess.pgn

UCI_RE = re.compile(r"([a-h][1-8])[\s-]?([a-h][1-8])([qrbn])?")
CASTLE_RE = re.compile(r"[0oO](-[0oO]){1,2}[+#]?")


class MoveError(ValueError):
    """The typed text isn't a legal move; the message is safe to show the user."""


def parse_move(board: chess.Board, text: str) -> chess.Move:
    """Accepts SAN (e4, Nf3, exd5, O-O, e8=Q, nf3) and coordinates (e2e4, e2-e4, e2 e4, e7e8q)."""
    t = text.strip()
    if not t:
        raise MoveError("Type a move like e4, Nf3, O-O or e2e4.")
    if CASTLE_RE.fullmatch(t):
        t = t.upper().replace("0", "O")

    if m := UCI_RE.fullmatch(t.lower()):
        move = chess.Move.from_uci("".join(g for g in m.groups() if g))
        piece = board.piece_at(move.from_square)
        if piece and piece.piece_type == chess.PAWN and chess.square_rank(move.to_square) in (0, 7):
            move.promotion = chess.Piece.from_symbol(m.group(3)).piece_type if m.group(3) else chess.QUEEN
        if board.is_legal(move):
            return move
        raise MoveError(f"{t} is not a legal move.")

    candidates = [t]
    if t[0] in "nbrqk":
        candidates.append(t[0].upper() + t[1:])
    error = None
    for cand in candidates:
        try:
            return board.parse_san(cand)
        except chess.AmbiguousMoveError:
            raise MoveError(f"{t} is ambiguous; say which piece, e.g. Nbd2.") from None
        except ValueError as e:
            error = e
    raise MoveError(f"{t} is not a legal move.") from error


def describe_outcome(outcome: chess.Outcome) -> str:
    who = {True: "White", False: "Black", None: None}[outcome.winner]
    reason = outcome.termination.name.replace("_", " ").lower()
    return f"{who} wins by {reason}." if who else f"Draw by {reason}."


def save_pgn(board: chess.Board, directory: Path, result: str | None = None) -> Path:
    game = chess.pgn.Game.from_board(board)
    now = datetime.now()
    game.headers["Event"] = "cli-chess game"
    game.headers["Date"] = now.strftime("%Y.%m.%d")
    if result:
        game.headers["Result"] = result
    path = directory / f"game-{now:%Y%m%d-%H%M%S}.pgn"
    path.write_text(str(game) + "\n", encoding="utf-8")
    return path
