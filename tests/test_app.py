import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import app as focusflow
import desktop_launcher as focusflow_desktop


class FocusFlowTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        focusflow.DATABASE = Path(self.temp_dir.name) / "test-focusflow.db"
        focusflow.init_db()
        self.client = focusflow.app.test_client()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as cookie_session:
            self.csrf_token = cookie_session["_csrf_token"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_headers(self):
        return {"X-CSRF-Token": self.csrf_token}

    def create_task(
        self, title="Repasar Python", priority="Alta", due_date="2026-10-22",
        subject="", estimated_minutes="30", planned_date="",
    ):
        return self.client.post(
            "/tasks",
            data={
                "title": title,
                "priority": priority,
                "due_date": due_date,
                "subject": subject,
                "estimated_minutes": estimated_minutes,
                "planned_date": planned_date,
                "csrf_token": self.csrf_token,
            },
            follow_redirects=True,
        )

    def task_id(self):
        with focusflow.get_db() as db:
            row = db.execute("SELECT id FROM tasks ORDER BY id LIMIT 1").fetchone()
        return row["id"]

    def test_desktop_data_directory_uses_local_appdata(self):
        with tempfile.TemporaryDirectory() as local_app_data:
            data_dir = focusflow_desktop.get_user_data_dir({"LOCALAPPDATA": local_app_data})
            self.assertEqual(data_dir, Path(local_app_data) / "FocusFlow")
            self.assertTrue(data_dir.is_dir())

    def test_desktop_secret_and_port_are_stable_between_launches(self):
        with tempfile.TemporaryDirectory() as local_app_data:
            data_dir = Path(local_app_data) / "FocusFlow"
            data_dir.mkdir()

            first_key = focusflow_desktop.load_or_create_secret_key(data_dir)
            second_key = focusflow_desktop.load_or_create_secret_key(data_dir)
            self.assertEqual(first_key, second_key)
            self.assertGreaterEqual(len(first_key), 64)

            focusflow_desktop.save_server_port(data_dir, 53184)
            self.assertEqual(focusflow_desktop.load_saved_port(data_dir), 53184)

    def test_desktop_port_loader_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as local_app_data:
            data_dir = Path(local_app_data)
            (data_dir / "server.port").write_text("not-a-port", encoding="ascii")
            self.assertEqual(focusflow_desktop.load_saved_port(data_dir), 0)
            with self.assertRaises(ValueError):
                focusflow_desktop.save_server_port(data_dir, 80)

    def test_home_loads_when_empty(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mis tareas", response.data)
        self.assertIn(b"theme-toggle", response.data)
        self.assertIn(b"starter-task", response.data)
        self.assertIn(b'id="work-dashboard"', response.data)
        self.assertIn(b"Actividad de trabajo", response.data)
        self.assertIn(b'id="study-goal-select"', response.data)
        self.assertNotIn(b'id="subject-filter"', response.data)
        self.assertIn("Tu espacio está listo".encode(), response.data)
        self.assertIn(b'id="active-work-dialog"', response.data)
        self.assertIn(b'id="active-work-dock"', response.data)
        self.assertIn(b'id="work-minimize-button"', response.data)
        self.assertIn(b'id="download-focusflow"', response.data)
        self.assertIn(b'id="download-status"', response.data)
        self.assertIn(b'https://github.com/Franxescoo/FocusFlow/releases/latest/download/FocusFlow-Setup.exe', response.data)
        self.assertNotIn(b'id="utility-session-card"', response.data)
        self.assertNotIn(b'id="utility-activity-card"', response.data)

    def test_task_filters_include_live_count_and_empty_results(self):
        self.create_task(title="Estudiar Django", subject="Programación")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.data
        self.assertIn(b'id="subject-filter"', page)
        self.assertIn(b'id="task-visible-count"', page)
        self.assertIn(b'id="task-filter-clear"', page)
        self.assertIn(b'id="task-no-results" hidden', page)
        self.assertIn(b'aria-pressed="true">Todas</button>', page)
        self.assertIn(b'aria-pressed="false">Pendientes</button>', page)
        self.assertIn(b'function clearTaskFilters()', page)
        self.assertIn(b'button.setAttribute("aria-pressed", String(active))', page)

    def test_cursor_aura_is_decorative_and_respects_accessibility(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.data
        self.assertIn(b'id="cursor-aura"', page)
        self.assertIn(b'aria-hidden="true"', page)
        self.assertIn(b'window.matchMedia("(prefers-reduced-motion: reduce)")', page)
        self.assertIn(b'window.matchMedia("(hover: hover) and (pointer: fine)")', page)
        self.assertIn(b'event.pointerType !== "mouse"', page)
        self.assertIn(b'window.requestAnimationFrame(animateAura)', page)

    def test_active_work_session_uses_modal_after_reload(self):
        self.create_task(title="Repasar cálculo")
        task_id = self.task_id()
        started = self.client.post(
            "/api/work/start",
            json={"task_id": task_id},
            headers=self.csrf_headers(),
        )
        self.assertEqual(started.status_code, 200)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="active-work-dialog"', response.data)
        self.assertIn(b'id="active-work-dock-reopen"', response.data)
        self.assertIn("Repasar cálculo".encode(), response.data)
        self.assertIn(b'workDialog.showModal()', response.data)
        self.assertIn(b'workDialog.close("minimize")', response.data)
        self.assertNotIn(b'id="utility-session-card"', response.data)

    def test_modal_keeps_session_ui_hidden_before_work_starts(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.data
        self.assertIn(b'<dialog class="active-work-dialog"', page)
        self.assertIn(b'id="active-work-panel" hidden', page)
        self.assertIn(b'id="active-work-dock" hidden', page)

    def test_work_dashboard_is_visible_on_main_page(self):
        page = self.client.get("/").data
        stats_position = page.index(b'class="stats"')
        dashboard_position = page.index(b'id="work-dashboard"')
        add_task_position = page.index(b"Agregar una tarea")
        self.assertLess(stats_position, dashboard_position)
        self.assertLess(dashboard_position, add_task_position)

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_create_task(self):
        response = self.create_task()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Repasar Python", response.data)
        self.assertIn(b"Alta", response.data)

    def test_invalid_priority_defaults_to_medium(self):
        self.create_task(priority="Urgente")
        with focusflow.get_db() as db:
            task = db.execute("SELECT priority FROM tasks").fetchone()
        self.assertEqual(task["priority"], "Media")

    def test_toggle_task(self):
        self.create_task()
        task_id = self.task_id()
        response = self.client.post(
            f"/tasks/{task_id}/toggle",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(response.status_code, 302)
        with focusflow.get_db() as db:
            completed = db.execute(
                "SELECT completed FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()["completed"]
        self.assertEqual(completed, 1)

    def test_edit_task(self):
        self.create_task()
        task_id = self.task_id()
        response = self.client.patch(
            f"/api/tasks/{task_id}",
            json={
                "title": "Proyecto terminado", "priority": "Media", "due_date": "",
                "planned_date": "2026-11-03",
                "subject": "Matemáticas", "estimated_minutes": 90,
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        with focusflow.get_db() as db:
            task = db.execute(
                """SELECT t.title, t.priority, t.due_date, t.planned_date, t.estimated_minutes,
                          s.name AS subject_name
                   FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
        self.assertEqual(task["title"], "Proyecto terminado")
        self.assertEqual(task["priority"], "Media")
        self.assertEqual(task["subject_name"], "Matemáticas")
        self.assertEqual(task["estimated_minutes"], 90)
        self.assertEqual(task["planned_date"], "2026-11-03")
        self.assertIsNone(task["due_date"])

    def test_edit_rejects_empty_title(self):
        self.create_task()
        response = self.client.patch(
            f"/api/tasks/{self.task_id()}",
            json={"title": "   ", "priority": "Media", "due_date": ""},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])

    def test_csrf_protection_rejects_missing_token(self):
        response = self.client.post("/api/work/start", json={"task_id": 1})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])
        self.assertIn("seguridad", response.json["message"].lower())

    def test_study_goal_defaults_and_persists(self):
        with focusflow.get_db() as db:
            initial = db.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = 'study_goal_minutes'"
            ).fetchone()
        self.assertEqual(initial["setting_value"], "120")

        response = self.client.put(
            "/api/settings/study-goal",
            json={"minutes": 180},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        self.assertEqual(response.json["minutes"], 180)
        with focusflow.get_db() as db:
            updated = db.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = 'study_goal_minutes'"
            ).fetchone()
        self.assertEqual(updated["setting_value"], "180")

    def test_study_goal_rejects_out_of_range_values(self):
        response = self.client.put(
            "/api/settings/study-goal",
            json={"minutes": 20},
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])

    def test_create_task_saves_subject_and_estimate(self):
        self.create_task(title="Funciones", subject="  Matemáticas   discretas ", estimated_minutes="90")
        task_id = self.task_id()
        with focusflow.get_db() as db:
            task = db.execute(
                """SELECT t.subject_id, t.estimated_minutes, s.name AS subject_name
                   FROM tasks t LEFT JOIN subjects s ON s.id = t.subject_id WHERE t.id = ?""",
                (task_id,),
            ).fetchone()
        self.assertEqual(task["subject_name"], "Matemáticas discretas")
        self.assertEqual(task["estimated_minutes"], 90)
        self.assertIsNotNone(task["subject_id"])
        home = self.client.get("/").data
        self.assertIn(b'id="subject-summary"', home)
        self.assertIn("Matemáticas discretas".encode(), home)

    def test_subject_names_are_reused_case_insensitively(self):
        self.create_task(title="Tarea uno", subject="Programación")
        self.create_task(title="Tarea dos", subject=" programación ")
        with focusflow.get_db() as db:
            subjects = db.execute("SELECT id, name FROM subjects").fetchall()
            tasks = db.execute("SELECT subject_id FROM tasks ORDER BY id").fetchall()
        self.assertEqual(len(subjects), 1)
        self.assertEqual(tasks[0]["subject_id"], tasks[1]["subject_id"])

    def test_invalid_task_estimate_defaults_to_30_minutes(self):
        self.create_task(title="Tarea estimada", subject="Bases de datos", estimated_minutes="17")
        with focusflow.get_db() as db:
            task = db.execute("SELECT estimated_minutes FROM tasks").fetchone()
        self.assertEqual(task["estimated_minutes"], 30)

    def test_edit_rejects_invalid_estimate(self):
        self.create_task()
        response = self.client.patch(
            f"/api/tasks/{self.task_id()}",
            json={
                "title": "Repasar Python", "priority": "Media", "due_date": "",
                "subject": "Python", "estimated_minutes": 17,
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("estimación", response.json["message"].lower())

    def test_weekly_plan_shows_pending_tasks_for_the_next_seven_days(self):
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.create_task(title="Estudiar hoy", subject="Álgebra", planned_date=today)
        today_task_id = self.task_id()
        self.create_task(title="Repasar mañana", subject="Álgebra", planned_date=tomorrow)

        page = self.client.get("/").data
        self.assertIn(b'id="weekly-planner"', page)
        self.assertIn(b"Estudiar hoy", page)
        self.assertIn(b"Repasar ma", page)
        self.assertIn(b"planificada", page)

        self.client.post(
            f"/tasks/{today_task_id}/toggle",
            data={"csrf_token": self.csrf_token},
        )
        page_after_completion = self.client.get("/").data
        self.assertNotIn(b'data-planned-task="' + str(today_task_id).encode() + b'"', page_after_completion)
        self.assertIn(b"Repasar ma", page_after_completion)

    def test_task_without_planned_date_is_not_added_to_week_plan(self):
        self.create_task(title="Sin día asignado")
        page = self.client.get("/").data
        self.assertIn("Sin día asignado".encode(), page)
        self.assertNotIn(b"data-planned-task=", page)

    def test_invalid_planned_date_is_ignored_on_task_creation(self):
        self.create_task(title="Plan por corregir", planned_date="no-es-fecha")
        with focusflow.get_db() as db:
            task = db.execute("SELECT planned_date FROM tasks").fetchone()
        self.assertIsNone(task["planned_date"])

    def test_init_db_migrates_legacy_tasks_without_losing_rows(self):
        current_database = focusflow.DATABASE
        legacy_database = Path(self.temp_dir.name) / "legacy-focusflow.db"
        try:
            focusflow.DATABASE = legacy_database
            with sqlite3.connect(legacy_database) as db:
                db.execute(
                    """CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        priority TEXT NOT NULL DEFAULT 'Media',
                        due_date TEXT,
                        completed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                db.execute(
                    """CREATE TABLE work_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER NOT NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        duration_seconds INTEGER NOT NULL DEFAULT 0,
                        comment TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                    )"""
                )
                db.execute(
                    "INSERT INTO tasks (title, priority) VALUES (?, ?)",
                    ("Tarea antigua", "Alta"),
                )
                db.execute(
                    "INSERT INTO work_sessions (task_id, started_at, comment) VALUES (?, ?, ?)",
                    (1, "2026-10-19T08:00:00+00:00", "Avance anterior"),
                )
            # sqlite3.Connection's context manager commits but does not close.
            # Explicitly close it so Windows can remove the temporary database.
            db.close()
            focusflow.init_db()
            with focusflow.get_db() as db:
                columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
                session_columns = {row["name"] for row in db.execute("PRAGMA table_info(work_sessions)")}
                task = db.execute("SELECT title, priority, estimated_minutes, subject_id FROM tasks").fetchone()
                old_session = db.execute("SELECT comment, next_step FROM work_sessions").fetchone()
            self.assertIn("next_step", session_columns)
            self.assertEqual(old_session["comment"], "Avance anterior")
            self.assertEqual(old_session["next_step"], "")
            self.assertIn("subject_id", columns)
            self.assertIn("estimated_minutes", columns)
            self.assertIn("planned_date", columns)
            self.assertEqual(task["title"], "Tarea antigua")
            self.assertEqual(task["priority"], "Alta")
            self.assertEqual(task["estimated_minutes"], 30)
            self.assertIsNone(task["subject_id"])
        finally:
            focusflow.DATABASE = current_database

    def test_start_and_stop_work_session_with_comment(self):
        self.create_task()
        task_id = self.task_id()
        started = self.client.post(
            "/api/work/start",
            json={"task_id": task_id},
            headers=self.csrf_headers(),
        )
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json["ok"])
        stopped = self.client.post(
            "/api/work/stop",
            json={
                "comment": "Terminé una parte del proyecto",
                "next_step": "Probar el flujo con un título vacío",
            },
            headers=self.csrf_headers(),
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertTrue(stopped.json["ok"])
        self.assertEqual(stopped.json["comment"], "Terminé una parte del proyecto")
        self.assertEqual(stopped.json["next_step"], "Probar el flujo con un título vacío")
        with focusflow.get_db() as db:
            row = db.execute(
                "SELECT ended_at, duration_seconds, comment, next_step FROM work_sessions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        self.assertIsNotNone(row["ended_at"])
        self.assertGreaterEqual(row["duration_seconds"], 0)
        self.assertEqual(row["comment"], "Terminé una parte del proyecto")
        self.assertEqual(row["next_step"], "Probar el flujo con un título vacío")

    def test_only_one_work_session_can_be_active(self):
        self.create_task("Tarea A")
        self.create_task("Tarea B")
        with focusflow.get_db() as db:
            ids = [
                row["id"]
                for row in db.execute("SELECT id FROM tasks ORDER BY id").fetchall()
            ]
        first = self.client.post(
            "/api/work/start", json={"task_id": ids[0]}, headers=self.csrf_headers()
        )
        second = self.client.post(
            "/api/work/start", json={"task_id": ids[1]}, headers=self.csrf_headers()
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_completed_task_cannot_start_work(self):
        self.create_task()
        task_id = self.task_id()
        self.client.post(
            f"/tasks/{task_id}/toggle", data={"csrf_token": self.csrf_token}
        )
        response = self.client.post(
            "/api/work/start", json={"task_id": task_id}, headers=self.csrf_headers()
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("completada", response.json["message"])

    def test_task_with_active_work_cannot_be_deleted(self):
        self.create_task()
        task_id = self.task_id()
        self.client.post(
            "/api/work/start", json={"task_id": task_id}, headers=self.csrf_headers()
        )
        response = self.client.post(
            f"/tasks/{task_id}/delete", data={"csrf_token": self.csrf_token}
        )
        self.assertEqual(response.status_code, 400)
        with focusflow.get_db() as db:
            count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, 1)

    def test_task_work_log_returns_saved_comment(self):
        self.create_task()
        task_id = self.task_id()
        self.client.post(
            "/api/work/start", json={"task_id": task_id}, headers=self.csrf_headers()
        )
        self.client.post(
            "/api/work/stop",
            json={"comment": "Prueba del historial", "next_step": "Repasar el ejercicio 3"},
            headers=self.csrf_headers(),
        )
        response = self.client.get(f"/api/tasks/{task_id}/work-log")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["sessions"][0]["comment"], "Prueba del historial")
        self.assertEqual(response.json["sessions"][0]["next_step"], "Repasar el ejercicio 3")

    def test_next_step_is_visible_on_task_card(self):
        self.create_task(title="Retomar cálculo")
        task_id = self.task_id()
        self.client.post(
            "/api/work/start", json={"task_id": task_id}, headers=self.csrf_headers()
        )
        self.client.post(
            "/api/work/stop",
            json={"comment": "Resolví dos ejercicios", "next_step": "Revisar los límites laterales"},
            headers=self.csrf_headers(),
        )
        page = self.client.get("/").data
        self.assertIn("Retomar con".encode(), page)
        self.assertIn("Revisar los límites laterales".encode(), page)

    def test_export_csv_includes_task_and_work_comment(self):
        self.create_task("Exportar mi progreso", priority="Alta", subject="Programación",
                         estimated_minutes="60", planned_date="2026-10-24")
        task_id = self.task_id()
        self.client.post(
            "/api/work/start", json={"task_id": task_id}, headers=self.csrf_headers()
        )
        self.client.post(
            "/api/work/stop",
            json={"comment": "Avancé el diseño", "next_step": "Conectar el formulario con la base de datos"},
            headers=self.csrf_headers(),
        )
        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["Content-Type"])
        self.assertIn("Exportar mi progreso".encode(), response.data)
        self.assertIn("Avancé el diseño".encode(), response.data)
        self.assertIn("Estimación (minutos)".encode(), response.data)
        self.assertIn("Asignatura".encode(), response.data)
        self.assertIn("Fecha planificada".encode(), response.data)
        self.assertIn("2026-10-24".encode(), response.data)
        self.assertIn("Siguiente paso".encode(), response.data)
        self.assertIn("Conectar el formulario con la base de datos".encode(), response.data)

    def test_export_csv_escapes_spreadsheet_formulas(self):
        self.create_task("=1+1")
        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"'=1+1", response.data)

    def test_delete_task(self):
        self.create_task()
        response = self.client.post(
            f"/tasks/{self.task_id()}/delete",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(response.status_code, 302)
        with focusflow.get_db() as db:
            count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
