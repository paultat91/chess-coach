"""
Chess starter — python-chess + Stockfish 16
"""

import chess
import chess.pgn
from engine import open_engine, analyse, get_best_move, set_strength


def demo_analysis():
    """Analyse a position and print the evaluation."""
    print("=== Position Analysis ===")
    engine = open_engine()

    board = chess.Board()

    # Play the Ruy Lopez opening
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    for san in moves:
        board.push_san(san)

    print(board)
    print(f"\nFEN: {board.fen()}")

    result = analyse(engine, board, depth=20)
    print(f"\nDepth:  {result['depth']}")
    print(f"Score:  {result['score_str']}  (from White's perspective)")
    print(f"Nodes:  {result['nodes']:,}")
    print(f"Best line: {' '.join(result['pv'][:6])}")

    engine.quit()


def demo_play_game():
    """Play a short game: engine vs engine at limited strength."""
    print("\n=== Engine vs Engine (1800 Elo, 8 moves) ===")
    engine = open_engine()
    set_strength(engine, elo=1800)

    board = chess.Board()
    game = chess.pgn.Game()
    game.headers["White"] = "Stockfish (1800)"
    game.headers["Black"] = "Stockfish (1800)"
    node = game

    for move_num in range(8):
        if board.is_game_over():
            break
        move = get_best_move(engine, board, time_limit=0.1)
        node = node.add_variation(move)
        board.push(move)
        side = "White" if move_num % 2 == 0 else "Black"
        print(f"  {move_num // 2 + 1}{'.' if side == 'White' else '...'} {board.peek().uci()}")

    print(f"\n{game}\n")
    print(board)

    engine.quit()


def demo_legal_moves():
    """Show legal moves from the starting position."""
    print("\n=== Legal Moves from Starting Position ===")
    board = chess.Board()
    legal = list(board.legal_moves)
    print(f"Total legal moves: {len(legal)}")
    print("Moves:", ", ".join(board.san(m) for m in legal))


if __name__ == "__main__":
    demo_legal_moves()
    demo_analysis()
    demo_play_game()
