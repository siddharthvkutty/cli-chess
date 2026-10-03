"""Stockfish (or any UCI engine) via python-chess's asyncio API."""
import chess
import chess.engine


class Engine:
    def __init__(self, command: str | list[str], skill: int = 10):
        self.command = command
        self.skill = skill
        self._engine: chess.engine.UciProtocol | None = None

    async def start(self) -> None:
        _, self._engine = await chess.engine.popen_uci(self.command)
        if "Skill Level" in self._engine.options:
            await self._engine.configure({"Skill Level": self.skill})

    async def best_move(self, board: chess.Board, seconds: float = 0.5) -> chess.Move:
        result = await self._engine.play(board, chess.engine.Limit(time=seconds))
        return result.move

    async def close(self) -> None:
        if self._engine:
            try:
                await self._engine.quit()
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError):
                pass
            self._engine = None
