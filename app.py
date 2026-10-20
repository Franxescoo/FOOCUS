from contextlib import contextmanager
from datetime import date, datetime, timedelta
import csv
import hmac
import io
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import urllib.error
import urllib.request

from flask import (
    Flask,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

try:
    from focusflow_build import APP_VERSION
except ImportError:
    # The first semantic release is V1.0.0; desktop builds embed their exact version.
    APP_VERSION = os.environ.get("FOCUSFLOW_VERSION", "V1.0.0")


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FOCUSFLOW_SECRET_KEY") or secrets.token_hex(32),
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FOCUSFLOW_SECURE_COOKIE", "").lower()
    in {"1", "true", "yes"},
)
DATABASE = Path(os.environ.get("FOCUSFLOW_DATABASE", str(Path(__file__).with_name("focusflow.db")))).expanduser()
VALID_PRIORITIES = {"Baja", "Media", "Alta"}
ALLOWED_ESTIMATED_MINUTES = {15, 30, 45, 60, 90, 120, 180, 240, 300, 360, 480, 600}
MAX_SUBJECT_NAME_LENGTH = 60
DEFAULT_STUDY_GOAL_MINUTES = 120
MIN_STUDY_GOAL_MINUTES = 15
MAX_STUDY_GOAL_MINUTES = 600


@contextmanager
def get_db():
    """Open one SQLite connection per operation and always close it."""
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    """Create the current schema and small indexes; safe to run on old databases."""
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'Media',
                due_date TEXT,
                planned_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
                estimated_minutes INTEGER NOT NULL DEFAULT 30
            )
            """
        )
        # Keep existing installations and their task history intact.
        task_columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
        if "subject_id" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL")
        if "estimated_minutes" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER NOT NULL DEFAULT 30")
        if "planned_date" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN planned_date TEXT")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                comment TEXT NOT NULL DEFAULT '',
                next_step TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            """
        )
        session_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(work_sessions)").fetchall()
        }
        if "next_step" not in session_columns:
            db.execute("ALTER TABLE work_sessions ADD COLUMN next_step TEXT NOT NULL DEFAULT ''")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            INSERT OR IGNORE INTO app_settings (setting_key, setting_value)
            VALUES ('study_goal_minutes', ?)
            """,
            (str(DEFAULT_STUDY_GOAL_MINUTES),),
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_state_due ON tasks(completed, due_date, id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_subject ON tasks(subject_id, completed)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_task_started ON work_sessions(task_id, started_at DESC)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_started_ended ON work_sessions(started_at, ended_at)"
        )


def csrf_token():
    """Return a per-session token used to protect every state-changing request."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token, "app_version": APP_VERSION}


@app.before_request
def protect_state_changing_requests():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    expected = session.get("_csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        if request.is_json:
            return jsonify({
                "ok": False,
                "message": "La sesión de seguridad venció. Recarga la página e inténtalo de nuevo.",
            }), 400
        abort(400, description="No se pudo validar la solicitud. Recarga la página e inténtalo de nuevo.")
    return None


@app.after_request
def add_security_headers(response):
    if request.path == "/api/updates":
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.errorhandler(400)
def bad_request(error):
    if request.is_json:
        return jsonify({"ok": False, "message": "La solicitud no es válida."}), 400
    return render_template(
        "error.html",
        status_code=400,
        title="No pudimos validar la solicitud",
        message="Recarga la página para actualizar la sesión de seguridad y vuelve a intentarlo.",
    ), 400


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "No encontramos el recurso solicitado."}), 404
    return render_template(
        "error.html",
        status_code=404,
        title="No encontramos esa página",
        message="Puede que el enlace haya cambiado o que el contenido ya no exista.",
    ), 404


def valid_due_date(value):
    """Accept an empty date or a real ISO calendar date."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return False

def normalize_subject_name(value):
    """Normalize a user-entered subject label and cap its size."""
    return " ".join(str(value or "").split())[:MAX_SUBJECT_NAME_LENGTH]


def get_or_create_subject(db, value):
    """Resolve a subject name to a stable ID, case-insensitively."""
    name = normalize_subject_name(value)
    if not name:
        return None
    db.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (name,))
    row = db.execute(
        "SELECT id FROM subjects WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row["id"] if row else None


def parse_estimated_minutes(value):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if minutes in ALLOWED_ESTIMATED_MINUTES else None



def get_study_goal_minutes(db):
    row = db.execute(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'study_goal_minutes'"
    ).fetchone()
    try:
        value = int(row["setting_value"]) if row else DEFAULT_STUDY_GOAL_MINUTES
    except (TypeError, ValueError):
        value = DEFAULT_STUDY_GOAL_MINUTES
    return min(MAX_STUDY_GOAL_MINUTES, max(MIN_STUDY_GOAL_MINUTES, value))


@app.route("/")
def index():
    today_date = date.today()
    week_start = today_date - timedelta(days=today_date.weekday())

    with get_db() as db:
        tasks = db.execute(
            """SELECT t.*, s.name AS subject_name
               FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id
               ORDER BY t.completed ASC,
               CASE WHEN t.due_date IS NULL OR t.due_date = '' THEN 1 ELSE 0 END,
               t.due_date ASC, t.id DESC"""
        ).fetchall()
        sessions = db.execute(
            """SELECT ws.*, t.title AS task_title, t.subject_id FROM work_sessions ws
               JOIN tasks t ON t.id = ws.task_id
               WHERE ws.ended_at IS NOT NULL ORDER BY ws.started_at DESC"""
        ).fetchall()
        active_session = db.execute(
            """SELECT ws.*, t.title AS task_title, t.subject_id FROM work_sessions ws
               JOIN tasks t ON t.id = ws.task_id
               WHERE ws.ended_at IS NULL ORDER BY ws.id DESC LIMIT 1"""
        ).fetchone()
        all_subjects = db.execute("SELECT id, name FROM subjects ORDER BY name COLLATE NOCASE").fetchall()
        study_goal_minutes = get_study_goal_minutes(db)

    total = len(tasks)
    completed = sum(task["completed"] for task in tasks)
    work_stats = {}
    active_days_by_task = {}
    activity_by_day = {}
    total_work_seconds = 0
    today_work_seconds = 0
    week_work_seconds = 0
    today_session_count = 0
    subject_work_seconds = {}

    for work_session in sessions:
        started = datetime.fromisoformat(work_session["started_at"])
        day_key = started.date().isoformat()
        seconds = max(0, int(work_session["duration_seconds"] or 0))
        total_work_seconds += seconds
        activity_by_day[day_key] = activity_by_day.get(day_key, 0) + seconds
        if started.date() == today_date:
            today_work_seconds += seconds
            today_session_count += 1
        if started.date() >= week_start:
            week_work_seconds += seconds

        subject_id = work_session["subject_id"]
        if subject_id is not None:
            subject_work_seconds[subject_id] = subject_work_seconds.get(subject_id, 0) + seconds
        task_id = work_session["task_id"]
        work_stats.setdefault(task_id, {
            "seconds": 0, "sessions": 0, "last_comment": "", "last_next_step": ""
        })
        work_stats[task_id]["seconds"] += seconds
        work_stats[task_id]["sessions"] += 1
        if not work_stats[task_id]["last_comment"] and work_session["comment"]:
            work_stats[task_id]["last_comment"] = work_session["comment"]
        if not work_stats[task_id]["last_next_step"] and work_session["next_step"]:
            work_stats[task_id]["last_next_step"] = work_session["next_step"]
        active_days_by_task.setdefault(task_id, set()).add(day_key)

    task_streaks = {}
    for task in tasks:
        days = active_days_by_task.get(task["id"], set())
        cursor_day = today_date if today_date.isoformat() in days else today_date - timedelta(days=1)
        streak = 0
        while cursor_day.isoformat() in days:
            streak += 1
            cursor_day -= timedelta(days=1)
        task_streaks[task["id"]] = streak

    weekday_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    week_plan_days = []
    week_plan_count = 0
    for offset in range(7):
        plan_date = today_date + timedelta(days=offset)
        day_tasks = [
            task for task in tasks
            if not task["completed"] and task["planned_date"] == plan_date.isoformat()
        ]
        day_tasks.sort(key=lambda task: (
            {"Alta": 0, "Media": 1, "Baja": 2}.get(task["priority"], 1),
            task["due_date"] or "9999-12-31",
            task["title"].casefold(),
        ))
        week_plan_count += len(day_tasks)
        week_plan_days.append({
            "date": plan_date.isoformat(),
            "label": "Hoy" if offset == 0 else f"{weekday_names[plan_date.weekday()].capitalize()} {plan_date.strftime('%d/%m')}",
            "is_today": offset == 0,
            "tasks": day_tasks,
        })

    activity_days = []
    for offset in range(34, -1, -1):
        day = today_date - timedelta(days=offset)
        seconds = activity_by_day.get(day.isoformat(), 0)
        activity_days.append({
            "date": day.isoformat(),
            "label": day.strftime("%d/%m"),
            "seconds": seconds,
            "minutes": seconds // 60,
            "level": 0 if seconds == 0 else (
                1 if seconds < 1800 else (
                    2 if seconds < 7200 else (
                        3 if seconds < 14400 else 4
                    )
                )
            ),
        })

    subject_summaries = []
    for subject in all_subjects:
        subject_tasks = [task for task in tasks if task["subject_id"] == subject["id"]]
        pending_tasks = [task for task in subject_tasks if not task["completed"]]
        subject_summaries.append({
            "id": subject["id"],
            "name": subject["name"],
            "task_count": len(subject_tasks),
            "pending_count": len(pending_tasks),
            "pending_estimated_minutes": sum(int(task["estimated_minutes"] or 30) for task in pending_tasks),
            "actual_seconds": subject_work_seconds.get(subject["id"], 0),
        })

    goal_seconds = study_goal_minutes * 60
    goal_progress_percent = min(100, round(today_work_seconds / goal_seconds * 100)) if goal_seconds else 0
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
        week_work_seconds=week_work_seconds,
        total_session_count=len(sessions),
        today_session_count=today_session_count,
        subjects=all_subjects,
        subject_summaries=subject_summaries,
        week_plan_days=week_plan_days,
        week_plan_count=week_plan_count,
        study_goal_minutes=study_goal_minutes,
        goal_progress_percent=goal_progress_percent,
        active_session=active_session,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response



def parse_semantic_version(value):
    """Return a comparable semantic-version tuple, or None for non-release builds."""
    match = re.fullmatch(r"[vV]?(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def release_change_items(body):
    """Extract human-readable change bullets from GitHub's generated release notes."""
    lines = str(body or "").splitlines()
    for index, line in enumerate(lines):
        if line.strip().casefold() in {"## what's changed", "## what’s changed"}:
            lines = lines[index + 1:]
            break
    else:
        lines = [line for line in lines if line.strip().startswith(("-", "*"))]

    items = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("**Full Changelog**"):
            break
        if not stripped.startswith(("-", "*")):
            continue
        item = stripped[1:].strip()
        item = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", item)
        item = re.sub(r"\s+by @[^ ]+ in https?://\S+", "", item).strip()
        item = re.sub(r"\s+", " ", item)
        if item and item not in items:
            items.append(item[:240])
        if len(items) >= 8:
            break
    return items


@app.route("/api/updates")
def check_for_updates():
    """Check private GitHub releases using a server-side, read-only token."""
    token = os.environ.get("FOCUSFLOW_GITHUB_TOKEN", "").strip()
    if not token:
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": (
                "La detección automática necesita configurar FOCUSFLOW_GITHUB_TOKEN "
                "en el servidor. No se debe guardar el token dentro del programa."
            ),
        }), 503

    api_url = "https://api.github.com/repos/Franxescoo/FocusFlow/releases/latest"
    github_request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FocusFlow-update-check",
        },
    )
    try:
        with urllib.request.urlopen(github_request, timeout=5) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        app.logger.warning("GitHub release check returned HTTP %s", error.code)
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": (
                "GitHub no permitió consultar las versiones. Comprueba que "
                "FOCUSFLOW_GITHUB_TOKEN tenga permiso de lectura del repositorio."
            ),
        }), 502
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": "No se pudo consultar GitHub. Revisa la conexión e inténtalo de nuevo.",
        }), 502

    latest_version = str(release.get("tag_name") or "").strip().lstrip("vV")
    current_semver = parse_semantic_version(APP_VERSION)
    latest_semver = parse_semantic_version(latest_version)
    if latest_semver is None:
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": "La última publicación de GitHub no tiene una versión semántica válida.",
        }), 502

    # Legacy builds such as "build-20" are considered older than the first semantic release.
    available = latest_semver > current_semver if current_semver is not None else True
    return jsonify({
        "ok": True,
        "checkable": True,
        "available": available,
        "current_version": APP_VERSION,
        "latest_version": "V" + latest_version,
        "release_name": release.get("name") or ("FocusFlow V" + latest_version),
        "published_at": release.get("published_at"),
        "changes": release_change_items(release.get("body", "")),
        "release_url": "https://github.com/Franxescoo/FocusFlow/releases/latest",
        "download_url": "https://github.com/Franxescoo/FocusFlow/releases/latest/download/FocusFlow-Setup.exe",
    })


@app.route("/tasks", methods=["POST"])
def add_task():
    title = request.form.get("title", "").strip()[:160]
    priority = request.form.get("priority", "Media")
    raw_due_date = request.form.get("due_date", "").strip()
    due_date = valid_due_date(raw_due_date)
    planned_date = valid_due_date(request.form.get("planned_date", "").strip())
    subject_name = normalize_subject_name(request.form.get("subject", ""))
    estimated_minutes = parse_estimated_minutes(request.form.get("estimated_minutes", 30))

    if not title:
        return redirect(url_for("index"))
    if priority not in VALID_PRIORITIES:
        priority = "Media"
    if due_date is False:
        due_date = None
    if planned_date is False:
        planned_date = None
    if estimated_minutes is None:
        estimated_minutes = 30

    with get_db() as db:
        subject_id = get_or_create_subject(db, subject_name)
        db.execute(
            """INSERT INTO tasks (title, priority, due_date, planned_date, subject_id, estimated_minutes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, priority, due_date, planned_date, subject_id, estimated_minutes),
        )
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id):
    with get_db() as db:
        db.execute(
            """UPDATE tasks
               SET completed = CASE completed WHEN 0 THEN 1 ELSE 0 END
               WHERE id = ?""",
            (task_id,),
        )
    return redirect(url_for("index"))


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id):
    with get_db() as db:
        active_session = db.execute(
            "SELECT id FROM work_sessions WHERE task_id = ? AND ended_at IS NULL LIMIT 1",
            (task_id,),
        ).fetchone()
        if active_session:
            abort(400, description="Termina la sesión de trabajo antes de eliminar esta tarea.")
        cursor = db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            abort(404)
    return redirect(url_for("index"))


@app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
def edit_task(task_id):
    """Update an existing task from the inline editor."""
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()[:160]
    priority = payload.get("priority", "Media")
    due_date = valid_due_date(str(payload.get("due_date", "")).strip())
    planned_date = valid_due_date(str(payload.get("planned_date", "")).strip())
    subject_name = normalize_subject_name(payload.get("subject", ""))
    estimated_minutes = parse_estimated_minutes(payload.get("estimated_minutes", 30))

    if not title:
        return jsonify({"ok": False, "message": "El nombre de la tarea no puede estar vacío."}), 400
    if priority not in VALID_PRIORITIES:
        return jsonify({"ok": False, "message": "Selecciona una prioridad válida."}), 400
    if due_date is False:
        return jsonify({"ok": False, "message": "La fecha límite no es válida."}), 400
    if planned_date is False:
        return jsonify({"ok": False, "message": "La fecha planificada no es válida."}), 400
    if estimated_minutes is None:
        return jsonify({"ok": False, "message": "Selecciona una estimación válida."}), 400

    with get_db() as db:
        exists = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not exists:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        subject_id = get_or_create_subject(db, subject_name)
        db.execute(
            """UPDATE tasks SET title = ?, priority = ?, due_date = ?, planned_date = ?,
               subject_id = ?, estimated_minutes = ? WHERE id = ?""",
            (title, priority, due_date, planned_date, subject_id, estimated_minutes, task_id),
        )
        subject = db.execute(
            "SELECT name FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone() if subject_id else None

    return jsonify({
        "ok": True,
        "task": {
            "id": task_id,
            "title": title,
            "priority": priority,
            "due_date": due_date,
            "planned_date": planned_date,
            "subject": subject["name"] if subject else "",
            "estimated_minutes": estimated_minutes,
        },
    })


@app.route("/api/settings/study-goal", methods=["PUT"])
def update_study_goal():
    payload = request.get_json(silent=True) or {}
    try:
        minutes = int(payload.get("minutes"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Selecciona una meta diaria válida."}), 400

    if minutes < MIN_STUDY_GOAL_MINUTES or minutes > MAX_STUDY_GOAL_MINUTES or minutes % 15 != 0:
        return jsonify({
            "ok": False,
            "message": f"La meta debe estar entre {MIN_STUDY_GOAL_MINUTES} y {MAX_STUDY_GOAL_MINUTES} minutos, en intervalos de 15.",
        }), 400

    with get_db() as db:
        db.execute(
            """INSERT INTO app_settings (setting_key, setting_value, updated_at)
               VALUES ('study_goal_minutes', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP""",
            (str(minutes),),
        )

    return jsonify({"ok": True, "minutes": minutes})


@app.route("/api/work/start", methods=["POST"])
def start_work():
    payload = request.get_json(silent=True) or {}
    try:
        task_id = int(payload.get("task_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Selecciona una tarea válida."}), 400

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with get_db() as db:
        # Acquire the SQLite write lock before checking for an active session so
        # two fast requests cannot both pass the check and start overlapping work.
        db.execute("BEGIN IMMEDIATE")
        task = db.execute("SELECT id, title, completed FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        if task["completed"]:
            return jsonify({"ok": False, "message": "Esa tarea ya está completada. Reábrela para registrar más trabajo."}), 409
        active = db.execute(
            "SELECT id FROM work_sessions WHERE ended_at IS NULL LIMIT 1"
        ).fetchone()
        if active:
            return jsonify({
                "ok": False,
                "message": "Ya hay una sesión en curso. Termínala antes de empezar otra.",
            }), 409
        cursor = db.execute(
            "INSERT INTO work_sessions (task_id, started_at) VALUES (?, ?)",
            (task_id, started_at),
        )
        session_id = cursor.lastrowid
    return jsonify({
        "ok": True,
        "session_id": session_id,
        "task_id": task_id,
        "task_title": task["title"],
        "started_at": started_at,
    })


@app.route("/api/work/stop", methods=["POST"])
def stop_work():
    payload = request.get_json(silent=True) or {}
    comment = str(payload.get("comment", "")).strip()[:1000]
    next_step = str(payload.get("next_step", "")).strip()[:500]
    ended_at = datetime.now().astimezone().isoformat(timespec="seconds")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        work_session = db.execute(
            "SELECT * FROM work_sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not work_session:
            return jsonify({"ok": False, "message": "No hay ninguna sesión en curso."}), 409
        started_at = datetime.fromisoformat(work_session["started_at"])
        ended = datetime.fromisoformat(ended_at)
        duration = max(0, int((ended - started_at).total_seconds()))
        db.execute(
            """UPDATE work_sessions
               SET ended_at = ?, duration_seconds = ?, comment = ?, next_step = ?
               WHERE id = ?""",
            (ended_at, duration, comment, next_step, work_session["id"]),
        )
    return jsonify({
        "ok": True,
        "duration_seconds": duration,
        "comment": comment,
        "next_step": next_step,
        "message": "Sesión guardada.",
    })


@app.route("/api/tasks/<int:task_id>/work-log")
def task_work_log(task_id):
    with get_db() as db:
        task = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        logs = db.execute(
            """SELECT id, started_at, ended_at, duration_seconds, comment, next_step
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
            return jsonify({
                "items": [],
                "message": "No encontré canciones con esa búsqueda. Prueba con otro término.",
            })
        return jsonify({"items": items, "message": ""})
    except ImportError:
        return jsonify({
            "items": [],
            "message": "Falta instalar ytmusicapi. En la terminal ejecuta: pip install -r requirements.txt",
        }), 503
    except Exception:
        app.logger.exception("Error buscando música con ytmusicapi")
        return jsonify({
            "items": [],
            "message": "YouTube Music no respondió como se esperaba. La búsqueda usa una interfaz no oficial; prueba más tarde o abre YouTube Music.",
        }), 502


def spreadsheet_safe(value):
    """Avoid CSV formula injection when exported strings are opened in spreadsheet apps."""
    if value is None:
        return ""
    text_value = str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


@app.route("/export.csv")
def export_csv():
    """Download tasks and their saved work sessions as a spreadsheet-friendly CSV."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT t.id, t.title, t.priority, t.due_date, t.planned_date, t.completed, t.created_at,
                   t.estimated_minutes, s.name AS subject_name,
                   ws.started_at, ws.ended_at, ws.duration_seconds, ws.comment, ws.next_step
            FROM tasks t
            LEFT JOIN subjects s ON s.id = t.subject_id
            LEFT JOIN work_sessions ws ON ws.task_id = t.id AND ws.ended_at IS NOT NULL
            ORDER BY t.id ASC, ws.started_at ASC
            """
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "ID tarea", "Tarea", "Asignatura", "Estimación (minutos)", "Fecha planificada",
        "Prioridad", "Fecha límite", "Completada", "Creada el", "Inicio sesión",
        "Fin sesión", "Duración (segundos)", "Comentario de sesión", "Siguiente paso",
    ])
    for row in rows:
        writer.writerow([
            row["id"],
            spreadsheet_safe(row["title"]),
            spreadsheet_safe(row["subject_name"] or ""),
            row["estimated_minutes"],
            row["planned_date"] or "",
            spreadsheet_safe(row["priority"]),
            row["due_date"] or "",
            "Sí" if row["completed"] else "No",
            row["created_at"],
            row["started_at"] or "",
            row["ended_at"] or "",
            row["duration_seconds"] if row["ended_at"] else "",
            spreadsheet_safe(row["comment"]) if row["ended_at"] else "",
            spreadsheet_safe(row["next_step"]) if row["ended_at"] else "",
        ])

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="focusflow-export.csv"'
    response.headers["Cache-Control"] = "no-store"
    return response


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
