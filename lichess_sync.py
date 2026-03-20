"""
Lichess sync — fetches games via the Lichess API (ndjson stream).
No authentication required for public games.
API docs: https://lichess.org/api#tag/Games
"""
import io
import urllib.request
import urllib.error
from datetime import datetime

import chess.pgn

import database
from openings import resolve_opening

API_BASE = "https://lichess.org/api"
HEADERS  = {
    "User-Agent":  "chess-coach-app/1.0",
    "Accept":      "application/x-ndjson",
}


def _get_ndjson(url: str) -> list[dict]:
    """Fetch a newline-delimited JSON stream and return a list of dicts."""
    import json
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _get_pgn_stream(url: str) -> str:
    """Fetch a PGN stream (multiple games separated by blank lines)."""
    pgn_headers = {**HEADERS, "Accept": "application/x-chess-pgn"}
    req = urllib.request.Request(url, headers=pgn_headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def fetch_recent_games(username: str, max_games: int = 50,
                       perf_type: str | None = None) -> str:
    """
    Return a multi-game PGN string for the player's most recent games.
    perf_type can be: bullet, blitz, rapid, classical, correspondence
    """
    params = f"max={max_games}&clocks=true&opening=true&evals=false"
    if perf_type:
        params += f"&perfType={perf_type}"
    url = f"{API_BASE}/games/user/{username}?{params}"
    return _get_pgn_stream(url)


def sync(username: str, max_games: int = 50,
         perf_type: str | None = None) -> dict:
    """
    Import up to `max_games` recent Lichess games for `username`.
    Skips games already in the database.
    Returns {"imported": N, "skipped": N, "errors": N}.
    """
    counts = {"imported": 0, "skipped": 0, "errors": 0}

    try:
        pgn_text_all = fetch_recent_games(username, max_games=max_games,
                                          perf_type=perf_type)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f'Lichess user "{username}" not found.')
        raise

    if not pgn_text_all.strip():
        return counts

    pgn_io = io.StringIO(pgn_text_all)
    while True:
        try:
            game_obj = chess.pgn.read_game(pgn_io)
        except Exception:
            counts["errors"] += 1
            continue
        if game_obj is None:
            break

        # Lichess game URL is in the Site header
        site = game_obj.headers.get("Site", "")
        source_id = site if site.startswith("https://lichess.org/") else ""

        if source_id and database.source_id_exists(source_id):
            counts["skipped"] += 1
            continue

        try:
            pgn_str = str(game_obj)
            headers = dict(game_obj.headers)
            opening, eco = resolve_opening(game_obj)
            headers["Opening"] = opening
            if eco:
                headers["ECO"] = eco

            database.insert_game(pgn_str, headers, source_id=source_id)
            counts["imported"] += 1
        except Exception:
            counts["errors"] += 1

    database.set_setting("last_lichess_sync", datetime.now().isoformat())
    return counts
