"""
Chess.com sync — fetches games via the public Published-Data API.
No authentication required.
"""
import io
import json
import urllib.request
import urllib.error
from datetime import datetime

import chess.pgn

import database
from openings import resolve_opening

API_BASE = "https://api.chess.com/pub/player"
HEADERS  = {"User-Agent": "chess-coach-app/1.0"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_archives(username: str) -> list[str]:
    """Return all monthly archive URLs for a player, newest first."""
    data = _get(f"{API_BASE}/{username}/games/archives")
    return list(reversed(data.get("archives", [])))


def fetch_month(archive_url: str) -> list[dict]:
    """Return raw game objects for one month archive."""
    data = _get(archive_url)
    return data.get("games", [])


def sync(username: str, months: int = 1) -> dict:
    """
    Import up to `months` worth of recent games for `username`.
    Skips games already in the database.
    Returns {"imported": N, "skipped": N, "errors": N}.
    """
    counts = {"imported": 0, "skipped": 0, "errors": 0}

    try:
        archives = get_archives(username)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError(f'Chess.com user "{username}" not found.')
        raise

    for archive_url in archives[:months]:
        try:
            games = fetch_month(archive_url)
        except Exception:
            counts["errors"] += 1
            continue

        for g in games:
            source_id = g.get("url", "")

            # Skip if already imported
            if source_id and database.source_id_exists(source_id):
                counts["skipped"] += 1
                continue

            pgn_text = g.get("pgn", "")
            if not pgn_text:
                counts["errors"] += 1
                continue

            try:
                game_obj = chess.pgn.read_game(io.StringIO(pgn_text))
                if game_obj is None:
                    counts["errors"] += 1
                    continue

                headers = dict(game_obj.headers)
                opening, eco = resolve_opening(game_obj)
                headers["Opening"] = opening
                if eco:
                    headers["ECO"] = eco

                database.insert_game(pgn_text, headers, source_id=source_id)
                counts["imported"] += 1

            except Exception:
                counts["errors"] += 1

    database.set_setting("last_sync", datetime.now().isoformat())
    return counts
