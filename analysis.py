import io
import math
import statistics

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


def cp_to_win_percent(cp_white: float) -> float:
    """Convert centipawns (from White's POV) to win% for White (0–100).

    Based on Lichess's empirically-derived sigmoid, which maps engine evals
    to real winning chances.  This is position-aware: the curve flattens near
    0% and 100%, so huge cp swings in already-decided positions produce only
    tiny win% changes — preventing the "best move = blunder" artifact.
    """
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp_white)) - 1.0)


def classify_move(win_loss: float) -> str:
    """Classify a move by the Win% lost (always >= 0, caller's perspective)."""
    if win_loss <= 2:
        return "best"
    if win_loss <= 5:
        return "good"
    if win_loss <= 10:
        return "inaccuracy"
    if win_loss <= 20:
        return "mistake"
    return "blunder"


def move_accuracy(win_loss: float) -> float:
    """Lichess accuracy formula: 0–100 from win-percent loss.

    The original Lichess equation takes a Win% *drop* as input (not raw cp).
    103.1668 * exp(-0.04354 * win_loss) - 3.1669, clamped to [0, 100].
    """
    acc = 103.1668 * math.exp(-0.04354 * max(0.0, win_loss)) - 3.1669
    return round(max(0.0, min(100.0, acc)), 1)


def game_accuracy(moves: list) -> float:
    """Lichess-style game accuracy: average of harmonic mean and
    volatility-weighted mean of per-move accuracy scores.

    Simple arithmetic mean is misleading: a few 100% moves can mask a
    catastrophic blunder.  The harmonic mean penalises bad moves strongly;
    the volatility-weighted mean concentrates on critical (swinging)
    moments.  Their average closely matches Lichess / Chess.com figures.

    Each element of `moves` must have keys: 'accuracy', 'eval_before', 'color'.
    """
    if not moves:
        return 0.0
    accs = [m["accuracy"] for m in moves]
    n = len(accs)

    # Harmonic mean (heavily penalises single poor moves)
    harmonic = n / sum(1.0 / max(a, 0.1) for a in accs)

    # Volatility-weighted mean — critical/swinging positions count more.
    window = max(3, int(math.sqrt(n)))
    is_white = moves[0]["color"] == "white"
    vols = []
    for i in range(n):
        start = max(0, i - window // 2)
        end   = min(n, start + window)
        chunk_evals = [moves[j]["eval_before"] for j in range(start, end)]
        if is_white:
            chunk_wins = [cp_to_win_percent(e) for e in chunk_evals]
        else:
            chunk_wins = [100.0 - cp_to_win_percent(e) for e in chunk_evals]
        vols.append(statistics.stdev(chunk_wins) if len(chunk_wins) > 1 else 1.0)

    total_vol = sum(vols) or 1.0
    vol_weighted = sum(accs[i] * vols[i] for i in range(n)) / total_vol

    return round((harmonic + vol_weighted) / 2.0, 1)


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

            # Evaluate the position before the move — ask for top 3 candidates
            infos = engine.analyse(
                board, chess.engine.Limit(time=ANALYSIS_TIME), multipv=3
            )
            # multipv=3 always returns a list; normalise to list
            if isinstance(infos, dict):
                infos = [infos]
            info_before = infos[0]
            eval_before_cp = score_to_cp(info_before["score"])
            pv = info_before.get("pv", [])
            best_move = pv[0] if pv else None
            best_move_uci = best_move.uci() if best_move else None
            best_move_san = board.san(best_move) if best_move else None

            # Build top-3 candidate list
            candidates = []
            for info in infos:
                c_pv = info.get("pv", [])
                if not c_pv:
                    continue
                c_move = c_pv[0]
                candidates.append({
                    "uci": c_move.uci(),
                    "san": board.san(c_move),
                    "eval_cp": round(score_to_cp(info["score"]), 1),
                    "eval_str": format_eval(score_to_cp(info["score"])),
                })

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

            # Win% loss from the mover's perspective.
            # Using Win% (not raw cp) makes the metric position-independent:
            # a 500 cp swing when already losing by 1000 cp barely moves Win%,
            # so deeply losing positions don't produce phantom "blunders".
            win_before = cp_to_win_percent(eval_before_cp)
            win_after  = cp_to_win_percent(eval_after_cp)

            played_is_best = (best_move_uci is not None and move.uci() == best_move_uci)
            if is_forced or played_is_best:
                win_loss = 0.0
            elif color == chess.WHITE:
                win_loss = max(0.0, win_before - win_after)
            else:
                # For black, higher cp = worse, so win% for Black = 100 - win_white
                win_before_black = 100.0 - win_before
                win_after_black  = 100.0 - win_after
                win_loss = max(0.0, win_before_black - win_after_black)

            # Keep cp_loss stored for display purposes (eval graph, etc.)
            if is_forced or played_is_best:
                cp_loss = 0.0
            elif color == chess.WHITE:
                cp_loss = max(0.0, eval_before_cp - eval_after_cp)
            else:
                cp_loss = max(0.0, eval_after_cp - eval_before_cp)

            classification = classify_move(win_loss)
            accuracy = move_accuracy(win_loss)

            moves_data.append(
                {
                    "move_idx": move_idx,
                    "candidates": candidates,
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

    def count_cls(moves, cls):
        return sum(1 for m in moves if m["classification"] == cls)

    critical_idx = (
        max(range(len(moves_data)), key=lambda i: moves_data[i]["cp_loss"])
        if moves_data
        else 0
    )

    stats = {
        "white_accuracy": game_accuracy(white_moves),
        "black_accuracy": game_accuracy(black_moves),
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
