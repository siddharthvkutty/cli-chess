"""Minimal UCI engine for tests: always plays the first legal move. Stands in for Stockfish."""
import sys

import chess

board = chess.Board()
for line in sys.stdin:
    parts = line.split()
    if not parts:
        continue
    cmd = parts[0]
    if cmd == "uci":
        print("id name FakeFish\noption name Skill Level type spin default 20 min 0 max 20\nuciok", flush=True)
    elif cmd == "isready":
        print("readyok", flush=True)
    elif cmd == "position":
        if parts[1] == "startpos":
            board = chess.Board()
            rest = parts[3:] if "moves" in parts else []
        else:
            i = parts.index("moves") if "moves" in parts else len(parts)
            board = chess.Board(" ".join(parts[2:i]))
            rest = parts[i + 1:]
        for uci in rest:
            board.push_uci(uci)
    elif cmd == "go":
        print(f"bestmove {next(iter(board.legal_moves)).uci()}", flush=True)
    elif cmd == "quit":
        break
