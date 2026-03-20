# chess-coach

A personal chess analysis web app powered by [Stockfish](https://stockfishchess.org/) and [python-chess](https://python-chess.readthedocs.io/).

Import games, analyse them move-by-move, and review them with an interactive board — complete with arrow overlays for the last move played, the engine's best move, the full principal variation, and the moves that were actually played.

## Features

- **Import PGN files** or **sync automatically from Chess.com**
- **Move-by-move Stockfish analysis** — classifies every move as Best / Good / Inaccuracy / Mistake / Blunder
- **Interactive board** with:
  - Yellow highlights for the last move played
  - Green arrow for the engine's best move
  - Orange arrows for the principal variation (engine's expected line)
  - Blue arrows for the actually-played future moves
- **Eval bar** and centipawn loss per move
- **Opening detection** — ECO code → human-readable name
- **Player-centric stats** — win/loss/draw record, accuracy, opening performance from your perspective
- **Search, filter & sort** the game list by result, colour, time control, date, and accuracy
- **Game termination badges** — checkmate, resignation, time, forfeit, and all draw types

## Requirements

- Python 3.10+
- [Stockfish](https://stockfishchess.org/download/) installed (`/usr/games/stockfish` on Ubuntu/Debian)
- See `requirements.txt` for Python dependencies

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Stockfish (Ubuntu/Debian)
sudo apt install stockfish

# Run the app
python app.py
```

Then open [http://localhost:5000](http://localhost:5000) in your browser.

## First steps

1. Open **⚙ Settings** in the navbar and enter your Chess.com username.
2. Click **⟳ Sync Chess.com** to import your recent games.
3. Click a game, then **Analyse Game** to run Stockfish on it.
4. Navigate moves with the arrow keys or the on-screen buttons.
5. Use the overlay toggles below the board to visualise the engine's suggestions.
