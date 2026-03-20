import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "chess.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pgn          TEXT    NOT NULL,
    white        TEXT,
    black        TEXT,
    result       TEXT,
    date         TEXT,
    event        TEXT,
    opening      TEXT,
    eco          TEXT,
    time_control TEXT,
    imported_at  TEXT    NOT NULL,
    analyzed     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS moves (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id        INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    move_idx       INTEGER NOT NULL,
    move_number    INTEGER NOT NULL,
    color          TEXT    NOT NULL,
    uci            TEXT    NOT NULL,
    san            TEXT    NOT NULL,
    fen_before     TEXT    NOT NULL,
    fen_after      TEXT    NOT NULL,
    eval_before    REAL,
    eval_after     REAL,
    best_move_uci  TEXT,
    best_move_san  TEXT,
    cp_loss        REAL,
    classification TEXT,
    accuracy       REAL,
    is_forced      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_stats (
    game_id             INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    white_accuracy      REAL,
    black_accuracy      REAL,
    white_blunders      INTEGER DEFAULT 0,
    black_blunders      INTEGER DEFAULT 0,
    white_mistakes      INTEGER DEFAULT 0,
    black_mistakes      INTEGER DEFAULT 0,
    white_inaccuracies  INTEGER DEFAULT 0,
    black_inaccuracies  INTEGER DEFAULT 0,
    critical_move_idx   INTEGER,
    critical_cp_loss    REAL,
    analyzed_at         TEXT
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # Migrations: safe to run repeatedly — silently skip if column exists
        migrations = [
            "ALTER TABLE games ADD COLUMN source_id TEXT",
            "ALTER TABLE games ADD COLUMN termination TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        # Backfill termination for any existing rows that have it blank
        _backfill_termination(conn)


def _backfill_termination(conn):
    """Populate termination column for games that were imported before it existed."""
    import re as _re
    rows = conn.execute(
        "SELECT id, pgn FROM games WHERE termination IS NULL OR termination = ''"
    ).fetchall()
    _term_re = _re.compile(r'\[Termination\s+"([^"]+)"\]')
    for row in rows:
        m = _term_re.search(row["pgn"] or "")
        term = m.group(1) if m else ""
        conn.execute("UPDATE games SET termination = ? WHERE id = ?", (term, row["id"]))


def source_id_exists(source_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM games WHERE source_id = ?", (source_id,)
        ).fetchone()
        return row is not None


def insert_game(pgn: str, headers: dict, source_id: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO games
               (pgn, white, black, result, date, event, opening, eco,
                time_control, imported_at, source_id, termination)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pgn,
                headers.get("White", "?"),
                headers.get("Black", "?"),
                headers.get("Result", "*"),
                headers.get("Date", ""),
                headers.get("Event", ""),
                headers.get("Opening", ""),
                headers.get("ECO", ""),
                headers.get("TimeControl", ""),
                datetime.now().isoformat(),
                source_id,
                headers.get("Termination", ""),
            ),
        )
        return cur.lastrowid


def get_games(
    limit: int = 200,
    offset: int = 0,
    search: str = "",
    result_filter: str = "",   # "win" | "loss" | "draw" | ""
    color_filter: str = "",    # "white" | "black" | ""
    tc_filter: str = "",        # "bullet" | "blitz" | "rapid" | "classical" | "daily" | ""
    analyzed_filter: str = "", # "yes" | "no" | ""
    sort_by: str = "date",     # "date" | "accuracy" | "opponent" | "opening"
    sort_dir: str = "desc",
    player: str = "",
):
    conditions = []
    params: list = []

    if search:
        conditions.append(
            "(lower(g.white) LIKE ? OR lower(g.black) LIKE ? OR lower(g.opening) LIKE ?)"
        )
        like = f"%{search.lower()}%"
        params += [like, like, like]

    if result_filter and player:
        p = player.lower()
        if result_filter == "win":
            conditions.append(
                "((lower(g.white)=? AND g.result='1-0') OR (lower(g.black)=? AND g.result='0-1'))"
            )
            params += [p, p]
        elif result_filter == "loss":
            conditions.append(
                "((lower(g.white)=? AND g.result='0-1') OR (lower(g.black)=? AND g.result='1-0'))"
            )
            params += [p, p]
        elif result_filter == "draw":
            conditions.append("g.result='1/2-1/2'")

    if color_filter and player:
        p = player.lower()
        if color_filter == "white":
            conditions.append("lower(g.white)=?")
            params.append(p)
        elif color_filter == "black":
            conditions.append("lower(g.black)=?")
            params.append(p)

    if tc_filter:
        # Map category → base-seconds ranges using CAST on the part before '+'
        tc_ranges = {
            "bullet":    "CAST(SUBSTR(g.time_control,1,INSTR(g.time_control||'+','+') -1) AS INTEGER) < 120",
            "blitz":     "CAST(SUBSTR(g.time_control,1,INSTR(g.time_control||'+','+') -1) AS INTEGER) BETWEEN 120 AND 599",
            "rapid":     "CAST(SUBSTR(g.time_control,1,INSTR(g.time_control||'+','+') -1) AS INTEGER) BETWEEN 600 AND 1799",
            "classical": "CAST(SUBSTR(g.time_control,1,INSTR(g.time_control||'+','+') -1) AS INTEGER) >= 1800",
            "daily":     "g.time_control LIKE '%/%'",
        }
        if tc_filter in tc_ranges:
            conditions.append(f"({tc_ranges[tc_filter]})")

    if analyzed_filter == "yes":
        conditions.append("g.analyzed=1")
    elif analyzed_filter == "no":
        conditions.append("g.analyzed=0")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Build ORDER BY
    dir_sql = "DESC" if sort_dir.lower() == "desc" else "ASC"
    if sort_by == "accuracy" and player:
        p = player.lower()
        order = f"""ORDER BY
            CASE WHEN lower(g.white)='{p}' THEN gs.white_accuracy
                 ELSE gs.black_accuracy END {dir_sql} NULLS LAST"""
    elif sort_by == "opponent" and player:
        p = player.lower()
        order = f"""ORDER BY
            CASE WHEN lower(g.white)='{p}' THEN lower(g.black)
                 ELSE lower(g.white) END {dir_sql}"""
    elif sort_by == "opening":
        order = f"ORDER BY lower(g.opening) {dir_sql}"
    elif sort_by == "result":
        order = f"ORDER BY g.result {dir_sql}"
    else:
        order = f"ORDER BY g.imported_at {dir_sql}"

    sql = f"""SELECT g.*, gs.white_accuracy, gs.black_accuracy
              FROM games g
              LEFT JOIN game_stats gs ON g.id = gs.game_id
              {where}
              {order}
              LIMIT ? OFFSET ?"""
    params += [limit, offset]

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM games g {where}", params[:-2]
        ).fetchone()[0]
        return [dict(r) for r in rows], total


def get_game(game_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return dict(row) if row else None


def get_moves(game_id: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM moves WHERE game_id = ? ORDER BY move_idx", (game_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_game_stats(game_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM game_stats WHERE game_id = ?", (game_id,)
        ).fetchone()
        return dict(row) if row else None


def get_critical_moves(game_id: int, n: int = 5) -> list:
    """Return the top-N moves by centipawn loss, ordered by move_idx."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT move_idx, move_number, color, san, uci,
                      cp_loss, classification, eval_before, eval_after
               FROM moves
               WHERE game_id = ? AND is_forced = 0
                 AND classification IN ('inaccuracy', 'mistake', 'blunder')
               ORDER BY cp_loss DESC LIMIT ?""",
            (game_id, n),
        ).fetchall()
        # Return in game order
        result = sorted([dict(r) for r in rows], key=lambda m: m["move_idx"])
        return result


def save_analysis(game_id: int, moves_data: list, stats: dict):
    with get_db() as conn:
        conn.execute("DELETE FROM moves WHERE game_id = ?", (game_id,))
        conn.execute("DELETE FROM game_stats WHERE game_id = ?", (game_id,))

        for m in moves_data:
            conn.execute(
                """INSERT INTO moves
                   (game_id, move_idx, move_number, color, uci, san,
                    fen_before, fen_after, eval_before, eval_after,
                    best_move_uci, best_move_san, cp_loss, classification,
                    accuracy, is_forced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    game_id,
                    m["move_idx"],
                    m["move_number"],
                    m["color"],
                    m["uci"],
                    m["san"],
                    m["fen_before"],
                    m["fen_after"],
                    m["eval_before"],
                    m["eval_after"],
                    m["best_move_uci"],
                    m["best_move_san"],
                    m["cp_loss"],
                    m["classification"],
                    m["accuracy"],
                    1 if m["is_forced"] else 0,
                ),
            )

        conn.execute(
            """INSERT INTO game_stats
               (game_id, white_accuracy, black_accuracy,
                white_blunders, black_blunders, white_mistakes, black_mistakes,
                white_inaccuracies, black_inaccuracies,
                critical_move_idx, critical_cp_loss, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                game_id,
                stats["white_accuracy"],
                stats["black_accuracy"],
                stats["white_blunders"],
                stats["black_blunders"],
                stats["white_mistakes"],
                stats["black_mistakes"],
                stats["white_inaccuracies"],
                stats["black_inaccuracies"],
                stats["critical_move_idx"],
                stats["critical_cp_loss"],
                datetime.now().isoformat(),
            ),
        )

        conn.execute("UPDATE games SET analyzed = 1 WHERE id = ?", (game_id,))


def delete_game(game_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM games WHERE id = ?", (game_id,))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Stats (player-aware)
# ---------------------------------------------------------------------------

def get_overall_stats(player: str = ""):
    """Return stats. When player is set, figures are from that player's POV."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        analyzed = conn.execute(
            "SELECT COUNT(*) FROM games WHERE analyzed = 1"
        ).fetchone()[0]

        # Player-aware accuracy & record
        if player:
            p = player.lower()
            record_row = conn.execute(
                """SELECT
                   COUNT(*) as played,
                   SUM(CASE
                     WHEN lower(white)=? AND result='1-0' THEN 1
                     WHEN lower(black)=? AND result='0-1' THEN 1
                     ELSE 0 END) as wins,
                   SUM(CASE
                     WHEN lower(white)=? AND result='0-1' THEN 1
                     WHEN lower(black)=? AND result='1-0' THEN 1
                     ELSE 0 END) as losses,
                   SUM(CASE WHEN result='1/2-1/2' THEN 1 ELSE 0 END) as draws
                   FROM games""",
                (p, p, p, p),
            ).fetchone()

            acc_row = conn.execute(
                """SELECT AVG(player_acc) as avg_acc,
                          SUM(player_blunders) as total_blunders
                   FROM (
                     SELECT
                       CASE WHEN lower(g.white)=? THEN gs.white_accuracy
                            ELSE gs.black_accuracy END as player_acc,
                       CASE WHEN lower(g.white)=? THEN gs.white_blunders
                            ELSE gs.black_blunders END as player_blunders
                     FROM games g
                     JOIN game_stats gs ON g.id = gs.game_id
                     WHERE lower(g.white)=? OR lower(g.black)=?
                   )""",
                (p, p, p, p),
            ).fetchone()
        else:
            record_row = None
            acc_row = conn.execute(
                """SELECT AVG((white_accuracy + black_accuracy) / 2) as avg_acc,
                          SUM(white_blunders + black_blunders) as total_blunders
                   FROM game_stats"""
            ).fetchone()

        if player:
            opening_rows = conn.execute(
                """SELECT opening, COUNT(*) as count,
                   SUM(CASE
                     WHEN lower(white)=? AND result='1-0' THEN 1
                     WHEN lower(black)=? AND result='0-1' THEN 1
                     ELSE 0 END) as wins,
                   SUM(CASE
                     WHEN lower(white)=? AND result='0-1' THEN 1
                     WHEN lower(black)=? AND result='1-0' THEN 1
                     ELSE 0 END) as losses,
                   SUM(CASE WHEN result='1/2-1/2' THEN 1 ELSE 0 END) as draws
                   FROM games
                   WHERE opening IS NOT NULL AND opening != ''
                   AND (lower(white)=? OR lower(black)=?)
                   GROUP BY opening
                   ORDER BY count DESC
                   LIMIT 10""",
                (p, p, p, p, p, p),
            ).fetchall()

            recent_rows = conn.execute(
                """SELECT g.id, g.white, g.black, g.result,
                   CASE WHEN lower(g.white)=? THEN gs.white_accuracy
                        ELSE gs.black_accuracy END as my_accuracy,
                   CASE WHEN lower(g.white)=? THEN 'white' ELSE 'black' END as my_color
                   FROM games g
                   JOIN game_stats gs ON g.id = gs.game_id
                   WHERE lower(g.white)=? OR lower(g.black)=?
                   ORDER BY g.imported_at DESC
                   LIMIT 20""",
                (p, p, p, p),
            ).fetchall()
        else:
            opening_rows = conn.execute(
                """SELECT opening, COUNT(*) as count,
                   SUM(CASE WHEN result = '1-0' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result = '0-1' THEN 1 ELSE 0 END) as losses,
                   SUM(CASE WHEN result = '1/2-1/2' THEN 1 ELSE 0 END) as draws
                   FROM games
                   WHERE opening IS NOT NULL AND opening != ''
                   GROUP BY opening
                   ORDER BY count DESC
                   LIMIT 10"""
            ).fetchall()

            recent_rows = conn.execute(
                """SELECT g.id, g.white, g.black, g.result,
                   gs.white_accuracy as my_accuracy, 'white' as my_color
                   FROM games g
                   JOIN game_stats gs ON g.id = gs.game_id
                   ORDER BY g.imported_at DESC
                   LIMIT 20"""
            ).fetchall()

        return {
            "total_games": total,
            "analyzed_games": analyzed,
            "avg_acc": round(acc_row["avg_acc"], 1) if acc_row and acc_row["avg_acc"] else None,
            "total_blunders": int(acc_row["total_blunders"] or 0) if acc_row else 0,
            "record": dict(record_row) if record_row else None,
            "opening_stats": [dict(r) for r in opening_rows],
            "recent_accuracy": [dict(r) for r in recent_rows],
        }


def get_accuracy_over_time(player: str = "", limit: int = 50) -> list:
    """Return (date, accuracy) pairs for the most recent `limit` analysed games."""
    with get_db() as conn:
        p = player.lower() if player else None
        if p:
            rows = conn.execute(
                """SELECT g.date,
                   CASE WHEN lower(g.white)=? THEN gs.white_accuracy
                        ELSE gs.black_accuracy END as accuracy
                   FROM games g
                   JOIN game_stats gs ON g.id = gs.game_id
                   WHERE (lower(g.white)=? OR lower(g.black)=?) AND g.date IS NOT NULL
                   ORDER BY g.date ASC, g.id ASC LIMIT ?""",
                (p, p, p, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT g.date,
                   (gs.white_accuracy + gs.black_accuracy) / 2.0 as accuracy
                   FROM games g
                   JOIN game_stats gs ON g.id = gs.game_id
                   WHERE g.date IS NOT NULL
                   ORDER BY g.date ASC, g.id ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_opponent_stats(player: str, limit: int = 15) -> list:
    """Win/draw/loss breakdown vs most-played opponents."""
    with get_db() as conn:
        p = player.lower()
        rows = conn.execute(
            """SELECT
               CASE WHEN lower(white)=? THEN black ELSE white END as opponent,
               COUNT(*) as games,
               SUM(CASE
                 WHEN lower(white)=? AND result='1-0' THEN 1
                 WHEN lower(black)=? AND result='0-1' THEN 1
                 ELSE 0 END) as wins,
               SUM(CASE
                 WHEN lower(white)=? AND result='0-1' THEN 1
                 WHEN lower(black)=? AND result='1-0' THEN 1
                 ELSE 0 END) as losses,
               SUM(CASE WHEN result='1/2-1/2' THEN 1 ELSE 0 END) as draws
               FROM games
               WHERE lower(white)=? OR lower(black)=?
               GROUP BY opponent
               ORDER BY games DESC LIMIT ?""",
            (p, p, p, p, p, p, p, limit),
        ).fetchall()
        return [dict(r) for r in rows]
