"""
Background worker — thread-based job queue for long-running tasks
(primarily Stockfish analysis) so they don't block the Flask dev server.

Usage:
    The worker is started automatically when app.py imports this module.
    Submit jobs via: worker.enqueue(job_type, **kwargs)
    Poll status via: worker.status(job_id)

Job types:
    "analyse"   kwargs: game_id (int)
    "analyse_all"  kwargs: (none — analyses all un-analysed games)
"""
import threading
import queue
import uuid
import time
import traceback
from datetime import datetime

import database
import analysis as analysis_module

# ── Job registry ────────────────────────────────────────────
_jobs: dict[str, dict] = {}   # job_id → {status, type, created_at, result, error}
_queue: queue.Queue = queue.Queue()
_lock  = threading.Lock()

JOB_PENDING   = "pending"
JOB_RUNNING   = "running"
JOB_DONE      = "done"
JOB_ERROR     = "error"


def enqueue(job_type: str, **kwargs) -> str:
    """Add a job to the queue. Returns the job_id."""
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "id":         job_id,
            "type":       job_type,
            "kwargs":     kwargs,
            "status":     JOB_PENDING,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "finished_at": None,
            "result":     None,
            "error":      None,
        }
    _queue.put(job_id)
    return job_id


def status(job_id: str) -> dict | None:
    """Return the current state of a job, or None if not found."""
    with _lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None


def list_jobs(limit: int = 20) -> list[dict]:
    """Return recent jobs newest-first."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
    return [dict(j) for j in jobs[:limit]]


# ── Worker thread ────────────────────────────────────────────
def _run_job(job: dict):
    jtype  = job["type"]
    kwargs = job["kwargs"]

    if jtype == "analyse":
        game_id = kwargs["game_id"]
        game    = database.get_game(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        result = analysis_module.analyse_game(game["pgn"])
        database.save_analysis(game_id, result["moves"], result["stats"])
        return {"game_id": game_id, "moves": len(result["moves"])}

    if jtype == "analyse_all":
        games = database.get_unanalysed_games()
        done, failed = 0, 0
        for g in games:
            try:
                result = analysis_module.analyse_game(g["pgn"])
                database.save_analysis(g["id"], result["moves"], result["stats"])
                done += 1
            except Exception:
                failed += 1
        return {"analysed": done, "failed": failed}

    raise ValueError(f"Unknown job type: {jtype!r}")


def _worker_loop():
    while True:
        job_id = _queue.get()
        with _lock:
            if job_id not in _jobs:
                continue
            job = _jobs[job_id]
            job["status"]     = JOB_RUNNING
            job["started_at"] = datetime.now().isoformat()

        try:
            result = _run_job(job)
            with _lock:
                _jobs[job_id]["status"]      = JOB_DONE
                _jobs[job_id]["result"]      = result
                _jobs[job_id]["finished_at"] = datetime.now().isoformat()
        except Exception as exc:
            with _lock:
                _jobs[job_id]["status"]      = JOB_ERROR
                _jobs[job_id]["error"]       = str(exc)
                _jobs[job_id]["finished_at"] = datetime.now().isoformat()
            traceback.print_exc()
        finally:
            _queue.task_done()


def _get_unanalysed_games():
    """Helper used by analyse_all job."""
    pass  # implemented in database.py


# ── Auto-start ───────────────────────────────────────────────
_thread = threading.Thread(target=_worker_loop, daemon=True, name="bg-worker")
_thread.start()
