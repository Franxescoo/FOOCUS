from contextlib import contextmanager
from datetime import date, datetime, timedelta
import csv
import hashlib
import hmac
import io
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request

from flask import (
    Flask,
    abort,
    g,
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
    # Desktop builds embed their exact version; source installs default to the current release.
    APP_VERSION = os.environ.get("FOOCUS_VERSION", os.environ.get("FOCUSFLOW_VERSION", "V1.0.5"))


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FOCUSFLOW_SECRET_KEY") or secrets.token_hex(32),
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=64 * 1024,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FOCUSFLOW_SECURE_COOKIE", "").lower()
    in {"1", "true", "yes"},
)
DATABASE = Path(os.environ.get("FOCUSFLOW_DATABASE", str(Path(__file__).with_name("focusflow.db")))).expanduser()
UPDATE_DOWNLOAD_LOCK = threading.Lock()
UPDATE_DOWNLOAD_STATE = {
    "status": "idle",
    "progress": 0,
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "filename": "FOOCUS-Setup.exe",
    "version": "",
    "message": "Preparado para descargar una actualización.",
    "verified": False,
    "verification": "",
    "path": "",
}
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
    return {"csrf_token": csrf_token, "app_version": APP_VERSION, "csp_nonce": getattr(g, "csp_nonce", "")}


@app.before_request
def protect_state_changing_requests():
    g.csp_nonce = secrets.token_urlsafe(18)
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
    if request.path.startswith("/api/updates"):
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    nonce = getattr(g, "csp_nonce", "")
    response.headers.setdefault(
        "Content-Security-Policy",
        "; ".join([
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "img-src 'self' data:",
            "font-src 'self' https://fonts.gstatic.com data:",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            f"script-src 'self' 'nonce-{nonce}'",
            "connect-src 'self'",
            "frame-src 'none'",
        ]),
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
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
        theme_row = db.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = 'theme'"
        ).fetchone()
        saved_theme = theme_row["setting_value"] if theme_row and theme_row["setting_value"] in {"dark", "light"} else "light"
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
        saved_theme=saved_theme,
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
    """Read the latest GitHub release; public repositories do not require user tokens."""
    repository = os.environ.get("FOOCUS_GITHUB_REPOSITORY", "Franxescoo/FOOCUS").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": "La configuración del repositorio de actualizaciones no es válida.",
        }), 500

    # Public repositories work anonymously. Tokens remain optional and server-side only.
    token = (
        os.environ.get("FOOCUS_GITHUB_TOKEN")
        or os.environ.get("FOCUSFLOW_GITHUB_TOKEN")
        or ""
    ).strip()
    api_url = f"https://api.github.com/repos/{repository}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FOOCUS-update-check",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    github_request = urllib.request.Request(api_url, headers=headers)

    try:
        with urllib.request.urlopen(github_request, timeout=8) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        app.logger.warning("GitHub release check returned HTTP %s for %s", error.code, repository)
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": (
                "No se pudo consultar la última versión. Comprueba que el repositorio "
                "FOOCUS exista y sea público; si es privado, configura un token de lectura "
                "en el entorno del servidor."
            ),
        }), 502
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({
            "ok": False,
            "checkable": False,
            "available": False,
            "current_version": APP_VERSION,
            "message": "No se pudo conectar con GitHub. Revisa tu conexión e inténtalo de nuevo.",
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

    # Legacy builds such as "build-20" are older than semantic releases.
    available = latest_semver > current_semver if current_semver is not None else True
    repository_url = f"https://github.com/{repository}"
    return jsonify({
        "ok": True,
        "checkable": True,
        "available": available,
        "current_version": APP_VERSION,
        "latest_version": "V" + latest_version,
        "release_name": release.get("name") or ("FOOCUS V" + latest_version),
        "published_at": release.get("published_at"),
        "changes": release_change_items(release.get("body", "")),
        "release_url": repository_url + "/releases/latest",
        # Keep the asset name stable so existing installations can upgrade.
        "download_url": repository_url + "/releases/latest/download/FOOCUS-Setup.exe",
    })


def _update_download_snapshot():
    with UPDATE_DOWNLOAD_LOCK:
        return dict(UPDATE_DOWNLOAD_STATE)


def _update_download_response():
    state = _update_download_snapshot()
    # Never expose the full local path or private checksum data through the API.
    return {
        "ok": True,
        "status": state["status"],
        "progress": state["progress"],
        "downloaded_bytes": state["downloaded_bytes"],
        "total_bytes": state["total_bytes"],
        "filename": state["filename"],
        "version": state["version"],
        "message": state["message"],
        "verified": state["verified"],
        "verification": state["verification"],
        "save_location": "Descargas / FOOCUS",
    }


def _latest_installer_metadata():
    repository = os.environ.get("FOOCUS_GITHUB_REPOSITORY", "Franxescoo/FOOCUS").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise RuntimeError("La configuración del repositorio de FOOCUS no es válida.")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FOOCUS-updater",
    }
    token = (
        os.environ.get("FOOCUS_GITHUB_TOKEN")
        or os.environ.get("FOCUSFLOW_GITHUB_TOKEN")
        or ""
    ).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{repository}/releases/latest"
    try:
        with urllib.request.urlopen(urllib.request.Request(api_url, headers=headers), timeout=15) as response:
            release = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("No se pudo consultar la publicación oficial de FOOCUS. Comprueba tu conexión.") from error

    tag = str(release.get("tag_name") or "").strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag, re.IGNORECASE):
        raise RuntimeError("La publicación más reciente no tiene una versión válida.")

    latest_version = tag[1:] if tag[:1].lower() == "v" else tag
    latest_semver = parse_semantic_version(latest_version)
    current_semver = parse_semantic_version(APP_VERSION)
    if latest_semver is None:
        raise RuntimeError("No se pudo validar la versión publicada.")
    if current_semver is not None and latest_semver <= current_semver:
        raise RuntimeError("Esta instalación de FOOCUS ya está actualizada.")

    asset = next(
        (
            item for item in release.get("assets", [])
            if isinstance(item, dict) and item.get("name") == "FOOCUS-Setup.exe"
        ),
        None,
    )
    if not asset:
        raise RuntimeError("La publicación oficial no contiene FOOCUS-Setup.exe.")

    expected_url = f"https://github.com/{repository}/releases/download/{tag}/FOOCUS-Setup.exe"
    if asset.get("browser_download_url") != expected_url:
        raise RuntimeError("El enlace del instalador no coincide con la publicación oficial.")

    try:
        expected_size = int(asset.get("size") or 0)
    except (TypeError, ValueError) as error:
        raise RuntimeError("La publicación no informa un tamaño válido para el instalador.") from error
    if expected_size <= 0:
        raise RuntimeError("La publicación no informa el tamaño del instalador.")

    digest = str(asset.get("digest") or "").strip().lower()
    if digest and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError("La publicación informa una huella digital no válida.")

    return {
        "version": "V" + latest_version,
        "url": expected_url,
        "size": expected_size,
        "sha256": digest.removeprefix("sha256:") if digest else "",
    }


def _download_latest_installer():
    partial_path = None
    try:
        metadata = _latest_installer_metadata()
        with UPDATE_DOWNLOAD_LOCK:
            UPDATE_DOWNLOAD_STATE.update({
                "status": "downloading",
                "progress": 0,
                "downloaded_bytes": 0,
                "total_bytes": metadata["size"],
                "version": metadata["version"],
                "message": "Conectando con la publicación oficial de FOOCUS…",
                "verified": False,
                "verification": "",
                "path": "",
            })

        configured_dir = os.environ.get("FOOCUS_DOWNLOAD_DIR", "").strip()
        download_dir = (
            Path(configured_dir).expanduser()
            if configured_dir
            else Path.home() / "Downloads" / "FOOCUS"
        )
        download_dir.mkdir(parents=True, exist_ok=True)
        installer_path = download_dir / "FOOCUS-Setup.exe"
        partial_path = download_dir / "FOOCUS-Setup.exe.part"

        request_headers = {
            "Accept": "application/octet-stream",
            "User-Agent": "FOOCUS-updater",
        }
        installer_request = urllib.request.Request(metadata["url"], headers=request_headers)
        digest = hashlib.sha256()
        downloaded_bytes = 0
        with urllib.request.urlopen(installer_request, timeout=30) as response:
            raw_length = response.headers.get("Content-Length")
            content_length = int(raw_length) if raw_length and raw_length.isdigit() else 0
            if content_length and content_length != metadata["size"]:
                raise RuntimeError("El tamaño del archivo no coincide con el publicado por GitHub.")

            with partial_path.open("wb") as installer_file:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    installer_file.write(chunk)
                    digest.update(chunk)
                    downloaded_bytes += len(chunk)
                    percentage = min(99, int(downloaded_bytes * 100 / metadata["size"]))
                    with UPDATE_DOWNLOAD_LOCK:
                        UPDATE_DOWNLOAD_STATE.update({
                            "progress": percentage,
                            "downloaded_bytes": downloaded_bytes,
                            "total_bytes": metadata["size"],
                            "message": "Descargando el instalador oficial…",
                        })

        if downloaded_bytes != metadata["size"]:
            raise RuntimeError("La descarga quedó incompleta. No se conservará el archivo.")

        actual_digest = digest.hexdigest()
        if metadata["sha256"] and actual_digest != metadata["sha256"]:
            raise RuntimeError("La huella SHA-256 no coincide. El archivo se descartó por seguridad.")

        os.replace(partial_path, installer_path)
        verification = "SHA-256" if metadata["sha256"] else "tamaño"
        message = (
            "Descarga completa y verificada mediante SHA-256."
            if metadata["sha256"]
            else "Descarga completa; el tamaño coincide con la publicación oficial."
        )
        with UPDATE_DOWNLOAD_LOCK:
            UPDATE_DOWNLOAD_STATE.update({
                "status": "complete",
                "progress": 100,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": metadata["size"],
                "filename": "FOOCUS-Setup.exe",
                "version": metadata["version"],
                "message": message,
                "verified": True,
                "verification": verification,
                "path": str(installer_path),
            })
    except Exception as error:
        app.logger.warning("FOOCUS installer download failed: %s", error, exc_info=True)
        if partial_path is not None:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                app.logger.warning("Could not remove partial FOOCUS installer", exc_info=True)
        if isinstance(error, RuntimeError):
            user_message = str(error)
        else:
            user_message = "No se pudo completar la descarga. Comprueba tu conexión y el espacio disponible, y vuelve a intentarlo."
        with UPDATE_DOWNLOAD_LOCK:
            UPDATE_DOWNLOAD_STATE.update({
                "status": "failed",
                "progress": 0,
                "message": user_message,
                "verified": False,
                "verification": "",
                "path": "",
            })


@app.route("/api/updates/download/status")
def update_download_status():
    return jsonify(_update_download_response())


@app.route("/api/updates/download", methods=["POST"])
def start_update_download():
    with UPDATE_DOWNLOAD_LOCK:
        already_downloading = UPDATE_DOWNLOAD_STATE["status"] in {"starting", "downloading"}
        if not already_downloading:
            UPDATE_DOWNLOAD_STATE.update({
                "status": "starting",
                "progress": 0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "filename": "FOOCUS-Setup.exe",
                "version": "",
                "message": "Preparando una descarga segura…",
                "verified": False,
                "verification": "",
                "path": "",
            })
    if already_downloading:
        payload = _update_download_response()
        payload["ok"] = False
        return jsonify(payload), 409

    worker = threading.Thread(
        target=_download_latest_installer,
        name="FOOCUS-installer-download",
        daemon=True,
    )
    worker.start()
    return jsonify(_update_download_response()), 202


@app.route("/api/updates/download/open", methods=["POST"])
def open_downloaded_installer():
    with UPDATE_DOWNLOAD_LOCK:
        path_value = UPDATE_DOWNLOAD_STATE.get("path", "")
        completed = UPDATE_DOWNLOAD_STATE.get("status") == "complete"
        verified = bool(UPDATE_DOWNLOAD_STATE.get("verified"))
    if not completed or not verified or not path_value or not Path(path_value).is_file():
        return jsonify({
            "ok": False,
            "message": "Primero termina y verifica la descarga del instalador.",
        }), 409
    if os.name != "nt" or not hasattr(os, "startfile"):
        return jsonify({
            "ok": False,
            "message": "El instalador se guardó en Descargas / FOOCUS. Ábrelo desde esa carpeta en Windows.",
        }), 501
    try:
        getattr(os, "startfile")(path_value)
    except OSError:
        app.logger.warning("Could not open FOOCUS installer", exc_info=True)
        return jsonify({
            "ok": False,
            "message": "No se pudo abrir el instalador. Encuéntralo en Descargas / FOOCUS e inténtalo manualmente.",
        }), 500
    return jsonify({
        "ok": True,
        "message": "Se abrió el instalador oficial de FOOCUS. Revisa los pasos del asistente para actualizar.",
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


@app.route("/api/settings/theme", methods=["PUT"])
def update_theme():
    """Persist the selected appearance in the local settings database."""
    payload = request.get_json(silent=True) or {}
    theme = payload.get("theme")
    if theme not in {"dark", "light"}:
        return jsonify({"ok": False, "message": "Selecciona un tema válido."}), 400

    with get_db() as db:
        db.execute(
            """INSERT INTO app_settings (setting_key, setting_value, updated_at)
               VALUES ('theme', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP""",
            (theme,),
        )

    return jsonify({"ok": True, "theme": theme})


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


def spreadsheet_safe(value):
    """Prevent user-controlled text from being interpreted as a spreadsheet formula."""
    text = "" if value is None else str(value)
    # Excel and similar spreadsheet apps can execute formulas after common whitespace.
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


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
