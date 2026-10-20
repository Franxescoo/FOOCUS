"""Windows desktop launcher for FocusFlow.

The Flask server only listens on loopback. User data lives outside the install
folder so updates and uninstalling the application do not remove the database.
"""
from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import secrets
import sys
from threading import Thread
from typing import Mapping

APP_NAME = "FocusFlow"
WINDOW_TITLE = "FocusFlow"
DEFAULT_WINDOW_SIZE = (1280, 860)
MIN_WINDOW_SIZE = (900, 620)


def get_user_data_dir(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the per-user writable data directory."""
    env = os.environ if environ is None else environ
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    else:
        root = (home or Path.home()) / "AppData" / "Local"

    data_dir = root / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_or_create_secret_key(data_dir: Path) -> str:
    """Keep Flask's session/CSRF signing key stable between app launches."""
    key_file = data_dir / "secret.key"
    try:
        existing = key_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 64:
            return existing
    except OSError:
        pass

    secret_key = secrets.token_hex(32)
    key_file.write_text(secret_key, encoding="utf-8")
    return secret_key


def load_saved_port(data_dir: Path) -> int:
    """Reuse a loopback port so browser storage keeps the same origin."""
    port_file = data_dir / "server.port"
    try:
        port = int(port_file.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0
    return port if 1024 <= port <= 65535 else 0


def save_server_port(data_dir: Path, port: int) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("The local server port is outside the valid range.")
    (data_dir / "server.port").write_text(str(port), encoding="ascii")


def show_error(message: str) -> None:
    """Show startup failures even when the executable has no console."""
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(f"{APP_NAME}: {message}", file=sys.stderr)


def main() -> int:
    data_dir = get_user_data_dir()
    log_file = data_dir / "desktop.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )

    server = None
    server_thread: Thread | None = None
    try:
        # Set paths before importing app.py, because it reads these values
        # while initializing the Flask application and SQLite database.
        os.environ.setdefault("FOCUSFLOW_DATABASE", str(data_dir / "focusflow.db"))
        os.environ.setdefault("FOCUSFLOW_SECRET_KEY", load_or_create_secret_key(data_dir))
        os.environ["FLASK_DEBUG"] = "0"

        from werkzeug.serving import make_server
        import webview
        from app import app as flask_app

        port = load_saved_port(data_dir)
        server = make_server("127.0.0.1", port, flask_app, threaded=True)
        actual_port = int(server.server_port)
        if port != actual_port:
            save_server_port(data_dir, actual_port)

        server_thread = Thread(
            target=server.serve_forever,
            name="FocusFlow-local-server",
            daemon=True,
        )
        server_thread.start()

        logging.info("Starting desktop window on loopback port %s", actual_port)
        webview.create_window(
            WINDOW_TITLE,
            f"http://127.0.0.1:{actual_port}/",
            width=DEFAULT_WINDOW_SIZE[0],
            height=DEFAULT_WINDOW_SIZE[1],
            min_size=MIN_WINDOW_SIZE,
            background_color="#f7f7fc",
            text_select=True,
            zoomable=True,
        )
        webview.start(debug=False)
        return 0
    except Exception as error:
        logging.exception("FocusFlow could not start")
        show_error(
            "No se pudo iniciar FocusFlow.\n\n"
            f"Detalle: {error}\n\n"
            "Comprueba que Microsoft Edge WebView2 esté instalado y que otra "
            "aplicación no esté usando el puerto local de FocusFlow. "
            "El registro técnico está en:\n"
            f"{log_file}"
        )
        return 1
    finally:
        if server is not None:
            try:
                if server_thread is not None and server_thread.is_alive():
                    server.shutdown()
                    server_thread.join(timeout=3)
                server.server_close()
            except Exception:
                logging.exception("Error while stopping FocusFlow's local server")


if __name__ == "__main__":
    raise SystemExit(main())
