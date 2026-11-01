from contextlib import contextmanager
from datetime import date, datetime, timedelta
import csv
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import re
from pathlib import Path
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
import zipfile

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from urllib.parse import urlsplit
from werkzeug.utils import secure_filename

try:
    from focusflow_build import APP_VERSION
except ImportError:
    # Source installs display the evolution line; desktop builds embed their own version.
    APP_VERSION = os.environ.get("FOOCUS_VERSION", os.environ.get("FOCUSFLOW_VERSION", "V1.1.0+"))


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FOCUSFLOW_SECRET_KEY") or secrets.token_hex(32),
    TEMPLATES_AUTO_RELOAD=True,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
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
DEFAULT_PRODUCTIVITY_PROFILE = {
    "adaptive_enabled": True, "available_days": [0,1,2,3,4],
    "start_time": "16:00", "end_time": "20:00", "session_minutes": 45,
    "break_minutes": 10, "daily_capacity_minutes": 180, "planning_horizon_days": 7,
    "accent": "violet", "compact_mode": False,
    "dashboard_widgets": ["welcome","summary","starter","weekly","analytics"],
}
ALLOWED_SESSION_MINUTES = {15,25,30,45,60,90,120}
ALLOWED_BREAK_MINUTES = {5,10,15,20,30}
ALLOWED_DASHBOARD_WIDGETS = {"welcome","summary","starter","weekly","analytics"}
ALLOWED_ACCENTS = {"violet","blue","green","rose"}


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
            CREATE TABLE IF NOT EXISTS task_study_days (
                task_id INTEGER NOT NULL,
                study_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (task_id, study_date),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
            """
        )
        # Migrate each still-relevant legacy planned date into the new multi-day calendar.
        db.execute(
            """
            INSERT OR IGNORE INTO task_study_days (task_id, study_date)
            SELECT id, planned_date FROM tasks
            WHERE planned_date IS NOT NULL AND planned_date <> ''
              AND planned_date >= date('now', 'localtime')
              AND (due_date IS NULL OR due_date = '' OR planned_date <= due_date)
            """
        )
        # Expired planned days are not future appointments; real study history is kept in work_sessions.
        db.execute(
            "DELETE FROM task_study_days WHERE study_date < date('now', 'localtime')"
        )
        db.execute(
            """
            UPDATE tasks
            SET planned_date = (
                SELECT MIN(study_date) FROM task_study_days
                WHERE task_study_days.task_id = tasks.id
            )
            WHERE planned_date IS NOT NULL AND planned_date < date('now', 'localtime')
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
            "CREATE INDEX IF NOT EXISTS idx_task_study_days_date ON task_study_days(study_date, task_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_task_started ON work_sessions(task_id, started_at DESC)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_started_ended ON work_sessions(started_at, ended_at)"
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS planned_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                planned_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, planned_date, start_time),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )"""
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_planned_sessions_date ON planned_sessions(planned_date, start_time)")
        # Canvas foundation: additive tables; existing tasks and work history stay untouched.
        db.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT 'violet' CHECK (color IN ('violet','blue','green','rose')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER,
                title TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'free' CHECK (mode IN ('free','structured')),
                viewport_json TEXT NOT NULL DEFAULT '{"x":0,"y":0,"zoom":1}',
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_boards_workspace ON canvas_boards(workspace_id, updated_at DESC)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_columns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                column_key TEXT NOT NULL,
                title TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                UNIQUE(board_id, column_key),
                FOREIGN KEY (board_id) REFERENCES canvas_boards(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_elements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                element_key TEXT NOT NULL,
                column_key TEXT,
                kind TEXT NOT NULL CHECK (kind IN ('note','text','group','card')),
                x REAL NOT NULL DEFAULT 80,
                y REAL NOT NULL DEFAULT 80,
                width REAL NOT NULL DEFAULT 240,
                height REAL NOT NULL DEFAULT 150,
                content_json TEXT NOT NULL DEFAULT '{}',
                task_id INTEGER,
                task_snapshot_title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_id, element_key),
                FOREIGN KEY (board_id) REFERENCES canvas_boards(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                connection_key TEXT NOT NULL,
                source_key TEXT NOT NULL,
                target_key TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                UNIQUE(board_id, connection_key),
                FOREIGN KEY (board_id) REFERENCES canvas_boards(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_columns_board ON canvas_columns(board_id, position)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_elements_board ON canvas_elements(board_id, kind)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_elements_task ON canvas_elements(task_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_connections_board ON canvas_connections(board_id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_id, version_number),
                FOREIGN KEY (board_id) REFERENCES canvas_boards(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_history_board_version ON canvas_history(board_id, version_number DESC)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS canvas_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                element_key TEXT NOT NULL,
                attachment_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK (kind IN ('file','link')),
                original_name TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                relative_path TEXT,
                url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (board_id) REFERENCES canvas_boards(id) ON DELETE CASCADE
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_canvas_attachments_board_element ON canvas_attachments(board_id, element_key)")


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
    """Accept an empty date or a canonical YYYY-MM-DD date."""
    if not value:
        return None
    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return parsed.isoformat() if parsed.isoformat()==value else False

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


def clock_minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return None
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 60 + minutes


def normalize_productivity_profile(payload, current=None):
    if not isinstance(payload, dict):
        return None
    profile = dict(DEFAULT_PRODUCTIVITY_PROFILE)
    if isinstance(current, dict):
        profile.update(current)
    adaptive = payload.get("adaptive_enabled", profile["adaptive_enabled"])
    compact = payload.get("compact_mode", profile["compact_mode"])
    if type(adaptive) is not bool or type(compact) is not bool:
        return None
    days = payload.get("available_days", profile["available_days"])
    if not isinstance(days, list) or not days or any(type(day) is not int or day < 0 or day > 6 for day in days):
        return None
    days = sorted(set(days))
    start, end = payload.get("start_time", profile["start_time"]), payload.get("end_time", profile["end_time"])
    start_min, end_min = clock_minutes(start), clock_minutes(end)
    if start_min is None or end_min is None or end_min - start_min < 15:
        return None
    session = payload.get("session_minutes", profile["session_minutes"])
    rest = payload.get("break_minutes", profile["break_minutes"])
    capacity = payload.get("daily_capacity_minutes", profile["daily_capacity_minutes"])
    horizon = payload.get("planning_horizon_days", profile["planning_horizon_days"])
    if type(session) is not int or session not in ALLOWED_SESSION_MINUTES:
        return None
    if type(rest) is not int or rest not in ALLOWED_BREAK_MINUTES:
        return None
    if type(capacity) is not int or capacity < 30 or capacity > 600 or capacity % 15:
        return None
    if type(horizon) is not int or horizon not in {7,14,21,30} or session > end_min - start_min:
        return None
    accent = payload.get("accent", profile["accent"])
    if accent not in ALLOWED_ACCENTS:
        return None
    widgets = payload.get("dashboard_widgets", profile["dashboard_widgets"])
    if not isinstance(widgets, list) or any(not isinstance(w, str) or w not in ALLOWED_DASHBOARD_WIDGETS for w in widgets):
        return None
    return {"adaptive_enabled": adaptive, "available_days": days, "start_time": start, "end_time": end,
            "session_minutes": session, "break_minutes": rest, "daily_capacity_minutes": capacity,
            "planning_horizon_days": horizon, "accent": accent, "compact_mode": compact,
            "dashboard_widgets": list(dict.fromkeys(widgets))}


def get_productivity_profile(db):
    row = db.execute("SELECT setting_value FROM app_settings WHERE setting_key='productivity_profile'").fetchone()
    if not row:
        return dict(DEFAULT_PRODUCTIVITY_PROFILE)
    try:
        saved = json.loads(row["setting_value"])
    except (TypeError, ValueError, json.JSONDecodeError):
        saved = {}
    return normalize_productivity_profile(saved, DEFAULT_PRODUCTIVITY_PROFILE) or dict(DEFAULT_PRODUCTIVITY_PROFILE)


def save_productivity_profile(db, profile):
    db.execute(
        """INSERT INTO app_settings (setting_key,setting_value,updated_at)
           VALUES ('productivity_profile',?,CURRENT_TIMESTAMP)
           ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP""",
        (json.dumps(profile, ensure_ascii=False, separators=(",",":")),),
    )


def build_productivity_plan(db, profile, horizon_days):
    today = date.today()
    rows = db.execute(
        """SELECT t.id,t.title,t.priority,t.due_date,t.estimated_minutes,t.created_at,s.name AS subject_name,
                  COALESCE(SUM(ws.duration_seconds),0) AS actual_seconds
           FROM tasks t LEFT JOIN subjects s ON s.id=t.subject_id
           LEFT JOIN work_sessions ws ON ws.task_id=t.id AND ws.ended_at IS NOT NULL
           WHERE t.completed=0 GROUP BY t.id,s.name
           ORDER BY CASE WHEN t.due_date IS NULL OR t.due_date='' THEN 1 ELSE 0 END,t.due_date,
                    CASE t.priority WHEN 'Alta' THEN 0 WHEN 'Media' THEN 1 ELSE 2 END,t.created_at,t.id"""
    ).fetchall()
    pending, overdue = [], []
    for row in rows:
        deadline = row["due_date"] or ""
        if deadline and deadline < today.isoformat():
            overdue.append({"task_id":row["id"],"title":row["title"],"due_date":deadline,"reason":"La fecha límite ya pasó."})
            continue
        estimate = max(15, int(row["estimated_minutes"] or 30))
        actual = (max(0,int(row["actual_seconds"] or 0))+59)//60
        remaining = max(0,estimate-actual)
        if remaining:
            pending.append({"task_id":row["id"],"title":row["title"],"priority":row["priority"],
                            "due_date":deadline or None,"subject":row["subject_name"] or "",
                            "remaining_minutes":remaining})
    start_min, end_min = clock_minutes(profile["start_time"]), clock_minutes(profile["end_time"])
    items = []
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        if day.weekday() not in set(profile["available_days"]):
            continue
        cursor, used = start_min, 0
        while cursor < end_min and used < profile["daily_capacity_minutes"]:
            task = next((x for x in pending if x["remaining_minutes"]>0 and (not x["due_date"] or x["due_date"]>=day.isoformat())),None)
            if task is None:
                break
            chunk = min(profile["session_minutes"],task["remaining_minutes"],end_min-cursor,
                        profile["daily_capacity_minutes"]-used)
            if chunk < 1:
                break
            finish = cursor+chunk
            items.append({"task_id":task["task_id"],"task_title":task["title"],"subject":task["subject"],
                          "priority":task["priority"],"due_date":task["due_date"],"planned_date":day.isoformat(),
                          "start_time":f"{cursor//60:02d}:{cursor%60:02d}",
                          "end_time":f"{finish//60:02d}:{finish%60:02d}","duration_minutes":chunk})
            task["remaining_minutes"] -= chunk
            used += chunk
            cursor = finish+profile["break_minutes"]
    unscheduled = overdue + [{"task_id":x["task_id"],"title":x["title"],"remaining_minutes":x["remaining_minutes"],
                              "due_date":x["due_date"],"reason":"No hay capacidad disponible antes de la fecha límite o dentro del horizonte elegido."}
                             for x in pending if x["remaining_minutes"]>0]
    return {"ok":True,"horizon_days":horizon_days,"generated_at":datetime.now().astimezone().isoformat(timespec="seconds"),
            "items":items,"unscheduled":unscheduled,"scheduled_minutes":sum(x["duration_minutes"] for x in items),
            "scheduled_sessions":len(items)}


def build_productivity_insights(db, profile):
    since = (date.today()-timedelta(days=60)).isoformat()
    rows = db.execute("SELECT started_at,duration_seconds FROM work_sessions WHERE ended_at IS NOT NULL AND started_at>=? ORDER BY started_at DESC",(since,)).fetchall()
    periods = {"Mañana":0,"Tarde":0,"Noche":0}
    sessions, total = [], 0
    for row in rows:
        try:
            started = datetime.fromisoformat(row["started_at"])
        except (TypeError,ValueError):
            continue
        sessions.append(started)
        total += max(0,int(row["duration_seconds"] or 0))
        periods["Mañana" if started.hour<12 else "Tarde" if started.hour<18 else "Noche"] += 1
    average = round(total/len(sessions)/60) if sessions else 0
    best = max(periods,key=periods.get) if sessions else None
    estimate_rows = db.execute(
        """SELECT t.estimated_minutes,SUM(ws.duration_seconds) AS actual_seconds FROM tasks t
           JOIN work_sessions ws ON ws.task_id=t.id WHERE ws.ended_at IS NOT NULL AND ws.started_at >= ? GROUP BY t.id"""
    , (since,)).fetchall()
    ratios = [(int(x["actual_seconds"] or 0)/60)/max(1,int(x["estimated_minutes"] or 30))
              for x in estimate_rows if int(x["actual_seconds"] or 0)>0]
    ratio = round(sum(ratios)/len(ratios),2) if ratios else None
    suggestions = []
    if not profile["adaptive_enabled"]:
        suggestions.append("El perfil adaptativo está desactivado. Tus estadísticas siguen disponibles, pero no se generan recomendaciones.")
    elif len(sessions)<3:
        suggestions.append("Registra al menos 3 sesiones para empezar a identificar patrones de actividad.")
    else:
        suggestions.append(f"Tu sesión registrada promedio dura {average} minutos. Úsala como referencia, no como obligación.")
        if best and periods[best]>=3:
            suggestions.append(f"Has registrado más sesiones durante la {best.lower()}. Puedes probar reservar ese horario para tareas importantes.")
        if ratio is not None and len(ratios)>=2:
            if ratio>1.15: suggestions.append("Tus tareas están tomando más tiempo que tus estimaciones. Considera reservar bloques adicionales.")
            elif ratio<0.85: suggestions.append("Sueles terminar antes de tus estimaciones. Puedes ajustar gradualmente los tiempos previstos.")
    return {"ok":True,"enabled":profile["adaptive_enabled"],"sample_size":len(sessions),
            "metrics":{"average_session_minutes":average,"best_period":best,"period_counts":periods,"estimate_ratio":ratio},
            "recommendations":suggestions}


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
        study_day_rows = db.execute(
            "SELECT task_id, study_date FROM task_study_days WHERE study_date >= ? ORDER BY study_date",
            (today_date.isoformat(),),
        ).fetchall()
        study_goal_minutes = get_study_goal_minutes(db)
        productivity_profile = get_productivity_profile(db)

    study_days_by_task = {}
    for study_day in study_day_rows:
        study_days_by_task.setdefault(study_day["task_id"], set()).add(study_day["study_date"])

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
        plan_iso = plan_date.isoformat()
        day_tasks = [
            task for task in tasks
            if not task["completed"] and (
                plan_iso in study_days_by_task.get(task["id"], set())
                if study_days_by_task.get(task["id"])
                else task["planned_date"] == plan_iso
                and (not task["due_date"] or plan_iso <= task["due_date"])
            )
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

    completion_rate = round(completed / total * 100) if total else 0
    average_session_seconds = round(total_work_seconds / len(sessions)) if sessions else 0

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
        completion_rate=completion_rate,
        average_session_seconds=average_session_seconds,
        productivity_profile=productivity_profile,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response



def parse_semantic_version(value):
    """Compare versions while accepting the display-only trailing plus."""
    match = re.fullmatch(r"[vV]?(\d+)\.(\d+)\.(\d+)(?:\+)?", str(value or "").strip())
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
    # Preserve the existing form behavior: invalid optional dates are ignored.
    if due_date is False:
        due_date = None
    if planned_date is False:
        planned_date = None
    if planned_date and not due_date and planned_date > (date.today()+timedelta(days=365)).isoformat():
        abort(400, description="Sin fecha límite, puedes planificar hasta un año por adelantado.")
    subject_name = normalize_subject_name(request.form.get("subject", ""))
    estimated_minutes = parse_estimated_minutes(request.form.get("estimated_minutes", 30))

    if not title:
        return redirect(url_for("index"))
    if priority not in VALID_PRIORITIES:
        priority = "Media"
    if estimated_minutes is None:
        estimated_minutes = 30

    if due_date and planned_date and planned_date > due_date:
        planned_date = None

    with get_db() as db:
        subject_id = get_or_create_subject(db, subject_name)
        cursor = db.execute(
            """INSERT INTO tasks (title, priority, due_date, planned_date, subject_id, estimated_minutes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, priority, due_date, planned_date, subject_id, estimated_minutes),
        )
        task_id = cursor.lastrowid
        if planned_date and planned_date >= date.today().isoformat():
            db.execute(
                "INSERT OR IGNORE INTO task_study_days (task_id, study_date) VALUES (?, ?)",
                (task_id, planned_date),
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
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON válido para editar la tarea."}),400
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
        return jsonify({"ok":False,"message":"La fecha planificada no es válida."}),400
    if planned_date and not due_date and planned_date > (date.today()+timedelta(days=365)).isoformat():
        return jsonify({"ok":False,"message":"Sin fecha límite, puedes planificar hasta un año por adelantado."}),400
    if estimated_minutes is None:
        return jsonify({"ok": False, "message": "Selecciona una estimación válida."}), 400

    with get_db() as db:
        exists = db.execute("SELECT id, planned_date FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not exists:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        if exists["planned_date"] != planned_date:
            db.execute("DELETE FROM planned_sessions WHERE task_id = ?", (task_id,))
        subject_id = get_or_create_subject(db, subject_name)
        db.execute(
            """UPDATE tasks SET title = ?, priority = ?, due_date = ?, planned_date = ?,
               subject_id = ?, estimated_minutes = ? WHERE id = ?""",
            (title, priority, due_date, planned_date, subject_id, estimated_minutes, task_id),
        )
        db.execute(
            "UPDATE canvas_elements SET task_snapshot_title = ? WHERE task_id = ?",
            (title, task_id),
        )

        if exists["planned_date"] != planned_date:
            # A deliberate edit to the single-day field replaces the old calendar plan.
            db.execute("DELETE FROM task_study_days WHERE task_id = ?", (task_id,))
            if planned_date and planned_date >= date.today().isoformat():
                db.execute(
                    "INSERT OR IGNORE INTO task_study_days (task_id, study_date) VALUES (?, ?)",
                    (task_id, planned_date),
                )
        if due_date:
            db.execute(
                "DELETE FROM task_study_days WHERE task_id = ? AND study_date > ?",
                (task_id, due_date),
            )
            db.execute(
                "DELETE FROM planned_sessions WHERE task_id = ? AND planned_date > ?",
                (task_id, due_date),
            )

        remaining_days = db.execute(
            "SELECT study_date FROM task_study_days WHERE task_id = ? ORDER BY study_date",
            (task_id,),
        ).fetchall()
        effective_planned_date = remaining_days[0]["study_date"] if remaining_days else (
            planned_date if not due_date or not planned_date or planned_date <= due_date else None
        )
        db.execute(
            "UPDATE tasks SET planned_date = ? WHERE id = ?",
            (effective_planned_date, task_id),
        )
        planned_date = effective_planned_date
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


@app.route("/api/tasks/<int:task_id>/study-days", methods=["GET"])
def get_task_study_days(task_id):
    """Return the saved calendar dates and deadline for a single task."""
    with get_db() as db:
        task = db.execute(
            "SELECT id, title, due_date, completed, estimated_minutes FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        days = db.execute(
            "SELECT study_date FROM task_study_days WHERE task_id = ? AND study_date >= ? ORDER BY study_date",
            (task_id, date.today().isoformat()),
        ).fetchall()
    return jsonify({
        "ok": True,
        "task_id": task_id,
        "title": task["title"],
        "due_date": task["due_date"],
        "completed": bool(task["completed"]),
        "estimated_minutes": task["estimated_minutes"],
        "days": [row["study_date"] for row in days],
    })


@app.route("/api/tasks/<int:task_id>/study-days", methods=["PUT"])
def update_task_study_days(task_id):
    """Save a flexible set of study dates, never later than the task deadline."""
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON con la lista de días."}),400
    raw_days = payload.get("days")
    if not isinstance(raw_days, list):
        return jsonify({"ok": False, "message": "Envía una lista de días de estudio."}), 400
    if len(raw_days) > 366:
        return jsonify({"ok": False, "message": "Puedes seleccionar hasta 366 días por tarea."}), 400

    normalized_days = set()
    for raw_day in raw_days:
        if not isinstance(raw_day, str):
            return jsonify({"ok": False, "message": "Una de las fechas no es válida."}), 400
        try:
            parsed_day = date.fromisoformat(raw_day)
        except ValueError:
            return jsonify({"ok": False, "message": "Una de las fechas no es válida."}), 400
        if parsed_day.isoformat() != raw_day:
            return jsonify({"ok": False, "message": "Usa fechas con formato AAAA-MM-DD."}), 400
        normalized_days.add(raw_day)

    today_iso = date.today().isoformat()
    if any(day < today_iso for day in normalized_days):
        return jsonify({"ok": False, "message": "No puedes planificar sesiones en días que ya pasaron."}), 400

    with get_db() as db:
        task = db.execute(
            "SELECT id, title, due_date, completed FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
        if task["completed"] and normalized_days:
            return jsonify({
                "ok": False,
                "message": "Esta tarea ya está completada. Reábrela antes de planificar más sesiones.",
            }), 409

        due_date = task["due_date"] or ""
        if due_date and any(day > due_date for day in normalized_days):
            return jsonify({
                "ok": False,
                "message": "Todos los días de estudio deben ser iguales o anteriores a la fecha límite.",
                "due_date": due_date,
            }), 400
        if not due_date and any(day > (date.today() + timedelta(days=365)).isoformat() for day in normalized_days):
            return jsonify({
                "ok": False,
                "message": "Sin fecha límite, puedes planificar hasta un año por adelantado. Define una fecha límite para ampliar el plan.",
            }), 400

        db.execute("DELETE FROM planned_sessions WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM task_study_days WHERE task_id = ?", (task_id,))
        db.executemany(
            "INSERT INTO task_study_days (task_id, study_date) VALUES (?, ?)",
            [(task_id, day) for day in sorted(normalized_days)],
        )
        planned_date = min(normalized_days) if normalized_days else None
        db.execute("UPDATE tasks SET planned_date = ? WHERE id = ?", (planned_date, task_id))

    return jsonify({
        "ok": True,
        "task_id": task_id,
        "due_date": due_date or None,
        "planned_date": planned_date,
        "days": sorted(normalized_days),
        "count": len(normalized_days),
        "message": "Plan de estudio guardado.",
    })


def normalize_workspace_payload(payload, current=None):
    if not isinstance(payload, dict):
        return None
    current = current or {}
    name = payload.get("name", current.get("name", ""))
    description = payload.get("description", current.get("description", ""))
    color = payload.get("color", current.get("color", "violet"))
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
        return None
    if not isinstance(description, str) or len(description) > 500:
        return None
    if not isinstance(color, str) or color not in {"violet", "blue", "green", "rose"}:
        return None
    return {"name": name.strip(), "description": description.strip(), "color": color}


def normalize_canvas_board_payload(payload, current=None):
    if not isinstance(payload, dict):
        return None
    current = current or {}
    title = payload.get("title", current.get("title", ""))
    mode = payload.get("mode", current.get("mode", "free"))
    workspace_id = payload.get("workspace_id", current.get("workspace_id"))
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
        return None
    if not isinstance(mode, str) or mode not in {"free", "structured"}:
        return None
    if workspace_id is not None and (type(workspace_id) is not int or workspace_id < 1):
        return None
    return {"title": title.strip(), "mode": mode, "workspace_id": workspace_id}


def persist_canvas_content(db, board_id, normalized):
    """Persist a validated full snapshot inside the caller transaction."""
    db.execute("DELETE FROM canvas_connections WHERE board_id = ?", (board_id,))
    db.execute("DELETE FROM canvas_elements WHERE board_id = ?", (board_id,))
    db.execute("DELETE FROM canvas_columns WHERE board_id = ?", (board_id,))
    db.executemany(
        "INSERT INTO canvas_columns (board_id, column_key, title, position) VALUES (?, ?, ?, ?)",
        [(board_id, item["key"], item["title"], item["position"]) for item in normalized["columns"]],
    )
    db.executemany(
        """INSERT INTO canvas_elements
           (board_id, element_key, column_key, kind, x, y, width, height, content_json, task_id, task_snapshot_title)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                board_id, item["key"], item["column_key"], item["kind"],
                item["x"], item["y"], item["width"], item["height"],
                json.dumps(item["content"], ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                item["task_id"], item["task_snapshot_title"],
            )
            for item in normalized["elements"]
        ],
    )
    db.executemany(
        """INSERT INTO canvas_connections
           (board_id, connection_key, source_key, target_key, label)
           VALUES (?, ?, ?, ?, ?)""",
        [(board_id, item["key"], item["source"], item["target"], item["label"]) for item in normalized["connections"]],
    )
    db.execute("UPDATE canvas_boards SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (board_id,))


def create_canvas_history_version(db, board_id, normalized, description):
    row = db.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS latest FROM canvas_history WHERE board_id = ?",
        (board_id,),
    ).fetchone()
    version = int(row["latest"]) + 1
    snapshot = {
        "columns": normalized["columns"],
        "elements": normalized["elements"],
        "connections": normalized["connections"],
    }
    db.execute(
        """INSERT INTO canvas_history (board_id, version_number, description, snapshot_json)
           VALUES (?, ?, ?, ?)""",
        (board_id, version, description, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)),
    )
    db.execute(
        """DELETE FROM canvas_history WHERE board_id = ? AND id NOT IN
           (SELECT id FROM canvas_history WHERE board_id = ? ORDER BY version_number DESC LIMIT 50)""",
        (board_id, board_id),
    )
    return version


def normalize_canvas_content(db, board, payload):
    """Validate a complete Canvas snapshot before its transaction replaces saved content."""
    if not isinstance(payload, dict):
        return None, "Envía el contenido del Canvas como un objeto JSON."

    columns = payload.get("columns", [])
    elements = payload.get("elements", [])
    connections = payload.get("connections", [])
    if not isinstance(columns, list) or not isinstance(elements, list) or not isinstance(connections, list):
        return None, "Columnas, elementos y conexiones deben ser listas."
    if len(columns) > 80 or len(elements) > 400 or len(connections) > 600:
        return None, "El tablero supera el límite de elementos permitido."

    mode = board["mode"]
    normalized_columns = []
    column_keys = set()
    for position, column in enumerate(columns):
        if not isinstance(column, dict):
            return None, "Una columna tiene un formato incorrecto."
        key = column.get("key")
        title = column.get("title")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
            return None, "Una columna tiene un identificador no válido."
        if key in column_keys:
            return None, "Hay identificadores de columna repetidos."
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 60:
            return None, "Los nombres de columna deben tener entre 1 y 60 caracteres."
        column_keys.add(key)
        normalized_columns.append({"key": key, "title": title.strip(), "position": position})

    if mode == "free" and normalized_columns:
        return None, "Un Canvas libre no puede contener columnas estructuradas."
    if mode == "structured" and not normalized_columns:
        return None, "Un Canvas estructurado debe tener al menos una columna."

    normalized_elements = []
    element_keys = set()
    for element in elements:
        if not isinstance(element, dict):
            return None, "Un elemento tiene un formato incorrecto."
        key = element.get("key")
        kind = element.get("kind")
        column_key = element.get("column_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
            return None, "Un elemento tiene un identificador no válido."
        if key in element_keys:
            return None, "Hay identificadores de elemento repetidos."
        if not isinstance(kind, str) or ((mode == "free" and kind not in {"note", "text", "group"}) or (
            mode == "structured" and kind != "card"
        )):
            return None, "El tipo de elemento no corresponde al modo de este Canvas."
        if mode == "structured" and (not isinstance(column_key, str) or column_key not in column_keys):
            return None, "Cada tarjeta debe pertenecer a una columna existente."
        if mode == "free" and column_key is not None:
            return None, "Los elementos de un Canvas libre no usan columnas."

        coordinates = {}
        for field, default, minimum, maximum in (
            ("x", 80, -100000, 100000),
            ("y", 80, -100000, 100000),
            ("width", 240, 60, 2400),
            ("height", 150, 60, 2400),
        ):
            value = element.get(field, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, "La posición o tamaño de un elemento no es válido."
            try:
                numeric_value = float(value)
            except (OverflowError, TypeError, ValueError):
                return None, "La posición o tamaño de un elemento no es válido."
            if not math.isfinite(numeric_value) or numeric_value < minimum or numeric_value > maximum:
                return None, "La posición o tamaño de un elemento está fuera del límite."
            coordinates[field] = numeric_value

        content = element.get("content", {})
        if not isinstance(content, dict):
            return None, "El contenido de un elemento debe ser un objeto."
        allowed_content_fields = {"title", "body", "description", "priority", "due_date", "status"}
        if set(content) - allowed_content_fields:
            return None, "Un elemento contiene campos no permitidos."
        clean_content = {}
        for field, maximum in (
            ("title", 160), ("body", 5000), ("description", 2000),
            ("priority", 10), ("due_date", 10), ("status", 30),
        ):
            value = content.get(field, "")
            if not isinstance(value, str) or len(value) > maximum:
                return None, "El contenido de un elemento supera el formato permitido."
            clean_content[field] = value.strip() if field in {"title", "priority", "status"} else value
        if mode == "structured":
            if not clean_content["title"].strip():
                return None, "Cada tarjeta debe tener un título."
            if clean_content["priority"] and clean_content["priority"] not in {"Baja", "Media", "Alta"}:
                return None, "La prioridad de una tarjeta no es válida."
            if clean_content["status"] and clean_content["status"] not in {"Pendiente", "En curso", "En revisión", "Completada"}:
                return None, "El estado de una tarjeta no es válido."
            due_date = clean_content["due_date"]
            if due_date and valid_due_date(due_date) is False:
                return None, "La fecha de una tarjeta no es válida."
        task_id = element.get("task_id")
        task_snapshot_title = element.get("task_snapshot_title", "") if task_id is None else ""
        if not isinstance(task_snapshot_title, str) or len(task_snapshot_title) > 160:
            return None, "El título conservado de una tarea vinculada no es válido."
        if task_id is not None:
            if mode != "structured" or kind != "card" or type(task_id) is not int or task_id < 1:
                return None, "La referencia a tarea global no es válida."
            task = db.execute("SELECT id, title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                return None, "La tarea global vinculada ya no existe."
            task_snapshot_title = task["title"]
        element_keys.add(key)
        normalized_elements.append({
            "key": key, "kind": kind, "column_key": column_key,
            **coordinates, "content": clean_content, "task_id": task_id,
            "task_snapshot_title": task_snapshot_title,
        })

    normalized_connections = []
    connection_keys = set()
    for connection in connections:
        if mode != "free":
            return None, "Las conexiones se habilitan en Canvas libre."
        if not isinstance(connection, dict):
            return None, "Una conexión tiene un formato incorrecto."
        key = connection.get("key")
        source = connection.get("source")
        target = connection.get("target")
        label = connection.get("label", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
            return None, "Una conexión tiene un identificador no válido."
        if key in connection_keys:
            return None, "Hay identificadores de conexión repetidos."
        if not isinstance(source, str) or not isinstance(target, str) or source not in element_keys or target not in element_keys or source == target:
            return None, "Una conexión debe unir dos elementos distintos del mismo tablero."
        if not isinstance(label, str) or len(label) > 100:
            return None, "La etiqueta de una conexión es demasiado larga."
        connection_keys.add(key)
        normalized_connections.append({"key": key, "source": source, "target": target, "label": label})

    return {
        "columns": normalized_columns,
        "elements": normalized_elements,
        "connections": normalized_connections,
    }, None


@app.route("/api/canvas/<int:board_id>/history", methods=["GET"])
def canvas_history_api(board_id):
    with get_db() as db:
        exists = db.execute("SELECT id FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
        if not exists:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
        rows = db.execute(
            """SELECT id, version_number, description, created_at
               FROM canvas_history WHERE board_id = ? ORDER BY version_number DESC""",
            (board_id,),
        ).fetchall()
    return jsonify({"ok": True, "items": [dict(row) for row in rows]})


@app.route("/api/canvas/<int:board_id>/history/<int:version_id>/restore", methods=["POST"])
def restore_canvas_history_api(board_id, version_id):
    with get_db() as db:
        board = db.execute("SELECT id, mode FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
        if not board:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
        version = db.execute(
            "SELECT version_number, snapshot_json FROM canvas_history WHERE id = ? AND board_id = ?",
            (version_id, board_id),
        ).fetchone()
        if not version:
            return jsonify({"ok": False, "message": "No encontramos esa versión del historial."}), 404
        try:
            snapshot = json.loads(version["snapshot_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return jsonify({"ok": False, "message": "La versión guardada no se puede leer."}), 409
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("elements"), list):
            return jsonify({"ok": False, "message": "La estructura de esa versión no es válida."}), 409
        # A deleted global task is restored as an independent card with its last saved content.
        for element in snapshot["elements"]:
            if isinstance(element, dict) and type(element.get("task_id")) is int:
                task = db.execute("SELECT id FROM tasks WHERE id = ?", (element["task_id"],)).fetchone()
                if not task:
                    element["task_snapshot_title"] = element.get("task_snapshot_title") or (element.get("content") or {}).get("title", "")
                    element["task_id"] = None
        normalized, error = normalize_canvas_content(db, board, snapshot)
        if error:
            return jsonify({"ok": False, "message": "No se pudo restaurar esa versión: " + error}), 409
        persist_canvas_content(db, board_id, normalized)
        new_version = create_canvas_history_version(
            db, board_id, normalized, "Restauración de versión " + str(version["version_number"])
        )
    return jsonify({
        "ok": True,
        "message": "Versión restaurada como una nueva versión.",
        "version_number": new_version,
    })


@app.route("/api/tasks/<int:task_id>/completion", methods=["PUT"])
def update_task_completion_api(task_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or type(payload.get("completed")) is not bool:
        return jsonify({"ok": False, "message": "Indica si la tarea está completada."}), 400
    with get_db() as db:
        cursor = db.execute("UPDATE tasks SET completed = ? WHERE id = ?", (int(payload["completed"]), task_id))
        if cursor.rowcount == 0:
            return jsonify({"ok": False, "message": "No se encontró esa tarea."}), 404
    return jsonify({"ok": True, "task_id": task_id, "completed": payload["completed"]})


CANVAS_ATTACHMENT_MAX_BYTES = 7 * 1024 * 1024
CANVAS_ATTACHMENT_EXTENSIONS = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".pdf": "application/pdf",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def canvas_attachment_root():
    return (DATABASE.parent / "canvas_attachments").resolve()


def canvas_attachment_path(relative_path):
    if not isinstance(relative_path, str) or not relative_path:
        return None
    root = canvas_attachment_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def validate_canvas_file(filename, content):
    safe_name = secure_filename(filename or "")
    extension = Path(safe_name).suffix.lower()
    if not safe_name or extension not in CANVAS_ATTACHMENT_EXTENSIONS:
        return None, "Tipo de archivo no permitido. Usa imágenes, PDF, TXT, MD, CSV, DOCX, XLSX o PPTX."
    if not content or len(content) > CANVAS_ATTACHMENT_MAX_BYTES:
        return None, "El archivo está vacío o supera el límite de 7 MB."

    valid = False
    mime_type = CANVAS_ATTACHMENT_EXTENSIONS[extension]
    if extension == ".png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension in {".jpg", ".jpeg"}:
        valid = content.startswith(b"\xff\xd8\xff")
    elif extension == ".webp":
        valid = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    elif extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension in {".txt", ".md", ".csv"}:
        try:
            decoded = content.decode("utf-8-sig")
            valid = "\x00" not in decoded
        except UnicodeDecodeError:
            valid = False
    elif extension in {".docx", ".xlsx", ".pptx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
            required = {
                ".docx": "word/document.xml",
                ".xlsx": "xl/workbook.xml",
                ".pptx": "ppt/presentation.xml",
            }[extension]
            valid = "[Content_Types].xml" in names and required in names
        except (zipfile.BadZipFile, OSError):
            valid = False
    if not valid:
        return None, "El contenido del archivo no coincide con su extensión."
    return {"name": safe_name[:180], "mime_type": mime_type, "extension": extension}, None


@app.route("/api/canvas/<int:board_id>/attachments", methods=["GET", "POST"])
def canvas_attachments_api(board_id):
    if request.method == "GET":
        with get_db() as db:
            board = db.execute("SELECT id FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
            if not board:
                return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
            rows = db.execute(
                """SELECT id, element_key, attachment_key, kind, original_name, mime_type,
                          size_bytes, url, created_at
                   FROM canvas_attachments WHERE board_id = ? ORDER BY created_at DESC, id DESC""",
                (board_id,),
            ).fetchall()
            element_rows = db.execute(
                "SELECT element_key, content_json FROM canvas_elements WHERE board_id = ?",
                (board_id,),
            ).fetchall()
        element_titles = {}
        for element in element_rows:
            try:
                data = json.loads(element["content_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            element_titles[element["element_key"]] = data.get("title", "") if isinstance(data, dict) else ""
        items = []
        for row in rows:
            item = dict(row)
            item["element_title"] = element_titles.get(item["element_key"], "Elemento eliminado")
            item["download_url"] = (
                url_for("canvas_attachment_download_api", board_id=board_id, attachment_id=item["id"])
                if item["kind"] == "file" else None
            )
            items.append(item)
        return jsonify({"ok": True, "items": items})

    board_id_exists = None
    with get_db() as db:
        board_id_exists = db.execute("SELECT id FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
        if not board_id_exists:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404

    if request.is_json:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "message": "Envía un enlace y un elemento válidos."}), 400
        element_key = payload.get("element_key")
        url = payload.get("url")
        if not isinstance(element_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", element_key):
            return jsonify({"ok": False, "message": "Selecciona un elemento válido."}), 400
        if not isinstance(url, str) or len(url) > 2048:
            return jsonify({"ok": False, "message": "El enlace no es válido."}), 400
        try:
            parsed = urlsplit(url.strip())
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password
        except ValueError:
            valid_url = False
        if not valid_url:
            return jsonify({"ok": False, "message": "Solo se permiten enlaces HTTP o HTTPS válidos."}), 400
        clean_url = url.strip()
        with get_db() as db:
            element = db.execute(
                "SELECT element_key FROM canvas_elements WHERE board_id = ? AND element_key = ?",
                (board_id, element_key),
            ).fetchone()
            if not element:
                return jsonify({"ok": False, "message": "El elemento seleccionado ya no existe."}), 404
            cursor = db.execute(
                """INSERT INTO canvas_attachments
                   (board_id, element_key, attachment_key, kind, original_name, mime_type, size_bytes, url)
                   VALUES (?, ?, ?, 'link', ?, 'text/uri-list', 0, ?)""",
                (board_id, element_key, secrets.token_hex(16), clean_url[:180], clean_url),
            )
            attachment_id = cursor.lastrowid
        return jsonify({
            "ok": True, "item": {
                "id": attachment_id, "element_key": element_key, "kind": "link",
                "original_name": clean_url[:180], "url": clean_url,
            },
        }), 201

    element_key = request.form.get("element_key", "")
    uploaded = request.files.get("file")
    if not isinstance(element_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", element_key):
        return jsonify({"ok": False, "message": "Selecciona un elemento válido."}), 400
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "message": "Selecciona un archivo para adjuntar."}), 400
    content = uploaded.read(CANVAS_ATTACHMENT_MAX_BYTES + 1)
    normalized, error = validate_canvas_file(uploaded.filename, content)
    if error:
        return jsonify({"ok": False, "message": error}), 400

    with get_db() as db:
        element = db.execute(
            "SELECT element_key FROM canvas_elements WHERE board_id = ? AND element_key = ?",
            (board_id, element_key),
        ).fetchone()
        if not element:
            return jsonify({"ok": False, "message": "El elemento seleccionado ya no existe."}), 404

    attachment_key = secrets.token_hex(16)
    relative_path = "board-" + str(board_id) + "/" + attachment_key + normalized["extension"]
    destination = canvas_attachment_path(relative_path)
    if destination is None:
        return jsonify({"ok": False, "message": "No se pudo preparar el almacenamiento local."}), 500
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.write_bytes(content)
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO canvas_attachments
                   (board_id, element_key, attachment_key, kind, original_name, mime_type, size_bytes, relative_path)
                   VALUES (?, ?, ?, 'file', ?, ?, ?, ?)""",
                (board_id, element_key, attachment_key, normalized["name"],
                 normalized["mime_type"], len(content), relative_path),
            )
            attachment_id = cursor.lastrowid
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return jsonify({
        "ok": True, "item": {
            "id": attachment_id, "element_key": element_key, "kind": "file",
            "original_name": normalized["name"], "mime_type": normalized["mime_type"],
            "size_bytes": len(content),
        },
    }), 201


@app.route("/api/canvas/<int:board_id>/attachments/<int:attachment_id>/download", methods=["GET"])
def canvas_attachment_download_api(board_id, attachment_id):
    with get_db() as db:
        row = db.execute(
            """SELECT original_name, mime_type, relative_path, kind
               FROM canvas_attachments WHERE id = ? AND board_id = ?""",
            (attachment_id, board_id),
        ).fetchone()
    if not row or row["kind"] != "file":
        return jsonify({"ok": False, "message": "No encontramos ese archivo."}), 404
    path = canvas_attachment_path(row["relative_path"])
    if path is None or not path.is_file():
        return jsonify({"ok": False, "message": "El archivo ya no está disponible en este equipo."}), 404
    inline = row["mime_type"].startswith("image/")
    response = send_file(
        path, mimetype=row["mime_type"], as_attachment=not inline,
        download_name=row["original_name"], conditional=False,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.route("/api/canvas/<int:board_id>/attachments/<int:attachment_id>", methods=["DELETE"])
def delete_canvas_attachment_api(board_id, attachment_id):
    with get_db() as db:
        row = db.execute(
            "SELECT relative_path FROM canvas_attachments WHERE id = ? AND board_id = ?",
            (attachment_id, board_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "No encontramos ese adjunto."}), 404
        relative_path = row["relative_path"]
        db.execute("DELETE FROM canvas_attachments WHERE id = ?", (attachment_id,))
        still_referenced = False
        if relative_path:
            still_referenced = db.execute(
                "SELECT 1 FROM canvas_attachments WHERE relative_path = ? LIMIT 1",
                (relative_path,),
            ).fetchone() is not None
    if relative_path and not still_referenced:
        path = canvas_attachment_path(relative_path)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return jsonify({"ok": True, "message": "Adjunto eliminado."})


@app.route("/api/canvas/<int:board_id>/elements/<element_key>/convert-task", methods=["POST"])
def convert_canvas_element_to_task_api(board_id, element_key):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", element_key):
        return jsonify({"ok": False, "message": "El identificador del elemento no es válido."}), 400
    with get_db() as db:
        board = db.execute("SELECT id, mode FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
        if not board:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
        if board["mode"] != "structured":
            return jsonify({"ok": False, "message": "Solo las tarjetas de Canvas estructurado pueden convertirse en tareas globales."}), 400
        element = db.execute(
            """SELECT element_key, kind, task_id, task_snapshot_title, content_json
               FROM canvas_elements WHERE board_id = ? AND element_key = ?""",
            (board_id, element_key),
        ).fetchone()
        if not element or element["kind"] != "card":
            return jsonify({"ok": False, "message": "No encontramos esa tarjeta."}), 404
        if element["task_id"] is not None:
            task = db.execute(
                "SELECT id, title, priority, due_date, planned_date, completed, estimated_minutes FROM tasks WHERE id = ?",
                (element["task_id"],),
            ).fetchone()
            if task:
                return jsonify({"ok": True, "already_linked": True, "task": dict(task)})
        try:
            data = json.loads(element["content_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        title = str(data.get("title", "")).strip()[:160] if isinstance(data, dict) else ""
        if not title:
            return jsonify({"ok": False, "message": "Agrega un título antes de convertir esta tarjeta."}), 400
        priority = data.get("priority", "Media")
        if priority not in VALID_PRIORITIES:
            priority = "Media"
        due_date = data.get("due_date", "")
        if due_date and valid_due_date(due_date) is False:
            return jsonify({"ok": False, "message": "La fecha de la tarjeta no es válida."}), 400
        subject_id = None
        cursor = db.execute(
            """INSERT INTO tasks (title, priority, due_date, planned_date, subject_id, estimated_minutes)
               VALUES (?, ?, ?, NULL, ?, 30)""",
            (title, priority, due_date or None, subject_id),
        )
        task_id = cursor.lastrowid
        db.execute(
            "UPDATE canvas_elements SET task_id = ?, task_snapshot_title = ?, updated_at = CURRENT_TIMESTAMP WHERE board_id = ? AND element_key = ?",
            (task_id, title, board_id, element_key),
        )
    return jsonify({
        "ok": True, "already_linked": False,
        "task": {
            "id": task_id, "title": title, "priority": priority, "due_date": due_date or None,
            "planned_date": None, "completed": 0, "estimated_minutes": 30,
        },
    }), 201


@app.route("/api/canvas/task-options", methods=["GET"])
def canvas_task_options_api():
    with get_db() as db:
        rows = db.execute(
            """SELECT t.id, t.title, t.priority, t.due_date, t.planned_date, t.completed,
                      t.estimated_minutes, COALESCE(s.name, '') AS subject
               FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id
               ORDER BY t.completed ASC, t.title COLLATE NOCASE"""
        ).fetchall()
    return jsonify({"ok": True, "items": [dict(row) for row in rows]})


@app.route("/api/canvas/<int:board_id>/viewport", methods=["PUT"])
def canvas_board_viewport_api(board_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "message": "Envía la posición y el zoom del lienzo."}), 400
    values = {}
    for field in ("x", "y"):
        value = payload.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1000000:
            return jsonify({"ok": False, "message": "La posición del lienzo no es válida."}), 400
        values[field] = int(value)
    zoom = payload.get("zoom", 1)
    if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not math.isfinite(zoom) or zoom < 0.25 or zoom > 2:
        return jsonify({"ok": False, "message": "El nivel de zoom debe estar entre 25% y 200%."}), 400
    values["zoom"] = round(float(zoom), 2)
    with get_db() as db:
        cursor = db.execute(
            "UPDATE canvas_boards SET viewport_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(values, separators=(",", ":"), allow_nan=False), board_id),
        )
        if cursor.rowcount == 0:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
    return jsonify({"ok": True, "viewport": values})


@app.route("/api/canvas/<int:board_id>/content", methods=["GET", "PUT"])
def canvas_board_content_api(board_id):
    with get_db() as db:
        board = db.execute(
            "SELECT id, mode FROM canvas_boards WHERE id = ?", (board_id,)
        ).fetchone()
        if not board:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404

        if request.method == "GET":
            columns = db.execute(
                "SELECT column_key AS key, title, position FROM canvas_columns WHERE board_id = ? ORDER BY position, id",
                (board_id,),
            ).fetchall()
            element_rows = db.execute(
                """SELECT e.element_key AS key, e.kind, e.column_key, e.x, e.y, e.width, e.height,
                          e.content_json, e.task_id, e.task_snapshot_title,
                          COALESCE(t.title, e.task_snapshot_title) AS linked_task_title,
                          t.priority AS linked_task_priority, t.due_date AS linked_task_due_date,
                          t.planned_date AS linked_task_planned_date, t.estimated_minutes AS linked_task_estimated_minutes,
                          COALESCE(s.name, '') AS linked_task_subject, t.completed AS linked_task_completed
                   FROM canvas_elements e LEFT JOIN tasks t ON t.id = e.task_id
                   LEFT JOIN subjects s ON s.id = t.subject_id
                   WHERE e.board_id = ? ORDER BY e.id""",
                (board_id,),
            ).fetchall()
            elements = []
            for row in element_rows:
                item = dict(row)
                try:
                    item["content"] = json.loads(item.pop("content_json"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["content"] = {}
                item["linked_task_completed"] = (
                    bool(item["linked_task_completed"]) if item["linked_task_completed"] is not None else None
                )
                elements.append(item)
            connection_rows = db.execute(
                """SELECT connection_key AS key, source_key AS source, target_key AS target, label
                   FROM canvas_connections WHERE board_id = ? ORDER BY id""",
                (board_id,),
            ).fetchall()
            return jsonify({
                "ok": True,
                "mode": board["mode"],
                "columns": [dict(row) for row in columns],
                "elements": elements,
                "connections": [dict(row) for row in connection_rows],
            })

        payload = request.get_json(silent=True)
        normalized, error = normalize_canvas_content(db, board, payload)
        if error:
            return jsonify({"ok": False, "message": error}), 400

        # Replace the full snapshot in one transaction.
        persist_canvas_content(db, board_id, normalized)
        latest = db.execute(
            "SELECT created_at FROM canvas_history WHERE board_id = ? ORDER BY version_number DESC LIMIT 1",
            (board_id,),
        ).fetchone()
        manual_version = payload.get("create_version") is True
        first_version = latest is None
        interval_elapsed = False
        if latest:
            interval_elapsed = db.execute(
                "SELECT datetime(?) <= datetime('now', '-30 minutes')", (latest["created_at"],)
            ).fetchone()[0] == 1
        version_number = None
        if manual_version or first_version or interval_elapsed:
            description = "Guardado manual" if manual_version else ("Primera versión" if first_version else "Versión automática")
            version_number = create_canvas_history_version(db, board_id, normalized, description)

    return jsonify({
        "ok": True,
        "message": "Canvas guardado.",
        "version_number": version_number,
        "counts": {
            "columns": len(normalized["columns"]),
            "elements": len(normalized["elements"]),
            "connections": len(normalized["connections"]),
        },
    })


@app.route("/api/workspaces", methods=["GET", "POST"])
def workspaces_api():
    if request.method == "GET":
        with get_db() as db:
            rows = db.execute(
                """SELECT w.id, w.name, w.description, w.color, w.created_at, w.updated_at,
                          COUNT(cb.id) AS board_count
                   FROM workspaces w LEFT JOIN canvas_boards cb ON cb.workspace_id = w.id
                   GROUP BY w.id ORDER BY w.name COLLATE NOCASE"""
            ).fetchall()
        return jsonify({"ok": True, "items": [dict(row) for row in rows]})

    normalized = normalize_workspace_payload(request.get_json(silent=True))
    if normalized is None:
        return jsonify({"ok": False, "message": "Revisa el nombre, la descripción y el color del espacio."}), 400
    try:
        with get_db() as db:
            cursor = db.execute(
                "INSERT INTO workspaces (name, description, color) VALUES (?, ?, ?)",
                (normalized["name"], normalized["description"], normalized["color"]),
            )
            workspace_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "message": "Ya existe un espacio de trabajo con ese nombre."}), 409
    return jsonify({"ok": True, "item": {"id": workspace_id, **normalized, "board_count": 0}}), 201


@app.route("/api/workspaces/<int:workspace_id>", methods=["PATCH", "DELETE"])
def workspace_detail_api(workspace_id):
    if request.method == "PATCH":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "message": "Envía los cambios como un objeto JSON."}), 400
        with get_db() as db:
            row = db.execute(
                "SELECT id, name, description, color FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "message": "No encontramos ese espacio de trabajo."}), 404
            normalized = normalize_workspace_payload(payload, dict(row))
            if normalized is None:
                return jsonify({"ok": False, "message": "Revisa el nombre, la descripción y el color del espacio."}), 400
            try:
                db.execute(
                    """UPDATE workspaces SET name = ?, description = ?, color = ?,
                       updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                    (normalized["name"], normalized["description"], normalized["color"], workspace_id),
                )
            except sqlite3.IntegrityError:
                return jsonify({"ok": False, "message": "Ya existe otro espacio con ese nombre."}), 409
        return jsonify({"ok": True, "item": {"id": workspace_id, **normalized}})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("preserve_boards") is not True:
        return jsonify({"ok": False, "message": "Confirma preserve_boards=true para conservar los tableros como independientes."}), 400
    with get_db() as db:
        row = db.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "No encontramos ese espacio de trabajo."}), 404
        db.execute(
            "UPDATE canvas_boards SET workspace_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE workspace_id = ?",
            (workspace_id,),
        )
        db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    return jsonify({"ok": True, "message": "Espacio eliminado; sus tableros se conservaron como independientes."})


@app.route("/api/canvas", methods=["GET", "POST"])
def canvas_boards_api():
    if request.method == "GET":
        workspace_filter = request.args.get("workspace_id")
        query = """SELECT cb.id, cb.workspace_id, cb.title, cb.mode, cb.created_at, cb.updated_at,
                          w.name AS workspace_name
                   FROM canvas_boards cb LEFT JOIN workspaces w ON w.id = cb.workspace_id"""
        params = ()
        if workspace_filter is not None:
            try:
                workspace_id = int(workspace_filter)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "message": "El identificador del espacio no es válido."}), 400
            query += " WHERE cb.workspace_id = ?"
            params = (workspace_id,)
        query += " ORDER BY cb.updated_at DESC, cb.id DESC"
        with get_db() as db:
            rows = db.execute(query, params).fetchall()
        return jsonify({"ok": True, "items": [dict(row) for row in rows]})

    normalized = normalize_canvas_board_payload(request.get_json(silent=True))
    if normalized is None:
        return jsonify({"ok": False, "message": "Revisa el título, tipo y espacio asociado del Canvas."}), 400
    with get_db() as db:
        workspace_id = normalized["workspace_id"]
        if workspace_id is not None:
            workspace = db.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if not workspace:
                return jsonify({"ok": False, "message": "El espacio seleccionado no existe."}), 404
        cursor = db.execute(
            "INSERT INTO canvas_boards (workspace_id, title, mode) VALUES (?, ?, ?)",
            (workspace_id, normalized["title"], normalized["mode"]),
        )
        if normalized["mode"] == "structured":
            db.executemany(
                "INSERT INTO canvas_columns (board_id, column_key, title, position) VALUES (?, ?, ?, ?)",
                [
                    (cursor.lastrowid, "todo", "Por hacer", 0),
                    (cursor.lastrowid, "doing", "En curso", 1),
                    (cursor.lastrowid, "done", "Hecho", 2),
                ],
            )
        row = db.execute(
            """SELECT cb.id, cb.workspace_id, cb.title, cb.mode, cb.created_at, cb.updated_at,
                      w.name AS workspace_name
               FROM canvas_boards cb LEFT JOIN workspaces w ON w.id = cb.workspace_id
               WHERE cb.id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
    return jsonify({"ok": True, "item": dict(row)}), 201


@app.route("/api/canvas/<int:board_id>", methods=["GET", "PATCH", "DELETE"])
def canvas_board_detail_api(board_id):
    if request.method == "GET":
        with get_db() as db:
            row = db.execute(
                """SELECT cb.id, cb.workspace_id, cb.title, cb.mode, cb.viewport_json,
                          cb.preferences_json, cb.created_at, cb.updated_at,
                          w.name AS workspace_name
                   FROM canvas_boards cb LEFT JOIN workspaces w ON w.id = cb.workspace_id
                   WHERE cb.id = ?""",
                (board_id,),
            ).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
        return jsonify({"ok": True, "item": dict(row), "stage": "catalog"})

    if request.method == "PATCH":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "message": "Envía los cambios como un objeto JSON."}), 400
        with get_db() as db:
            row = db.execute(
                "SELECT id, workspace_id, title, mode FROM canvas_boards WHERE id = ?",
                (board_id,),
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
            normalized = normalize_canvas_board_payload(payload, dict(row))
            if normalized is None:
                return jsonify({"ok": False, "message": "Revisa el título, tipo y espacio asociado del Canvas."}), 400
            workspace_id = normalized["workspace_id"]
            if workspace_id is not None:
                workspace = db.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
                if not workspace:
                    return jsonify({"ok": False, "message": "El espacio seleccionado no existe."}), 404
            db.execute(
                """UPDATE canvas_boards SET workspace_id = ?, title = ?, mode = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (workspace_id, normalized["title"], normalized["mode"], board_id),
            )
            updated = db.execute(
                """SELECT cb.id, cb.workspace_id, cb.title, cb.mode, cb.created_at, cb.updated_at,
                          w.name AS workspace_name
                   FROM canvas_boards cb LEFT JOIN workspaces w ON w.id = cb.workspace_id
                   WHERE cb.id = ?""",
                (board_id,),
            ).fetchone()
        return jsonify({"ok": True, "item": dict(updated)})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        return jsonify({"ok": False, "message": "Confirma la eliminación con confirm=true."}), 400
    with get_db() as db:
        row = db.execute("SELECT id FROM canvas_boards WHERE id = ?", (board_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "message": "No encontramos ese tablero."}), 404
        attachment_paths = [
            item["relative_path"] for item in db.execute(
                "SELECT relative_path FROM canvas_attachments WHERE board_id = ? AND relative_path IS NOT NULL",
                (board_id,),
            ).fetchall()
        ]
        db.execute("DELETE FROM canvas_boards WHERE id = ?", (board_id,))
    for relative_path in attachment_paths:
        path = canvas_attachment_path(relative_path)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return jsonify({"ok": True, "message": "Canvas eliminado."})


@app.route("/api/settings/theme", methods=["PUT"])
def update_theme():
    """Persist the selected appearance in the local settings database."""
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON con el tema."}),400
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
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON con la meta diaria."}),400
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


@app.route("/api/productivity/profile", methods=["GET","PUT"])
def productivity_profile_api():
    with get_db() as db:
        current=get_productivity_profile(db)
        if request.method=="GET":
            return jsonify({"ok":True,"profile":current})
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):
            return jsonify({"ok":False,"message":"Envía un objeto JSON con tus preferencias."}),400
        profile=normalize_productivity_profile(payload,current)
        if profile is None:
            return jsonify({"ok":False,"message":"Revisa días, horarios, sesiones, descansos y opciones."}),400
        save_productivity_profile(db,profile)
    return jsonify({"ok":True,"profile":profile,"message":"Preferencias guardadas en este equipo."})


@app.route("/api/productivity/insights")
def productivity_insights_api():
    with get_db() as db:
        data=build_productivity_insights(db,get_productivity_profile(db))
    return jsonify(data)


@app.route("/api/productivity/plan", methods=["GET","POST"])
def productivity_plan_api():
    with get_db() as db:
        if request.method=="GET":
            rows=db.execute(
                """SELECT ps.id,ps.task_id,t.title AS task_title,s.name AS subject,t.priority,t.due_date,
                          ps.planned_date,ps.start_time,
                          substr(time(ps.start_time,'+'||ps.duration_minutes||' minutes'),1,5) AS end_time,
                          ps.duration_minutes
                   FROM planned_sessions ps JOIN tasks t ON t.id=ps.task_id
                   LEFT JOIN subjects s ON s.id=t.subject_id
                   WHERE ps.planned_date>=? AND t.completed=0
                   ORDER BY ps.planned_date,ps.start_time,ps.id""",(date.today().isoformat(),)).fetchall()
            return jsonify({"ok":True,"items":[dict(x) for x in rows],"count":len(rows)})
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):
            return jsonify({"ok":False,"message":"Envía un objeto JSON para generar la planificación."}),400
        profile=get_productivity_profile(db)
        horizon=payload.get("horizon_days",profile["planning_horizon_days"])
        if type(horizon) is not int or horizon not in {7,14,21,30}:
            return jsonify({"ok":False,"message":"Selecciona un horizonte de 7, 14, 21 o 30 días."}),400
        plan=build_productivity_plan(db,profile,horizon)
    return jsonify(plan)


@app.route("/api/productivity/plan/apply",methods=["POST"])
def apply_productivity_plan_api():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON para guardar la propuesta."}),400
    horizon=payload.get("horizon_days")
    if type(horizon) is not int or horizon not in {7,14,21,30}:
        return jsonify({"ok":False,"message":"Selecciona un horizonte válido."}),400
    with get_db() as db:
        plan=build_productivity_plan(db,get_productivity_profile(db),horizon)
        if not plan["items"]:
            return jsonify({"ok":False,"message":"No hay sesiones que se puedan programar con la disponibilidad actual.",
                            "unscheduled":plan["unscheduled"]}),409
        today_iso=date.today().isoformat()
        db.execute("DELETE FROM planned_sessions WHERE planned_date>=?",(today_iso,))
        touched=set()
        for item in plan["items"]:
            db.execute(
                """INSERT OR REPLACE INTO planned_sessions(task_id,planned_date,start_time,duration_minutes)
                   VALUES(?,?,?,?)""",
                (item["task_id"],item["planned_date"],item["start_time"],item["duration_minutes"]))
            db.execute("INSERT OR IGNORE INTO task_study_days(task_id,study_date) VALUES(?,?)",
                       (item["task_id"],item["planned_date"]))
            touched.add(item["task_id"])
        for task_id in touched:
            first=db.execute("SELECT MIN(study_date) AS first_day FROM task_study_days WHERE task_id=? AND study_date>=?",
                             (task_id,today_iso)).fetchone()["first_day"]
            db.execute("UPDATE tasks SET planned_date=? WHERE id=?",(first,task_id))
    return jsonify({"ok":True,"message":"La propuesta se guardó y se integró con tu calendario.",
                    "items":plan["items"],"count":len(plan["items"]),
                    "scheduled_minutes":plan["scheduled_minutes"],"unscheduled":plan["unscheduled"]})


@app.route("/api/work/start", methods=["POST"])
def start_work():
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON con la tarea que quieres iniciar."}),400
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
    payload = request.get_json(silent=True)
    if not isinstance(payload,dict):
        return jsonify({"ok":False,"message":"Envía un objeto JSON con el resumen de la sesión."}),400
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
