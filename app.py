import io
import json
import os
import re

import chess.pgn
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

import analysis as analysis_module
import database
from openings import resolve_opening
import sync as sync_module
import lichess_sync as lichess_module

_CLK_RE = re.compile(r'\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]')


def _extract_clocks(pgn_text: str) -> list:
    """
    Walk PGN nodes and return a clock string per half-move.
    Format returned: 'H:MM:SS' collapsed to 'M:SS' or 'H:MM:SS' as needed.
    None when no clock annotation is present for that move.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    clocks = []
    node = game
    while node.variations:
        node = node.variations[0]
        m = _CLK_RE.search(node.comment or "")
        if m:
            h, mn, s = int(m.group(1)), int(m.group(2)), int(float(m.group(3)))
            if h > 0:
                clocks.append(f"{h}:{mn:02d}:{s:02d}")
            else:
                clocks.append(f"{mn}:{s:02d}")
        else:
            clocks.append(None)
    return clocks

app = Flask(__name__)
app.secret_key = "chess-coach-dev-key"

os.makedirs(os.path.join(os.path.dirname(__file__), "games"), exist_ok=True)
database.init_db()


@app.context_processor
def inject_player():
    """Make player_name and termination helper available in every template."""
    player = database.get_setting("player_name", "")

    def classify_termination(termination: str, result: str, white: str, black: str) -> dict | None:
        """
        Return {"type": ..., "outcome": ...} or None if termination is blank.

        type:    checkmate | resignation | time | forfeit |
                 stalemate | repetition | agreement | material | fifty | unknown
        outcome: won | lost | draw | None
        """
        if not termination:
            return None

        t   = termination.lower()
        p   = player.lower() if player else ""

        # Determine outcome from the player's perspective
        def _outcome():
            if result == "1/2-1/2":
                return "draw"
            if not p:
                return None
            my_color = "white" if white.lower() == p else \
                       ("black" if black.lower() == p else None)
            if not my_color:
                return None
            won = (my_color == "white" and result == "1-0") or \
                  (my_color == "black" and result == "0-1")
            return "won" if won else "lost"

        outcome = _outcome()

        if "checkmate" in t:
            kind = "checkmate"
        elif "resign" in t:
            kind = "resignation"
        elif "time" in t:
            kind = "time"
        elif "forfeit" in t or "abandon" in t or "disconnect" in t:
            kind = "forfeit"
        elif "stalemate" in t:
            kind = "stalemate"
        elif "repetition" in t or "threefold" in t:
            kind = "repetition"
        elif "agreement" in t:
            kind = "agreement"
        elif "material" in t or "insufficient" in t:
            kind = "material"
        elif "50" in t or "fifty" in t:
            kind = "fifty"
        else:
            kind = "unknown"

        return {"type": kind, "outcome": outcome}

    def classify_time_control(tc: str) -> dict:
        """
        Parse a PGN TimeControl string and return
        {'label': 'Blitz', 'detail': '5+3', 'color': '...'}.
        """
        if not tc or tc in ("-", "?", ""):
            return {"label": "?", "detail": "", "color": "#6e7681"}
        # Daily / correspondence  e.g. "1/86400"
        if "/" in tc:
            return {"label": "Daily", "detail": tc, "color": "#8b949e"}
        parts = tc.split("+")
        try:
            base = int(parts[0])
            inc  = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            return {"label": tc, "detail": "", "color": "#6e7681"}

        # Human-readable detail  e.g. "10+0" or "3+2"
        base_min  = base // 60
        base_sec  = base  % 60
        base_str  = f"{base_min}:{base_sec:02d}" if base_sec else str(base_min)
        detail    = f"{base_str}+{inc}" if inc else base_str

        # FIDE-ish classification by base seconds
        if base < 120:                        # < 2 min
            label, color = "Bullet",    "#f85149"
        elif base < 600:                      # 2–10 min
            label, color = "Blitz",     "#d4a017"
        elif base < 1800:                     # 10–30 min
            label, color = "Rapid",     "#58a6ff"
        else:                                 # 30+ min
            label, color = "Classical", "#56d364"

        return {"label": label, "detail": detail, "color": color}

    return {"player_name": player, "classify_termination": classify_termination,
            "classify_time_control": classify_time_control,
            "time_termination": lambda *a: None}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    player  = database.get_setting("player_name", "")
    search   = request.args.get("q", "").strip()
    result_f = request.args.get("result", "")
    color_f  = request.args.get("color", "")
    tc_f     = request.args.get("tc", "")
    analyzed_f = request.args.get("analyzed", "")
    sort_by  = request.args.get("sort", "date")
    sort_dir = request.args.get("dir", "desc")
    page     = max(1, int(request.args.get("page", 1)))
    per_page = 50

    games, total = database.get_games(
        limit=per_page,
        offset=(page - 1) * per_page,
        search=search,
        result_filter=result_f,
        color_filter=color_f,
        tc_filter=tc_f,
        analyzed_filter=analyzed_f,
        sort_by=sort_by,
        sort_dir=sort_dir,
        player=player,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "index.html",
        games=games,
        total=total,
        page=page,
        total_pages=total_pages,
        q=search,
        result_filter=result_f,
        color_filter=color_f,
        tc_filter=tc_f,
        analyzed_filter=analyzed_f,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@app.route("/import", methods=["POST"])
def import_game():
    pgn_text = ""

    if "pgn_file" in request.files and request.files["pgn_file"].filename:
        pgn_text = request.files["pgn_file"].read().decode("utf-8")
    elif request.form.get("pgn_text", "").strip():
        pgn_text = request.form["pgn_text"]
    else:
        flash("No PGN provided.", "error")
        return redirect(url_for("index"))

    count = 0
    reader = io.StringIO(pgn_text)
    while True:
        game = chess.pgn.read_game(reader)
        if game is None:
            break
        headers = dict(game.headers)
        opening, eco = resolve_opening(game)
        headers["Opening"] = opening
        if eco:
            headers["ECO"] = eco
        database.insert_game(str(game), headers)
        count += 1

    if count == 0:
        flash("No valid games found in the PGN.", "error")
    else:
        flash(f'Imported {count} game{"s" if count != 1 else ""}.', "success")

    return redirect(url_for("index"))


@app.route("/game/<int:game_id>")
def game_review(game_id):
    game = database.get_game(game_id)
    if not game:
        flash("Game not found.", "error")
        return redirect(url_for("index"))

    moves = database.get_moves(game_id) if game["analyzed"] else []
    stats = database.get_game_stats(game_id)

    # Build the positions list: [start_fen, after_move_1, after_move_2, ...]
    if moves:
        positions = [moves[0]["fen_before"]] + [m["fen_after"] for m in moves]
    else:
        import chess as _chess
        positions = [_chess.Board().fen()]

    # Extract per-move clock times from the stored PGN
    clocks = _extract_clocks(game["pgn"])
    moves_with_clocks = [
        {**m, "clock": clocks[i] if i < len(clocks) else None}
        for i, m in enumerate(moves)
    ]

    return render_template(
        "game.html",
        game=game,
        moves=moves_with_clocks,
        stats=stats,
        moves_json=json.dumps(moves_with_clocks),
        positions_json=json.dumps(positions),
    )


@app.route("/api/critical/<int:game_id>")
def get_critical(game_id):
    """Top-5 moves by cp_loss for a game, ordered by move index."""
    rows = database.get_critical_moves(game_id, n=5)
    return jsonify(rows)


@app.route("/api/pv", methods=["POST"])
def get_pv():
    import chess as _chess
    import chess.engine as _engine
    data    = request.get_json(silent=True) or {}
    fen     = data.get("fen", "")
    n_moves = max(1, min(int(data.get("moves", 3)), 10))
    try:
        board = _chess.Board(fen)
    except Exception:
        return jsonify({"pv": []}), 400
    if board.is_game_over():
        return jsonify({"pv": []})
    engine = _engine.SimpleEngine.popen_uci(analysis_module.STOCKFISH_PATH)
    try:
        info = engine.analyse(board, _engine.Limit(time=0.4))
        pv   = [m.uci() for m in info.get("pv", [])[:n_moves]]
    finally:
        engine.quit()
    return jsonify({"pv": pv})


@app.route("/game/<int:game_id>/analyse", methods=["POST"])
def analyse_game(game_id):
    game = database.get_game(game_id)
    if not game:
        return jsonify({"error": "Game not found"}), 404
    try:
        result = analysis_module.analyse_game(game["pgn"])
        database.save_analysis(game_id, result["moves"], result["stats"])
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/game/<int:game_id>/delete", methods=["POST"])
def delete_game(game_id):
    database.delete_game(game_id)
    flash("Game deleted.", "success")
    return redirect(url_for("index"))


@app.route("/backfill-openings", methods=["POST"])
def backfill_openings():
    """Fix opening names for already-imported games that show an ECO code or blank."""
    import io as _io
    games = database.get_games(limit=10000)
    updated = 0
    for g in games:
        eco = (g.get("eco") or "").strip()
        opening = (g.get("opening") or "").strip()
        # Re-resolve if opening looks like a raw ECO code or is blank
        if not opening or (len(opening) == 3 and opening[0].isalpha() and opening[1:].isdigit()):
            game_obj = chess.pgn.read_game(_io.StringIO(g["pgn"]))
            if game_obj:
                new_opening, _ = resolve_opening(game_obj)
                if new_opening and new_opening != opening:
                    with database.get_db() as conn:
                        conn.execute(
                            "UPDATE games SET opening = ? WHERE id = ?",
                            (new_opening, g["id"]),
                        )
                    updated += 1
    flash(f"Updated opening names for {updated} game(s).", "success")
    return redirect(url_for("index"))


@app.route("/sync", methods=["POST"])
def sync_chesscom():
    player = database.get_setting("player_name", "").strip()
    if not player:
        return jsonify({"error": "No player name set. Add it in Settings first."}), 400
    months = int(request.form.get("months", 1))
    try:
        counts = sync_module.sync(player, months=months)
        return jsonify(counts)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/settings", methods=["POST"])
def save_settings():
    name = request.form.get("player_name", "").strip()
    database.set_setting("player_name", name)
    flash(f'Player name set to "{name}".', "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/stats")
def stats():
    player = database.get_setting("player_name", "")
    data = database.get_overall_stats(player=player)
    return render_template("stats.html", stats=data)


@app.route("/game/<int:game_id>/export")
def export_pgn(game_id):
    """
    Download the game PGN with Stockfish eval annotations embedded as
    { [%eval +0.45] } comments after each move (compatible with Lichess/ChessBase).
    Also appends classification and cp_loss as comments.
    """
    game = database.get_game(game_id)
    if not game:
        return "Game not found", 404

    import io as _io
    import chess.pgn as _pgn

    # Parse original PGN
    pgn_game = _pgn.read_game(_io.StringIO(game["pgn"]))
    if pgn_game is None:
        return "Invalid PGN", 500

    moves_data = database.get_moves(game_id) if game["analyzed"] else []
    moves_by_idx = {m["move_idx"]: m for m in moves_data}

    # Walk the game and inject comments
    node = pgn_game
    for idx, child in enumerate(pgn_game.mainline()):
        m = moves_by_idx.get(idx)
        if m:
            parts = []
            if m["eval_after"] is not None:
                cp = m["eval_after"]
                if cp >= 9000:
                    eval_str = f"#{int(10000 - cp)}"
                elif cp <= -9000:
                    eval_str = f"#-{int(10000 + cp)}"
                else:
                    eval_str = f"{cp / 100:+.2f}"
                parts.append(f"[%eval {eval_str}]")
            if m["classification"] and m["classification"] != "best":
                parts.append(m["classification"].capitalize())
                if m["cp_loss"] and m["cp_loss"] > 0:
                    parts.append(f"({m['cp_loss'] / 100:.2f} pawns)")
                if m["best_move_san"] and m["best_move_uci"] != m["uci"]:
                    parts.append(f"Best: {m['best_move_san']}")
            if parts:
                child.comment = " ".join(parts)
        node = child

    exporter = _pgn.StringExporter(headers=True, variations=True, comments=True)
    annotated = pgn_game.accept(exporter)

    filename = f"{game['white']}_vs_{game['black']}_{game['date'] or 'unknown'}.pgn"
    filename = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)

    from flask import Response
    return Response(
        annotated,
        mimetype="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/progress")
def progress():
    player = database.get_setting("player_name", "")
    accuracy_series = database.get_accuracy_over_time(player=player, limit=60)
    opponent_stats  = database.get_opponent_stats(player=player, limit=15) if player else []
    opening_stats   = database.get_overall_stats(player=player)["opening_stats"]
    return render_template(
        "progress.html",
        accuracy_series=accuracy_series,
        opponent_stats=opponent_stats,
        opening_stats=opening_stats,
    )


@app.route("/sync/lichess", methods=["POST"])
def sync_lichess():
    player = database.get_setting("player_name", "")
    lichess_user = request.form.get("lichess_user", player).strip()
    if not lichess_user:
        return jsonify({"error": "No Lichess username provided."}), 400
    max_games = int(request.form.get("max_games", 50))
    perf_type  = request.form.get("perf_type", "") or None
    try:
        result = lichess_module.sync(lichess_user, max_games=max_games,
                                     perf_type=perf_type)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Sync failed: {e}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
