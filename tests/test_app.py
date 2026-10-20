import tempfile
import unittest
from pathlib import Path

import app as focusflow


class FocusFlowTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        focusflow.DATABASE = Path(self.temp_dir.name) / "test-focusflow.db"
        focusflow.init_db()
        self.client = focusflow.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_task(self, title="Repasar Python", priority="Alta", due_date="2026-10-22"):
        return self.client.post(
            "/tasks",
            data={"title": title, "priority": priority, "due_date": due_date},
            follow_redirects=True,
        )

    def test_home_loads_when_empty(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mis tareas", response.data)
        self.assertIn(b"theme-toggle", response.data)
        self.assertIn(b"SISTEMA ANTI-PROCRASTINACI", response.data)
        self.assertIn(b"starter-task", response.data)
        self.assertIn(b'id="work-dashboard"', response.data)
        self.assertIn(b"Actividad de trabajo", response.data)
        self.assertNotIn(b'id="utility-activity-card"', response.data)

    def test_work_dashboard_is_visible_on_main_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.data
        stats_position = page.index(b'class="stats"')
        dashboard_position = page.index(b'id="work-dashboard"')
        add_task_position = page.index(b'Agregar una tarea')
        self.assertLess(stats_position, dashboard_position)
        self.assertLess(dashboard_position, add_task_position)
        self.assertNotIn(b'id="utility-activity-card"', page)

    def test_create_task(self):
        response = self.create_task()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Repasar Python".encode(), response.data)
        self.assertIn(b"Alta", response.data)

    def test_invalid_priority_defaults_to_medium(self):
        self.create_task(priority="Urgente")
        with focusflow.get_db() as db:
            task = db.execute("SELECT priority FROM tasks").fetchone()
        self.assertEqual(task["priority"], "Media")

    def test_toggle_task(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        response = self.client.post(f"/tasks/{task_id}/toggle")
        self.assertEqual(response.status_code, 302)
        with focusflow.get_db() as db:
            completed = db.execute("SELECT completed FROM tasks WHERE id = ?", (task_id,)).fetchone()["completed"]
        self.assertEqual(completed, 1)

    def test_edit_task(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        response = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "Proyecto terminado", "priority": "Media", "due_date": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        with focusflow.get_db() as db:
            task = db.execute("SELECT title, priority, due_date FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(task["title"], "Proyecto terminado")
        self.assertEqual(task["priority"], "Media")
        self.assertIsNone(task["due_date"])

    def test_edit_rejects_empty_title(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        response = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "   ", "priority": "Media", "due_date": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["ok"])


    def test_start_and_stop_work_session_with_comment(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        started = self.client.post("/api/work/start", json={"task_id": task_id})
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json["ok"])
        stopped = self.client.post("/api/work/stop", json={"comment": "Terminé una parte del proyecto"})
        self.assertEqual(stopped.status_code, 200)
        self.assertTrue(stopped.json["ok"])
        self.assertEqual(stopped.json["comment"], "Terminé una parte del proyecto")
        with focusflow.get_db() as db:
            row = db.execute("SELECT ended_at, duration_seconds, comment FROM work_sessions WHERE task_id = ?", (task_id,)).fetchone()
        self.assertIsNotNone(row["ended_at"])
        self.assertGreaterEqual(row["duration_seconds"], 0)
        self.assertEqual(row["comment"], "Terminé una parte del proyecto")

    def test_only_one_work_session_can_be_active(self):
        self.create_task("Tarea A")
        self.create_task("Tarea B")
        with focusflow.get_db() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM tasks ORDER BY id").fetchall()]
        first = self.client.post("/api/work/start", json={"task_id": ids[0]})
        second = self.client.post("/api/work/start", json={"task_id": ids[1]})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_task_work_log_returns_saved_comment(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        self.client.post("/api/work/start", json={"task_id": task_id})
        self.client.post("/api/work/stop", json={"comment": "Prueba del historial"})
        response = self.client.get(f"/api/tasks/{task_id}/work-log")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["sessions"][0]["comment"], "Prueba del historial")


    def test_export_csv_includes_task_and_work_comment(self):
        self.create_task("Exportar mi progreso", priority="Alta")
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        self.client.post("/api/work/start", json={"task_id": task_id})
        self.client.post("/api/work/stop", json={"comment": "Avancé el diseño"})
        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["Content-Type"])
        self.assertIn("Exportar mi progreso".encode(), response.data)
        self.assertIn("Avancé el diseño".encode(), response.data)

    def test_delete_task(self):
        self.create_task()
        with focusflow.get_db() as db:
            task_id = db.execute("SELECT id FROM tasks").fetchone()["id"]
        response = self.client.post(f"/tasks/{task_id}/delete")
        self.assertEqual(response.status_code, 302)
        with focusflow.get_db() as db:
            count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
