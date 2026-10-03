import chess
import pytest

from chesscli.core import MoveError, describe_outcome, parse_move, save_pgn
from chesscli.net import normalize_url


@pytest.mark.parametrize("text", ["e4", "e2e4", "e2-e4", "e2 e4", "E2E4"])
def test_pawn_move_formats(text):
    assert parse_move(chess.Board(), text) == chess.Move.from_uci("e2e4")


def test_piece_moves_and_lowercase_piece_letter():
    board = chess.Board()
    assert parse_move(board, "Nf3") == chess.Move.from_uci("g1f3")
    assert parse_move(board, "nf3") == chess.Move.from_uci("g1f3")


def test_castling_variants():
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert parse_move(board, "O-O") == chess.Move.from_uci("e1g1")
    assert parse_move(board, "0-0-0") == chess.Move.from_uci("e1c1")
    assert parse_move(board, "o-o") == chess.Move.from_uci("e1g1")


def test_promotion_defaults_to_queen_and_accepts_choice():
    board = chess.Board("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert parse_move(board, "a8=Q").promotion == chess.QUEEN
    assert parse_move(board, "a7a8").promotion == chess.QUEEN
    assert parse_move(board, "a7a8n").promotion == chess.KNIGHT
    assert parse_move(board, "a8=N").promotion == chess.KNIGHT


@pytest.mark.parametrize("text", ["", "e5", "e2e5", "Ke2", "zz", "Nf6"])
def test_illegal_input_raises_friendly_error(text):
    with pytest.raises(MoveError):
        parse_move(chess.Board(), text)


def test_ambiguous_move():
    board = chess.Board("4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1")  # knights on b1 and f3 both reach d2
    with pytest.raises(MoveError, match="ambiguous"):
        parse_move(board, "Nd2")
    assert parse_move(board, "Nbd2") == chess.Move.from_uci("b1d2")


def test_outcome_text():
    board = chess.Board()
    for san in ["f3", "e5", "g4", "Qh4#"]:
        board.push_san(san)
    assert describe_outcome(board.outcome()) == "Black wins by checkmate."


def test_save_pgn(tmp_path):
    board = chess.Board()
    board.push_san("e4")
    path = save_pgn(board, tmp_path)
    assert "1. e4" in path.read_text()


@pytest.mark.parametrize("given,expected", [
    ("localhost", "ws://localhost:8765"),
    ("ws://localhost:9000", "ws://localhost:9000"),
    ("https://abc.trycloudflare.com/", "wss://abc.trycloudflare.com"),
    ("abc.trycloudflare.com", "wss://abc.trycloudflare.com"),
    ("192.168.1.5", "ws://192.168.1.5:8765"),
])
def test_normalize_url(given, expected):
    assert normalize_url(given) == expected
