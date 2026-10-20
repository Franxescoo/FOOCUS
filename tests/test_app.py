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
