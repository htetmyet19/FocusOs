"""FocusOs's own PostgreSQL server: no installation, no admin rights, no service.

The server programs live in FocusOs\\pgsql (made by scripts\\get_portable_postgres.ps1).
The data lives in %LOCALAPPDATA%\\FocusOs\\pgdata, so every Windows user gets
their own private database. The server listens only on 127.0.0.1, on port
5544 (not 5432, so it never clashes with an installed PostgreSQL).

First run: initdb creates the cluster with a random password for focus_user
(saved in %APPDATA%\\postgresql\\pgpass.conf, which libpq and psycopg read),
then the study_tracker database is created and schema.sql + logic.sql loaded.

    python portable_db.py start | stop | status
"""
import os
import secrets
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# FOCUSOS_ROOT: set by desktop.py when packaged as an .exe (the folder holding it).
ROOT = Path(os.environ.get("FOCUSOS_ROOT") or Path(__file__).resolve().parents[2])
PG_BIN = ROOT / "pgsql" / "bin"
DB_SQL = ROOT / "db"

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusOs"
DATA_DIR = APP_DIR / "pgdata"
LOG_FILE = APP_DIR / "postgres.log"
RUNTIME_INI = APP_DIR / "runtime.ini"      # connection settings handed to the C++ tracker

HOST = "127.0.0.1"
PORT = 5544
USER = "focus_user"
DATABASE = "study_tracker"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PortableDbError(Exception):
    """Something the user has to fix; the message says what."""


def available() -> bool:
    return (PG_BIN / "postgres.exe").exists() and (PG_BIN / "pg_ctl.exe").exists()


def connection_params() -> dict:
    return {"host": HOST, "port": PORT, "user": USER, "dbname": DATABASE}


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW, **kw)


def _pgpass_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "postgresql" / "pgpass.conf"


def _save_password(password: str) -> None:
    """Store the password where libpq looks for it, replacing old entries for our port."""
    path = _pgpass_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if path.exists():
        lines = [l for l in path.read_text(encoding="ascii", errors="ignore").splitlines()
                 if l.strip() and not l.startswith((f"{HOST}:{PORT}:", f"localhost:{PORT}:"))]
    lines += [f"{HOST}:{PORT}:*:{USER}:{password}", f"localhost:{PORT}:*:{USER}:{password}"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    if sys.platform == "win32":   # readable by this Windows user only
        _run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:(R,W)"])


def _write_runtime_ini() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_INI.write_text(
        "; Written by FocusOs for the tracker. Password is in pgpass.conf.\n"
        f"[database]\nhost = {HOST}\nport = {PORT}\nuser = {USER}\ndatabase = {DATABASE}\n",
        encoding="utf-8",
    )


def is_initialised() -> bool:
    return (DATA_DIR / "PG_VERSION").exists()


def is_running() -> bool:
    if not is_initialised():
        return False
    return _run([str(PG_BIN / "pg_ctl.exe"), "status", "-D", str(DATA_DIR)]).returncode == 0


def _initdb() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(28))
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw", encoding="ascii") as f:
        f.write(password)
        pwfile = f.name
    try:
        r = _run([str(PG_BIN / "initdb.exe"), "-D", str(DATA_DIR), "-U", USER, f"--pwfile={pwfile}",
                  "-A", "scram-sha-256", "-E", "UTF8", "--locale=C", "--no-instructions"])
    finally:
        os.remove(pwfile)
    if r.returncode != 0:
        raise PortableDbError(f"Could not create the database files: {r.stderr.strip() or r.stdout.strip()}")
    # Only this computer may connect, on our own port.
    with open(DATA_DIR / "postgresql.conf", "a", encoding="utf-8") as conf:
        conf.write(f"\n# FocusOs\nlisten_addresses = '{HOST}'\nport = {PORT}\n")
    _save_password(password)


def _create_database() -> None:
    import psycopg
    with psycopg.connect(host=HOST, port=PORT, user=USER, dbname="postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE {DATABASE} ENCODING \'UTF8\' TEMPLATE template0')
    load_schema()


def load_schema() -> None:
    """(Re)load schema.sql and logic.sql. Both files are safe to run more than once."""
    import psycopg
    with psycopg.connect(**connection_params(), autocommit=True) as conn:
        for name in ("schema.sql", "logic.sql"):
            conn.execute((DB_SQL / name).read_text(encoding="utf-8"))


def start() -> str:
    """Make sure the database exists and is running. Returns a short status line."""
    if sys.platform != "win32":
        raise PortableDbError("The portable database is for Windows. Use mode = server elsewhere.")
    if not available():
        raise PortableDbError("Portable PostgreSQL not found in pgsql\\. "
                              "Run scripts\\get_portable_postgres.ps1 first.")
    first_run = not is_initialised()
    if first_run:
        _initdb()
    if not is_running():
        # Don't capture output here: pg_ctl starts the long-running postgres
        # process, which would inherit our pipes and keep them open forever,
        # so we'd wait for ever. The server writes to its own log file instead.
        r = subprocess.run([str(PG_BIN / "pg_ctl.exe"), "start", "-D", str(DATA_DIR), "-l", str(LOG_FILE),
                            "-w", "-t", "30"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
        if r.returncode != 0:
            tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:] \
                if LOG_FILE.exists() else []
            hint = " Is another program using port 5544?" if any("5544" in l for l in tail) else ""
            raise PortableDbError("The database server did not start." + hint +
                                  (" Log: " + " | ".join(tail) if tail else ""))
    _write_runtime_ini()
    # Always make sure the database exists (also repairs an interrupted first
    # run), then (re)load the schema so updates add new tables and views.
    _create_database()
    if first_run:
        return f"Created your FocusOs database in {DATA_DIR}"
    return f"FocusOs database running on {HOST}:{PORT}"


def stop() -> str:
    if not is_running():
        return "FocusOs database is not running."
    r = _run([str(PG_BIN / "pg_ctl.exe"), "stop", "-D", str(DATA_DIR), "-m", "fast", "-w"])
    if r.returncode != 0:
        raise PortableDbError(r.stderr.strip() or "Could not stop the database.")
    return "FocusOs database stopped."


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if cmd == "start":
            print(start())
        elif cmd == "stop":
            print(stop())
        else:
            print("running" if is_running() else ("stopped" if is_initialised() else "not created yet"),
                  f"(data: {DATA_DIR}, port {PORT})")
    except PortableDbError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
