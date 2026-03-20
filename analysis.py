import io
import math

import chess
import chess.engine
import chess.pgn

STOCKFISH_PATH = "/usr/games/stockfish"
ANALYSIS_TIME = 0.3  # seconds per position


def score_to_cp(score: chess.engine.PovScore) -> float:
    """Always returns centipawns from White's perspective."""
    white = score.white()
    if white.is_mate():
        m = white.mate()
        # Mate in N → large value; further mates are slightly smaller
        return (10000 - abs(m)) * (1 if m > 0 else -1)
    val = white.score()
    return float(val) if val is not None else 0.0


def classify_move(cp_loss: float) -> str:
    if cp_loss <= 10:
        return "best"
    if cp_loss <= 25:
        return "good"
    if cp_loss <= 60:
        return "inaccuracy"
    if cp_loss <= 100:
        return "mistake"
    return "blunder"


def move_accuracy(cp_loss: float) -> float:
    """Lichess accuracy formula: 0–100 from centipawn loss."""
    acc = 103.1668 * math.exp(-0.04354 * max(0.0, cp_loss)) - 3.1669
    return round(max(0.0, min(100.0, acc)), 1)


def format_eval(cp: float) -> str:
    if cp >= 9000:
        return f"+M{10000 - int(cp)}"
    if cp <= -9000:
        return f"-M{10000 + int(cp)}"
    pawns = cp / 100
    return f"{pawns:+.2f}"


def analyse_game(pgn_text: str) -> dict:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Invalid PGN")

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    engine.configure({"Threads": 2, "Hash": 128})

    board = game.board()
    moves_data = []

    try:
        for move_idx, move in enumerate(game.mainline_moves()):
            fen_before = board.fen()
            color = board.turn
            move_number = board.fullmove_number
            legal_moves = list(board.legal_moves)
            is_forced = len(legal_moves) == 1
            san = board.san(move)

            # Evaluate the position before the move
            info_before = engine.analyse(
                board, chess.engine.Limit(time=ANALYSIS_TIME)
            )
            eval_before_cp = score_to_cp(info_before["score"])
            pv = info_before.get("pv", [])
            best_move = pv[0] if pv else None
            best_move_uci = best_move.uci() if best_move else None
            best_move_san = board.san(best_move) if best_move else None

            # Play the actual move
            board.push(move)
            fen_after = board.fen()

            # Evaluate the resulting position
            if board.is_game_over():
                eval_after_cp = eval_before_cp
            else:
                info_after = engine.analyse(
                    board, chess.engine.Limit(time=ANALYSIS_TIME)
                )
                eval_after_cp = score_to_cp(info_after["score"])

            # Centipawn loss from the mover's perspective
            played_is_best = (best_move_uci is not None and move.uci() == best_move_uci)
            if is_forced or played_is_best:
                cp_loss = 0.0
            elif color == chess.WHITE:
                cp_loss = max(0.0, eval_before_cp - eval_after_cp)
            else:
                cp_loss = max(0.0, eval_after_cp - eval_before_cp)

            classification = classify_move(cp_loss)
            accuracy = move_accuracy(cp_loss)

            moves_data.append(
                {
                    "move_idx": move_idx,
                    "move_number": move_number,
                    "color": "white" if color == chess.WHITE else "black",
                    "uci": move.uci(),
                    "san": san,
                    "fen_before": fen_before,
                    "fen_after": fen_after,
                    "eval_before": round(eval_before_cp, 1),
                    "eval_after": round(eval_after_cp, 1),
                    "eval_before_str": format_eval(eval_before_cp),
                    "eval_after_str": format_eval(eval_after_cp),
                    "best_move_uci": best_move_uci,
                    "best_move_san": best_move_san,
                    "cp_loss": round(cp_loss, 1),
                    "classification": classification,
                    "accuracy": accuracy,
                    "is_forced": is_forced,
                }
            )
    finally:
        engine.quit()

    white_moves = [m for m in moves_data if m["color"] == "white"]
    black_moves = [m for m in moves_data if m["color"] == "black"]

    def avg_acc(moves):
        return round(sum(m["accuracy"] for m in moves) / len(moves), 1) if moves else 0.0

    def count_cls(moves, cls):
        return sum(1 for m in moves if m["classification"] == cls)

    critical_idx = (
        max(range(len(moves_data)), key=lambda i: moves_data[i]["cp_loss"])
        if moves_data
        else 0
    )

    stats = {
        "white_accuracy": avg_acc(white_moves),
        "black_accuracy": avg_acc(black_moves),
        "white_blunders": count_cls(white_moves, "blunder"),
        "black_blunders": count_cls(black_moves, "blunder"),
        "white_mistakes": count_cls(white_moves, "mistake"),
        "black_mistakes": count_cls(black_moves, "mistake"),
        "white_inaccuracies": count_cls(white_moves, "inaccuracy"),
        "black_inaccuracies": count_cls(black_moves, "inaccuracy"),
        "critical_move_idx": critical_idx,
        "critical_cp_loss": moves_data[critical_idx]["cp_loss"] if moves_data else 0.0,
    }

    return {"moves": moves_data, "stats": stats}
