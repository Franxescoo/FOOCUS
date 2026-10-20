from datetime import date
import json
import os
import sqlite3
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
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


@app.route("/")
def index():
    with get_db() as db:
        tasks = db.execute(
            "SELECT * FROM tasks ORDER BY completed ASC, id DESC"
        ).fetchall()

    total = len(tasks)
    completed = sum(task["completed"] for task in tasks)
    return render_template(
        "index.html",
        tasks=tasks,
        total=total,
        completed=completed,
        today=date.today().isoformat(),
    )


@app.route("/tasks", methods=["POST"])
def add_task():
    title = request.form.get("title", "").strip()
    priority = request.form.get("priority", "Media")
    due_date = request.form.get("due_date", "").strip() or None

    if title:
        if priority not in {"Baja", "Media", "Alta"}:
            priority = "Media"
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


@app.route("/api/music/search")
def search_music():
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"items": [], "message": "Escribe una canción, artista o estilo."}), 400
    if not api_key:
        return jsonify({
            "items": [],
            "message": "La búsqueda integrada necesita configurar YOUTUBE_API_KEY. Puedes abrir YouTube Music con el botón de abajo."
        })
    params = urlencode({
        "part": "snippet", "type": "video", "videoCategoryId": "10",
        "maxResults": 8, "safeSearch": "moderate", "q": query, "key": api_key
    })
    try:
        with urlopen("https://www.googleapis.com/youtube/v3/search?" + params, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = []
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if video_id:
                items.append({
                    "id": video_id,
                    "title": snippet.get("title", "Video sin título"),
                    "channel": snippet.get("channelTitle", "Canal de YouTube"),
                    "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", "")
                })
        return jsonify({"items": items, "message": ""})
    except HTTPError as error:
        message = "YouTube rechazó la búsqueda. Revisa la API habilitada, la clave y la cuota." if error.code in (400, 403) else "No se pudo buscar en YouTube."
        return jsonify({"items": [], "message": message}), 502
    except (URLError, TimeoutError, ValueError):
        return jsonify({"items": [], "message": "No se pudo conectar con YouTube. Inténtalo de nuevo."}), 502


init_db()

if __name__ == "__main__":
    app.run(debug=True)
