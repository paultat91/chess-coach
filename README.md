# chess-coach

A personal chess analysis web app powered by [Stockfish](https://stockfishchess.org/) and [python-chess](https://python-chess.readthedocs.io/).

Import games from Chess.com (or a PGN file), run Stockfish analysis move-by-move, then review each game on an interactive board with rich visual overlays and detailed statistics.

---

## Features

### Game Import & Sync
- **Sync from Chess.com** — fetches your recent games automatically via the public API
- **Import PGN files** — drag-and-drop or upload any PGN

### Stockfish Analysis
- **Move-by-move evaluation** using Win% (not raw centipawns), so classifications are position-independent
- **Move classification** — Best / Good / Inaccuracy / Mistake / Blunder, based on Win% drop thresholds matching Lichess's methodology
- **Per-move accuracy score** and **game accuracy** calculated with a Lichess-style formula (average of harmonic mean and volatility-weighted mean)
- **Critical moments** flagged automatically (large swings in evaluation)

### Interactive Board Review
- **Yellow highlights** — last move played
- **Green arrow** — engine's best move
- **Orange arrows** — principal variation (engine's expected line), depth controlled by slider
- **Blue arrows** — actually played future moves, depth controlled by slider (defaults to 1)
- **Eval bar** — live colour-coded evaluation bar beside the board
- **Evaluation graph** — click or tap to jump to any position; `touch-action: none` prevents accidental page scroll
- **Tap to navigate on mobile** — tap the right half of the board to advance, left half to go back

### Game Detail
- **Opening name** — ECO code mapped to a full human-readable name
- **Clock time per move** — displayed in the move list and detail panel
- **Time-pressure flag** — ⚡ highlights moves played with ≤ 10 seconds remaining
- **Game termination badges** — Checkmate, Resignation, Time, Forfeit, and all draw types (Agreement, Stalemate, Repetition, 50-move, Insufficient Material)
- **Time control label** — Bullet / Blitz / Rapid / Classical / Daily

### Stats & Progress
- **Player-centric stats** — all win/loss/draw records and accuracy from your perspective
- **Opening performance table** — ECO breakdown with win rates
- **Accuracy over time** — rolling trend charts
- **Opponent breakdown** — performance against each opponent
- **Opening gaps** — openings where you consistently go wrong early

### Game List
- **Search** by opponent name
- **Filter** by result, colour, time control, and date range
- **Sort** by date, accuracy, or opponent

### Mobile Layout
- Responsive design — optimised for small screens
- Key columns hidden on mobile to keep the game list readable
- Tables in cards scroll horizontally on mobile

---

## Requirements

- Python 3.10+
- [Stockfish](https://stockfishchess.org/download/) installed on your system
  - Ubuntu/Debian: `sudo apt install stockfish`
- See `requirements.txt` for Python dependencies (`flask`, `chess`)

---

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Stockfish (Ubuntu/Debian)
sudo apt install stockfish

# Start the app (accessible on your local network)
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser, or use your machine's local IP (e.g. `http://192.168.x.x:5000`) to access it from your phone.

> **Firewall note (Linux):** if you can't reach the app from another device, run `sudo ufw allow 5000/tcp`.

---

## First Steps

1. Open **⚙ Settings** in the navbar and enter your Chess.com username.
2. Click **⟳ Sync Chess.com** on the games page to import your recent games.
3. Click a game in the list, then **Analyse Game** to run Stockfish on it.
4. Navigate moves with **← →** arrow keys, on-screen buttons, or by tapping the board halves on mobile.
5. Use the overlay toggles and sliders below the board to visualise the engine's suggestions.

---

## Project Structure

```
chess-coach/
├── app.py            # Flask routes and context processors
├── analysis.py       # Stockfish analysis, Win%-based classification, game accuracy
├── database.py       # SQLite schema and CRUD operations
├── engine.py         # Stockfish engine wrapper
├── sync.py           # Chess.com sync via public API
├── openings.py       # ECO code → opening name mapping
├── main.py           # CLI entry point
├── templates/
│   ├── base.html     # Shared layout, nav, settings modal
│   ├── index.html    # Game list
│   ├── game.html     # Interactive board review
│   ├── stats.html    # Overall statistics
│   └── progress.html # Progress charts
└── requirements.txt
```

---

## Feature Branches

The following branches are in development and not yet merged into `main`:

| Branch | Description |
|---|---|
| `feat/multi-pv` | Show top 3 candidate moves at each position |
| `feat/opening-gaps` | Highlight openings where you go wrong early |
| `feat/training-mode` | "What would you play?" guessing mode |
| `feat/lichess-sync` | Sync games from a Lichess account |
| `future-state/background-worker` | Thread queue for non-blocking analysis |
| `future-state/auto-analysis` | Auto-analyse games after sync |
| `future-state/analyse-all` | Bulk-analyse all unanalysed games |
