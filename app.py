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
    query = request.args.get("q", "").strip()
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
                "channel": artist_names or song.get("album", {}).get("name", "YouTube Music"),
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
