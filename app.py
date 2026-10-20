from datetime import date, datetime
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for, make_response

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
DATABASE = Path(__file__).with_name("focusflow.db")


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'Media',
                due_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            """
        )


def valid_due_date(value):
    """Accept an empty date or a real ISO calendar date."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return False


@app.route("/")
def index():
    with get_db() as db:
        tasks = db.execute(
            "SELECT * FROM tasks ORDER BY completed ASC, "
            "CASE WHEN due_date IS NULL OR due_date = '' THEN 1 ELSE 0 END, "
            "due_date ASC, id DESC"
        ).fetchall()

    total = len(tasks)
    completed = sum(task["completed"] for task in tasks)
    today_date = date.today()
    with get_db() as db:
        sessions = db.execute(
            """SELECT ws.*, t.title AS task_title FROM work_sessions ws
               JOIN tasks t ON t.id = ws.task_id
               WHERE ws.ended_at IS NOT NULL ORDER BY ws.started_at DESC"""
        ).fetchall()
        active_session = db.execute(
            """SELECT ws.*, t.title AS task_title FROM work_sessions ws
               JOIN tasks t ON t.id = ws.task_id
               WHERE ws.ended_at IS NULL ORDER BY ws.id DESC LIMIT 1"""
        ).fetchone()

    work_stats = {}
    active_days_by_task = {}
    activity_by_day = {}
    total_work_seconds = 0
    today_work_seconds = 0
    for session in sessions:
        started = datetime.fromisoformat(session["started_at"])
        day_key = started.date().isoformat()
        seconds = max(0, int(session["duration_seconds"] or 0))
        total_work_seconds += seconds
        activity_by_day[day_key] = activity_by_day.get(day_key, 0) + seconds
        if started.date() == today_date:
            today_work_seconds += seconds
        task_id = session["task_id"]
        work_stats.setdefault(task_id, {"seconds": 0, "sessions": 0, "last_comment": ""})
        work_stats[task_id]["seconds"] += seconds
        work_stats[task_id]["sessions"] += 1
        if not work_stats[task_id]["last_comment"] and session["comment"]:
            work_stats[task_id]["last_comment"] = session["comment"]
        active_days_by_task.setdefault(task_id, set()).add(day_key)

    task_streaks = {}
    for task in tasks:
        days = active_days_by_task.get(task["id"], set())
        cursor_day = today_date if today_date.isoformat() in days else date.fromordinal(today_date.toordinal() - 1)
        streak = 0
        while cursor_day.isoformat() in days:
            streak += 1
            cursor_day = date.fromordinal(cursor_day.toordinal() - 1)
        task_streaks[task["id"]] = streak

    activity_days = []
    for offset in range(34, -1, -1):
        day = date.fromordinal(today_date.toordinal() - offset)
        seconds = activity_by_day.get(day.isoformat(), 0)
        activity_days.append({
            "date": day.isoformat(),
            "label": day.strftime("%d/%m"),
            "seconds": seconds,
            "minutes": seconds // 60,
            "level": 0 if seconds == 0 else (1 if seconds < 1800 else (2 if seconds < 7200 else (3 if seconds < 14400 else 4))),
        })
    response = make_response(render_template(
        "index.html",
        tasks=tasks,
        total=total,
        completed=completed,
        today=today_date.isoformat(),
        work_stats=work_stats,
        task_streaks=task_streaks,
        activity_days=activity_days,
        total_work_seconds=total_work_seconds,
        today_work_seconds=today_work_seconds,
        active_session=active_session,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/tasks", methods=["POST"])
def add_task():
    title = request.form.get("title", "").strip()[:160]
    priority = request.form.get("priority", "Media")
    raw_due_date = request.form.get("due_date", "").strip()
    due_date = valid_due_date(raw_due_date)

    if not title:
        return redirect(url_for("index"))
    if priority not in {"Baja", "Media", "Alta"}:
        priority = "Media"
    if due_date is False:
        due_date = None

    with get_db() as db:
        db.execute(
            "INSERT INTO tasks (title, priority, due_date) VALUES (?, ?, ?)",
            (title, priority, due_date),
        )
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    with get_db() as db:
        db.execute(
            """
            UPDATE tasks
            SET completed = CASE completed WHEN 0 THEN 1 ELSE 0 END
            WHERE id = ?
            """,
            (task_id,),
        )
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    with get_db() as db:
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return redirect(url_for("index"))


@app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
def edit_task(task_id):
    """Update an existing task from the inline editor."""
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()[:160]
    priority = payload.get("priority", "Media")
    due_date = valid_due_date(str(payload.get("due_date", "")).strip())

    if not title:
        return jsonify({"ok": False, "message": "El nombre de la tarea no puede estar vacío."}), 400
    if priority not in {"Baja", "Media", "Alta"}:
        return jsonify({"ok": False, "message": "Selecciona una prioridad válida."}), 400
    if due_date is False:
        return jsonify({"ok": False, "message": "La fecha límite no es válida."}), 400

    with get_db() as db:
        cursor = db.execute(
            "UPDATE tasks SET title = ?, priority = ?, due_date = ? WHERE id = ?",
            (title, priority, due_date, task_id),
        )
        if cursor.rowcount == 0:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404

    return jsonify({
        "ok": True,
        "task": {"id": task_id, "title": title, "priority": priority, "due_date": due_date},
    })


@app.route("/api/work/start", methods=["POST"])
def start_work():
    payload = request.get_json(silent=True) or {}
    try:
        task_id = int(payload.get("task_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Selecciona una tarea válida."}), 400
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_db() as db:
        task = db.execute("SELECT id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        active = db.execute("SELECT id FROM work_sessions WHERE ended_at IS NULL LIMIT 1").fetchone()
        if active:
            return jsonify({"ok": False, "message": "Ya hay una sesión en curso. Termínala antes de empezar otra."}), 409
        cursor = db.execute(
            "INSERT INTO work_sessions (task_id, started_at) VALUES (?, ?)",
            (task_id, started_at),
        )
        session_id = cursor.lastrowid
    return jsonify({"ok": True, "session_id": session_id, "task_id": task_id, "task_title": task["title"], "started_at": started_at})


@app.route("/api/work/stop", methods=["POST"])
def stop_work():
    payload = request.get_json(silent=True) or {}
    comment = str(payload.get("comment", "")).strip()[:1000]
    ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_db() as db:
        session = db.execute(
            "SELECT * FROM work_sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not session:
            return jsonify({"ok": False, "message": "No hay ninguna sesión en curso."}), 409
        started_at = datetime.fromisoformat(session["started_at"])
        ended = datetime.fromisoformat(ended_at)
        duration = max(0, int((ended - started_at).total_seconds()))
        db.execute(
            "UPDATE work_sessions SET ended_at = ?, duration_seconds = ?, comment = ? WHERE id = ?",
            (ended_at, duration, comment, session["id"]),
        )
    return jsonify({"ok": True, "duration_seconds": duration, "comment": comment, "message": "Sesión guardada."})


@app.route("/api/tasks/<int:task_id>/work-log")
def task_work_log(task_id):
    with get_db() as db:
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        logs = db.execute(
            """SELECT id, started_at, ended_at, duration_seconds, comment
               FROM work_sessions WHERE task_id = ? AND ended_at IS NOT NULL
               ORDER BY started_at DESC LIMIT 20""",
            (task_id,),
        ).fetchall()
    return jsonify({"ok": True, "sessions": [dict(row) for row in logs]})


@app.route("/api/music/search")
def search_music():
    query = request.args.get("q", "").strip()[:120]
    if not query:
        return jsonify({"items": [], "message": "Escribe una canción, artista o estilo."}), 400

    try:
        from ytmusicapi import YTMusic
        music = YTMusic()
        found = music.search(query, filter="songs", limit=8)
        items = []
        for song in found:
            video_id = song.get("videoId")
            if not video_id:
                continue
            artists = song.get("artists") or []
            artist_names = ", ".join(
                artist.get("name", "") for artist in artists if artist.get("name")
            )
            thumbnails = song.get("thumbnails") or []
            thumbnail = thumbnails[-1].get("url", "") if thumbnails else ""
            items.append({
                "id": video_id,
                "title": song.get("title", "Canción sin título"),
                "channel": artist_names or (song.get("album") or {}).get("name", "YouTube Music"),
                "thumbnail": thumbnail,
            })
        if not items:
            return jsonify({"items": [], "message": "No encontré canciones con esa búsqueda. Prueba con otro término."})
        return jsonify({"items": items, "message": ""})
    except ImportError:
        return jsonify({
            "items": [],
            "message": "Falta instalar ytmusicapi. En la terminal ejecuta: pip install -r requirements.txt"
        }), 503
    except Exception:
        app.logger.exception("Error buscando música con ytmusicapi")
        return jsonify({
            "items": [],
            "message": "YouTube Music no respondió como se esperaba. La búsqueda usa una interfaz no oficial; prueba más tarde o abre YouTube Music."
        }), 502


init_db()

if __name__ == "__main__":
    app.run(debug=True)
