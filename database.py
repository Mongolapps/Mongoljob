import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_PATH = Path(__file__).with_name("servigo.db")
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH)))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seekers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT NOT NULL,
                profession TEXT NOT NULL,
                location TEXT NOT NULL,
                desired_salary TEXT NOT NULL,
                phone TEXT NOT NULL,
                experience TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                plan TEXT NOT NULL DEFAULT 'free',
                premium_expires_at TEXT,
                notifications_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL UNIQUE,
                owner_username TEXT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                location TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employer_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                salary TEXT NOT NULL,
                location TEXT NOT NULL,
                schedule TEXT NOT NULL,
                job_type TEXT NOT NULL,
                requirements TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                plan TEXT NOT NULL DEFAULT 'free',
                premium_expires_at TEXT,
                channel_message_id INTEGER,
                views INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                applicant_id INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                score_reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'waiting_employer',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, applicant_id),
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(applicant_id) REFERENCES seekers(telegram_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS favorites (
                applicant_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(applicant_id, job_id),
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(applicant_id) REFERENCES seekers(telegram_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                approved_at TEXT
            );

            """
        )
        _migrate_schema(conn)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_browse
                ON jobs(status, job_type, category, plan, created_at);
            CREATE INDEX IF NOT EXISTS idx_jobs_employer
                ON jobs(employer_id, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_matches_employer
                ON matches(status, job_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_matches_applicant
                ON matches(applicant_id, status, created_at);
            """
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, definitions: dict[str, str]
) -> None:
    existing = _table_columns(conn, table)
    for column, definition in definitions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Keep Railway's persistent SQLite volume compatible with this release."""
    _add_missing_columns(
        conn,
        "seekers",
        {
            "username": "TEXT",
            "experience": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'pending'",
            "plan": "TEXT NOT NULL DEFAULT 'free'",
            "premium_expires_at": "TEXT",
            "notifications_enabled": "INTEGER NOT NULL DEFAULT 1",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _add_missing_columns(
        conn,
        "businesses",
        {
            "owner_username": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'pending'",
            "verified": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _add_missing_columns(
        conn,
        "jobs",
        {
            "job_type": "TEXT NOT NULL DEFAULT 'full_time'",
            "status": "TEXT NOT NULL DEFAULT 'pending'",
            "plan": "TEXT NOT NULL DEFAULT 'free'",
            "premium_expires_at": "TEXT",
            "channel_message_id": "INTEGER",
            "views": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    _add_missing_columns(
        conn,
        "matches",
        {
            "score": "INTEGER NOT NULL DEFAULT 0",
            "score_reason": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'waiting_employer'",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    )


def _one(query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(query, tuple(params)).fetchone()


def _all(query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(query, tuple(params)).fetchall()


def expire_promotions() -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            UPDATE seekers SET plan='free', premium_expires_at=NULL, updated_at=?
            WHERE plan!='free' AND premium_expires_at IS NOT NULL
              AND premium_expires_at<=?
            """,
            (now, now),
        )
        conn.execute(
            """
            UPDATE jobs SET plan='free', premium_expires_at=NULL, updated_at=?
            WHERE plan!='free' AND premium_expires_at IS NOT NULL
              AND premium_expires_at<=?
            """,
            (now, now),
        )


def save_seeker(data: dict[str, Any]) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO seekers (
                telegram_id, username, full_name, profession, location,
                desired_salary, phone, experience, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                profession=excluded.profession,
                location=excluded.location,
                desired_salary=excluded.desired_salary,
                phone=excluded.phone,
                experience=excluded.experience,
                status='pending',
                updated_at=excluded.updated_at
            """,
            (
                data["telegram_id"], data.get("username"), data["full_name"],
                data["profession"], data["location"], data["desired_salary"],
                data["phone"], data.get("experience", ""), now, now,
            ),
        )


def get_seeker(telegram_id: int) -> sqlite3.Row | None:
    expire_promotions()
    return _one("SELECT * FROM seekers WHERE telegram_id=?", (telegram_id,))


def set_seeker_status(telegram_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE seekers SET status=?, updated_at=? WHERE telegram_id=?",
            (status, utc_now(), telegram_id),
        )


def set_seeker_plan(telegram_id: int, plan: str, expires_at: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE seekers SET plan=?, premium_expires_at=?, updated_at=? WHERE telegram_id=?",
            (plan, expires_at, utc_now(), telegram_id),
        )


def toggle_notifications(telegram_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT notifications_enabled FROM seekers WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        if not row:
            return False
        enabled = 0 if row["notifications_enabled"] else 1
        conn.execute(
            "UPDATE seekers SET notifications_enabled=?, updated_at=? WHERE telegram_id=?",
            (enabled, utc_now(), telegram_id),
        )
        return bool(enabled)


def save_business(data: dict[str, Any]) -> int:
    now = utc_now()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM businesses WHERE owner_id=?", (data["owner_id"],)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE businesses SET owner_username=?, name=?, phone=?, location=?,
                    status='pending', updated_at=? WHERE owner_id=?
                """,
                (
                    data.get("owner_username"), data["name"], data["phone"],
                    data["location"], now, data["owner_id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO businesses (
                owner_id, owner_username, name, phone, location, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["owner_id"], data.get("owner_username"), data["name"],
                data["phone"], data["location"], now, now,
            ),
        )
        return int(cur.lastrowid)


def get_business_by_owner(owner_id: int) -> sqlite3.Row | None:
    return _one("SELECT * FROM businesses WHERE owner_id=?", (owner_id,))


def get_business(business_id: int) -> sqlite3.Row | None:
    return _one("SELECT * FROM businesses WHERE id=?", (business_id,))


def set_business_status(business_id: int, status: str, verified: bool = False) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE businesses SET status=?, verified=?, updated_at=? WHERE id=?",
            (status, int(verified), utc_now(), business_id),
        )


def add_job(data: dict[str, Any]) -> int:
    now = utc_now()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs (
                employer_id, business_id, title, category, salary, location,
                schedule, job_type, requirements, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["employer_id"], data["business_id"], data["title"],
                data["category"], data["salary"], data["location"],
                data["schedule"], data["job_type"], data["requirements"], now, now,
            ),
        )
        return int(cur.lastrowid)


def get_job(job_id: int, increment_view: bool = False) -> sqlite3.Row | None:
    expire_promotions()
    if increment_view:
        with connect() as conn:
            conn.execute("UPDATE jobs SET views=views+1 WHERE id=?", (job_id,))
    return _one(
        """
        SELECT j.*, b.name AS company, b.phone AS business_phone,
               b.verified AS business_verified
        FROM jobs j JOIN businesses b ON b.id=j.business_id
        WHERE j.id=?
        """,
        (job_id,),
    )


def list_jobs(job_type: str | None = None, category: str | None = None, limit: int = 20) -> list[sqlite3.Row]:
    expire_promotions()
    clauses = ["j.status='approved'"]
    params: list[Any] = []
    if job_type:
        clauses.append("j.job_type=?")
        params.append(job_type)
    if category:
        clauses.append("j.category=?")
        params.append(category)
    params.append(limit)
    return _all(
        f"""
        SELECT j.*, b.name AS company, b.verified AS business_verified
        FROM jobs j JOIN businesses b ON b.id=j.business_id
        WHERE {' AND '.join(clauses)}
        ORDER BY CASE j.plan WHEN 'vip' THEN 0 WHEN 'premium' THEN 1 ELSE 2 END,
                 j.created_at DESC LIMIT ?
        """,
        params,
    )


def list_employer_jobs(employer_id: int) -> list[sqlite3.Row]:
    return _all(
        """
        SELECT j.*, b.name AS company,
            (SELECT COUNT(*) FROM matches m WHERE m.job_id=j.id) AS application_count
        FROM jobs j JOIN businesses b ON b.id=j.business_id
        WHERE j.employer_id=? ORDER BY j.created_at DESC
        """,
        (employer_id,),
    )


def set_job_status(job_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
            (status, utc_now(), job_id),
        )


def set_job_plan(job_id: int, plan: str, expires_at: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET plan=?, premium_expires_at=?, updated_at=? WHERE id=?",
            (plan, expires_at, utc_now(), job_id),
        )


def set_job_channel_message(job_id: int, message_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET channel_message_id=?, updated_at=? WHERE id=?",
            (message_id, utc_now(), job_id),
        )


def close_job(job_id: int, employer_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='closed', updated_at=? WHERE id=? AND employer_id=?",
            (utc_now(), job_id, employer_id),
        )
        return cur.rowcount > 0


def create_match(
    job_id: int, applicant_id: int, score: int, reason: str
) -> tuple[sqlite3.Row, bool]:
    now = utc_now()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO matches (job_id, applicant_id, score, score_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, applicant_id) DO NOTHING
            """,
            (job_id, applicant_id, score, reason, now, now),
        )
        row = conn.execute(
            "SELECT * FROM matches WHERE job_id=? AND applicant_id=?",
            (job_id, applicant_id),
        ).fetchone()
        return row, cursor.rowcount > 0


def get_match(match_id: int) -> sqlite3.Row | None:
    return _one(
        """
        SELECT m.*, j.title, j.employer_id, j.status AS job_status,
               b.name AS company, b.phone AS employer_phone,
               s.full_name, s.phone AS applicant_phone, s.profession
        FROM matches m
        JOIN jobs j ON j.id=m.job_id
        JOIN businesses b ON b.id=j.business_id
        JOIN seekers s ON s.telegram_id=m.applicant_id
        WHERE m.id=?
        """,
        (match_id,),
    )


def set_match_status(match_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE matches SET status=?, updated_at=? WHERE id=?",
            (status, utc_now(), match_id),
        )


def list_applicant_matches(applicant_id: int) -> list[sqlite3.Row]:
    return _all(
        """
        SELECT m.*, j.title, b.name AS company
        FROM matches m JOIN jobs j ON j.id=m.job_id
        JOIN businesses b ON b.id=j.business_id
        WHERE m.applicant_id=? ORDER BY m.created_at DESC
        """,
        (applicant_id,),
    )


def list_employer_matches(employer_id: int, status: str | None = None) -> list[sqlite3.Row]:
    params: list[Any] = [employer_id]
    status_sql = ""
    if status:
        status_sql = " AND m.status=?"
        params.append(status)
    return _all(
        f"""
        SELECT m.*, j.title, s.full_name, s.profession
        FROM matches m JOIN jobs j ON j.id=m.job_id
        JOIN seekers s ON s.telegram_id=m.applicant_id
        WHERE j.employer_id=?{status_sql}
        ORDER BY m.created_at DESC
        """,
        params,
    )


def toggle_favorite(applicant_id: int, job_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE applicant_id=? AND job_id=?",
            (applicant_id, job_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM favorites WHERE applicant_id=? AND job_id=?",
                (applicant_id, job_id),
            )
            return False
        conn.execute(
            "INSERT INTO favorites(applicant_id, job_id, created_at) VALUES (?, ?, ?)",
            (applicant_id, job_id, utc_now()),
        )
        return True


def list_favorites(applicant_id: int) -> list[sqlite3.Row]:
    return _all(
        """
        SELECT j.*, b.name AS company, b.verified AS business_verified
        FROM favorites f JOIN jobs j ON j.id=f.job_id
        JOIN businesses b ON b.id=j.business_id
        WHERE f.applicant_id=? AND j.status='approved'
        ORDER BY f.created_at DESC
        """,
        (applicant_id,),
    )


def dashboard_counts(user_id: int, role: str) -> dict[str, int]:
    with connect() as conn:
        if role == "seeker":
            waiting = conn.execute(
                "SELECT COUNT(*) c FROM matches WHERE applicant_id=? AND status='waiting_employer'",
                (user_id,),
            ).fetchone()["c"]
            connected = conn.execute(
                "SELECT COUNT(*) c FROM matches WHERE applicant_id=? AND status='connected'",
                (user_id,),
            ).fetchone()["c"]
            favorites = conn.execute(
                "SELECT COUNT(*) c FROM favorites WHERE applicant_id=?", (user_id,)
            ).fetchone()["c"]
            return {"waiting": waiting, "connected": connected, "favorites": favorites}
        jobs = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE employer_id=? AND status='approved'", (user_id,)
        ).fetchone()["c"]
        waiting = conn.execute(
            """
            SELECT COUNT(*) c FROM matches m JOIN jobs j ON j.id=m.job_id
            WHERE j.employer_id=? AND m.status='waiting_employer'
            """,
            (user_id,),
        ).fetchone()["c"]
        connected = conn.execute(
            """
            SELECT COUNT(*) c FROM matches m JOIN jobs j ON j.id=m.job_id
            WHERE j.employer_id=? AND m.status='connected'
            """,
            (user_id,),
        ).fetchone()["c"]
        return {"jobs": jobs, "waiting": waiting, "connected": connected}


def stats() -> dict[str, int]:
    with connect() as conn:
        return {
            "seekers": conn.execute("SELECT COUNT(*) c FROM seekers").fetchone()["c"],
            "businesses": conn.execute("SELECT COUNT(*) c FROM businesses").fetchone()["c"],
            "jobs": conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "matches": conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"],
            "connected": conn.execute("SELECT COUNT(*) c FROM matches WHERE status='connected'").fetchone()["c"],
        }
