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
    response = make_response(render_template(
        "index.html",
        tasks=tasks,
        total=total,
        completed=completed,
        today=date.today().isoformat(),
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
