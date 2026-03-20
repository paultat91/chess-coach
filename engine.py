"""
Stockfish engine wrapper using python-chess.
"""

import chess
import chess.engine

STOCKFISH_PATH = "/usr/games/stockfish"


def open_engine(threads: int = 2, hash_mb: int = 128) -> chess.engine.SimpleEngine:
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    engine.configure({"Threads": threads, "Hash": hash_mb})
    return engine


def set_strength(engine: chess.engine.SimpleEngine, elo: int) -> None:
    """Limit engine strength to a given Elo rating (1320–3190)."""
    engine.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})


def get_best_move(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    time_limit: float = 1.0,
) -> chess.Move:
    result = engine.play(board, chess.engine.Limit(time=time_limit))
    return result.move


def analyse(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    depth: int = 20,
) -> dict:
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    score = info["score"].white()

    return {
        "score": score,
        "score_str": str(score),
        "depth": info.get("depth"),
        "pv": [m.uci() for m in info.get("pv", [])],
        "nodes": info.get("nodes"),
    }
