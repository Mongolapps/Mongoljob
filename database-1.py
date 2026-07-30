import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("jobs.db")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            profession TEXT NOT NULL,
            experience TEXT NOT NULL,
            desired_salary TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER NOT NULL,
            employer_username TEXT,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '📂 Бусад',
            salary TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            plan TEXT NOT NULL DEFAULT 'free',
            premium_expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            applicant_accepted INTEGER NOT NULL DEFAULT 1,
            employer_accepted INTEGER,
            score INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting_employer',
            payment_amount INTEGER NOT NULL DEFAULT 3000,
            payment_status TEXT NOT NULL DEFAULT 'not_requested',
            payment_requested_at TEXT,
            paid_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, applicant_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status_category
        ON jobs(status, category);

        CREATE INDEX IF NOT EXISTS idx_matches_status
        ON matches(status, payment_status);
        """)

        cols = _cols(conn, "jobs")
        if "category" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN category TEXT NOT NULL DEFAULT '📂 Бусад'")
        if "plan" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
        if "premium_expires_at" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN premium_expires_at TEXT")


def save_user(data):
    with connect() as conn:
        conn.execute("""
        INSERT INTO users (
            telegram_id, username, full_name, phone,
            profession, experience, desired_salary
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            phone=excluded.phone,
            profession=excluded.profession,
            experience=excluded.experience,
            desired_salary=excluded.desired_salary
        """, (
            data["telegram_id"],
            data.get("username"),
            data["full_name"],
            data["phone"],
            data["profession"],
            data["experience"],
            data["desired_salary"],
        ))


def get_user(telegram_id):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()


def add_job(data):
    with connect() as conn:
        cur = conn.execute("""
        INSERT INTO jobs (
            employer_id, employer_username, company, title,
            category, salary, location, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["employer_id"],
            data.get("employer_username"),
            data["company"],
            data["title"],
            data["category"],
            data["salary"],
            data["location"],
            data["description"],
        ))
        return cur.lastrowid


def get_job(job_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def get_pending_jobs():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE status='pending' ORDER BY id DESC"
        ).fetchall()


def get_approved_jobs_by_category(category, limit=30):
    with connect() as conn:
        return conn.execute("""
        SELECT * FROM jobs
        WHERE status='approved' AND category=?
        ORDER BY
            CASE
                WHEN plan='vip'
                     AND premium_expires_at > CURRENT_TIMESTAMP THEN 0
                WHEN plan='premium'
                     AND premium_expires_at > CURRENT_TIMESTAMP THEN 1
                ELSE 2
            END,
            id DESC
        LIMIT ?
        """, (category, limit)).fetchall()


def approve_job(job_id, plan="free", days=None):
    if plan not in {"free", "premium", "vip"}:
        raise ValueError("invalid plan")
    with connect() as conn:
        if days:
            cur = conn.execute("""
                UPDATE jobs
                SET status='approved',
                    plan=?,
                    premium_expires_at=datetime('now', ?)
                WHERE id=? AND status='pending'
            """, (plan, f"+{int(days)} days", job_id))
        else:
            cur = conn.execute("""
                UPDATE jobs
                SET status='approved',
                    plan='free',
                    premium_expires_at=NULL
                WHERE id=? AND status='pending'
            """, (job_id,))
        return cur.rowcount > 0


def set_job_plan(job_id, plan="free", days=None):
    if plan not in {"free", "premium", "vip"}:
        raise ValueError("invalid plan")
    with connect() as conn:
        if days:
            cur = conn.execute("""
                UPDATE jobs
                SET plan=?,
                    premium_expires_at=datetime('now', ?)
                WHERE id=? AND status='approved'
            """, (plan, f"+{int(days)} days", job_id))
        else:
            cur = conn.execute("""
                UPDATE jobs
                SET plan='free',
                    premium_expires_at=NULL
                WHERE id=? AND status='approved'
            """, (job_id,))
        return cur.rowcount > 0


def reject_job(job_id):
    with connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='rejected' WHERE id=? AND status='pending'",
            (job_id,),
        )
        return cur.rowcount > 0


def create_or_get_match(job_id, applicant_id, score):
    with connect() as conn:
        existing = conn.execute("""
            SELECT id FROM matches
            WHERE job_id=? AND applicant_id=?
        """, (job_id, applicant_id)).fetchone()
        if existing:
            return existing["id"], False

        cur = conn.execute("""
            INSERT INTO matches (
                job_id, applicant_id, applicant_accepted,
                score, status, payment_amount
            )
            VALUES (?, ?, 1, ?, 'waiting_employer', 3000)
        """, (job_id, applicant_id, score))
        return cur.lastrowid, True


def get_match(match_id):
    with connect() as conn:
        return conn.execute("""
            SELECT
                m.*,
                j.employer_id,
                j.employer_username,
                j.company,
                j.title,
                j.salary,
                j.location,
                u.username AS applicant_username,
                u.full_name,
                u.phone,
                u.profession,
                u.experience,
                u.desired_salary
            FROM matches m
            JOIN jobs j ON j.id=m.job_id
            JOIN users u ON u.telegram_id=m.applicant_id
            WHERE m.id=?
        """, (match_id,)).fetchone()


def set_employer_decision(match_id, accepted, force=False):
    with connect() as conn:
        if force:
            cur = conn.execute("""
                UPDATE matches
                SET employer_accepted=0,
                    status='cancelled'
                WHERE id=?
            """, (match_id,))
        elif accepted:
            cur = conn.execute("""
                UPDATE matches
                SET employer_accepted=1,
                    status='mutual_accepted'
                WHERE id=?
                  AND status='waiting_employer'
            """, (match_id,))
        else:
            cur = conn.execute("""
                UPDATE matches
                SET employer_accepted=0,
                    status='rejected'
                WHERE id=?
                  AND status='waiting_employer'
            """, (match_id,))
        return cur.rowcount > 0


def set_payment_requested(match_id, amount=3000):
    with connect() as conn:
        cur = conn.execute("""
            UPDATE matches
            SET payment_amount=?,
                payment_status='pending',
                payment_requested_at=CURRENT_TIMESTAMP,
                status='payment_pending'
            WHERE id=?
              AND status='mutual_accepted'
              AND payment_status='not_requested'
        """, (amount, match_id))
        return cur.rowcount > 0


def mark_match_paid(match_id):
    with connect() as conn:
        cur = conn.execute("""
            UPDATE matches
            SET payment_status='paid',
                paid_at=CURRENT_TIMESTAMP,
                status='connected'
            WHERE id=?
              AND payment_status='pending'
        """, (match_id,))
        return cur.rowcount > 0


def stats():
    with connect() as conn:
        return {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "approved": conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='approved'"
            ).fetchone()[0],
            "premium": conn.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE status='approved'
                  AND plan IN ('premium', 'vip')
                  AND premium_expires_at > CURRENT_TIMESTAMP
            """).fetchone()[0],
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "payment_pending": conn.execute("""
                SELECT COUNT(*) FROM matches
                WHERE payment_status='pending'
            """).fetchone()[0],
            "paid_matches": conn.execute("""
                SELECT COUNT(*) FROM matches
                WHERE payment_status='paid'
            """).fetchone()[0],
            "revenue": conn.execute("""
                SELECT COALESCE(SUM(payment_amount), 0)
                FROM matches
                WHERE payment_status='paid'
            """).fetchone()[0],
        }
