import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("servigo.db")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def _cols(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            profession TEXT,
            experience TEXT,
            desired_salary TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            plan TEXT NOT NULL DEFAULT 'free',
            premium_expires_at TEXT,
            channel_message_id INTEGER,
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL UNIQUE,
            owner_username TEXT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            phone TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            plan TEXT NOT NULL DEFAULT 'free',
            premium_expires_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            price TEXT NOT NULL,
            duration TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            requested_time TEXT NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(service_id, customer_id, requested_time),
            FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER NOT NULL,
            employer_username TEXT,
            business_id INTEGER,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            job_type TEXT NOT NULL DEFAULT 'full_time',
            category TEXT NOT NULL,
            salary TEXT NOT NULL,
            schedule TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            plan TEXT NOT NULL DEFAULT 'free',
            premium_expires_at TEXT,
            channel_message_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            employer_accepted INTEGER,
            status TEXT NOT NULL DEFAULT 'waiting_employer',
            connected_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, applicant_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_businesses_status_category ON businesses(status, category);
        CREATE INDEX IF NOT EXISTS idx_services_business ON services(business_id, status);
        CREATE INDEX IF NOT EXISTS idx_jobs_status_type_category ON jobs(status, job_type, category);
        CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
        CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
        """)

        # Шинэ багануудыг хуучин database-д нэмж шинэчилнэ.
        user_cols = _cols(conn, "users")
        for col, ddl in {
            "status": "TEXT NOT NULL DEFAULT 'pending'",
            "plan": "TEXT NOT NULL DEFAULT 'free'",
            "premium_expires_at": "TEXT",
            "channel_message_id": "INTEGER",
            "notifications_enabled": "INTEGER NOT NULL DEFAULT 1",
        }.items():
            if col not in user_cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

        job_cols = _cols(conn, "jobs")
        if "channel_message_id" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN channel_message_id INTEGER")

        # Хуучин төлбөрийн баганатай matches хүснэгтийг төлбөргүй бүтэц рүү шилжүүлнэ.
        match_cols = _cols(conn, "matches")
        if "payment_status" in match_cols or "payment_amount" in match_cols or "paid_at" in match_cols:
            connected_expr = "COALESCE(paid_at, CURRENT_TIMESTAMP)" if "paid_at" in match_cols else "CURRENT_TIMESTAMP"
            conn.executescript(f"""
            ALTER TABLE matches RENAME TO matches_old;

            CREATE TABLE matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                applicant_id INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                employer_accepted INTEGER,
                status TEXT NOT NULL DEFAULT 'waiting_employer',
                connected_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(job_id, applicant_id),
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            INSERT INTO matches (
                id, job_id, applicant_id, score, employer_accepted,
                status, connected_at, created_at
            )
            SELECT
                id, job_id, applicant_id, score, employer_accepted,
                CASE
                    WHEN status IN ('connected', 'payment_pending', 'mutual_accepted') THEN 'connected'
                    ELSE status
                END,
                CASE
                    WHEN status IN ('connected', 'payment_pending', 'mutual_accepted') THEN {connected_expr}
                    ELSE NULL
                END,
                created_at
            FROM matches_old;

            DROP TABLE matches_old;
            CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
            """)


def save_user(data):
    with connect() as conn:
        conn.execute("""
        INSERT INTO users (telegram_id, username, full_name, phone, profession, experience, desired_salary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            phone=excluded.phone,
            profession=excluded.profession,
            experience=excluded.experience,
            desired_salary=excluded.desired_salary,
            status='pending'
        """, (
            data["telegram_id"], data.get("username"), data["full_name"], data["phone"],
            data.get("profession", ""), data.get("experience", ""), data.get("desired_salary", "")
        ))


def get_user(telegram_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()


def add_business(data):
    with connect() as conn:
        existing = conn.execute("SELECT id FROM businesses WHERE owner_id=?", (data["owner_id"],)).fetchone()
        if existing:
            conn.execute("""
            UPDATE businesses SET owner_username=?, name=?, category=?, phone=?, location=?,
                description=?, status='pending' WHERE owner_id=?
            """, (data.get("owner_username"), data["name"], data["category"], data["phone"],
                  data["location"], data["description"], data["owner_id"]))
            return existing["id"]
        cur = conn.execute("""
        INSERT INTO businesses (owner_id, owner_username, name, category, phone, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data["owner_id"], data.get("owner_username"), data["name"], data["category"],
              data["phone"], data["location"], data["description"]))
        return cur.lastrowid


def get_business(business_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()


def get_business_by_owner(owner_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM businesses WHERE owner_id=?", (owner_id,)).fetchone()


def get_pending_businesses():
    with connect() as conn:
        return conn.execute("SELECT * FROM businesses WHERE status='pending' ORDER BY id DESC").fetchall()


def approve_business(business_id, approved=True):
    with connect() as conn:
        status = "approved" if approved else "rejected"
        cur = conn.execute("UPDATE businesses SET status=? WHERE id=? AND status='pending'", (status, business_id))
        return cur.rowcount > 0


def get_businesses_by_category(category, limit=30):
    with connect() as conn:
        return conn.execute("""
        SELECT * FROM businesses WHERE status='approved' AND category=?
        ORDER BY CASE WHEN plan='premium' AND premium_expires_at > CURRENT_TIMESTAMP THEN 0 ELSE 1 END, id DESC
        LIMIT ?
        """, (category, limit)).fetchall()


def add_service(data):
    with connect() as conn:
        cur = conn.execute("""
        INSERT INTO services (business_id, title, price, duration, description)
        VALUES (?, ?, ?, ?, ?)
        """, (data["business_id"], data["title"], data["price"], data["duration"], data["description"]))
        return cur.lastrowid


def get_service(service_id):
    with connect() as conn:
        return conn.execute("""
        SELECT s.*, b.name AS business_name, b.owner_id, b.phone AS business_phone,
               b.location, b.category, b.status AS business_status
        FROM services s JOIN businesses b ON b.id=s.business_id WHERE s.id=?
        """, (service_id,)).fetchone()


def get_services_by_business(business_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM services WHERE business_id=? AND status='active' ORDER BY id DESC", (business_id,)).fetchall()


def create_booking(service_id, customer_id, requested_time, note=""):
    with connect() as conn:
        try:
            cur = conn.execute("""
            INSERT INTO bookings (service_id, customer_id, requested_time, note)
            VALUES (?, ?, ?, ?)
            """, (service_id, customer_id, requested_time, note))
            return cur.lastrowid, True
        except sqlite3.IntegrityError:
            row = conn.execute("SELECT id FROM bookings WHERE service_id=? AND customer_id=? AND requested_time=?",
                               (service_id, customer_id, requested_time)).fetchone()
            return row["id"], False


def get_booking(booking_id):
    with connect() as conn:
        return conn.execute("""
        SELECT bk.*, s.title AS service_title, s.price, b.name AS business_name, b.owner_id,
               u.full_name, u.phone, u.username
        FROM bookings bk
        JOIN services s ON s.id=bk.service_id
        JOIN businesses b ON b.id=s.business_id
        LEFT JOIN users u ON u.telegram_id=bk.customer_id
        WHERE bk.id=?
        """, (booking_id,)).fetchone()


def set_booking_status(booking_id, owner_id, status):
    if status not in {"approved", "rejected", "completed", "cancelled"}:
        raise ValueError("invalid booking status")
    with connect() as conn:
        cur = conn.execute("""
        UPDATE bookings SET status=? WHERE id=? AND status='pending' AND EXISTS (
            SELECT 1 FROM services s JOIN businesses b ON b.id=s.business_id
            WHERE s.id=bookings.service_id AND b.owner_id=?
        )
        """, (status, booking_id, owner_id))
        return cur.rowcount > 0


def add_job(data):
    with connect() as conn:
        cur = conn.execute("""
        INSERT INTO jobs (employer_id, employer_username, business_id, company, title, job_type,
                          category, salary, schedule, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data["employer_id"], data.get("employer_username"), data.get("business_id"), data["company"],
              data["title"], data["job_type"], data["category"], data["salary"], data["schedule"],
              data["location"], data["description"]))
        return cur.lastrowid


def get_job(job_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def get_pending_jobs():
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id DESC").fetchall()


def approve_job(job_id, plan="free", days=None):
    with connect() as conn:
        if days:
            cur = conn.execute("""
            UPDATE jobs SET status='approved', plan=?, premium_expires_at=datetime('now', ?)
            WHERE id=? AND status='pending'
            """, (plan, f"+{int(days)} days", job_id))
        else:
            cur = conn.execute("UPDATE jobs SET status='approved', plan='free', premium_expires_at=NULL WHERE id=? AND status='pending'", (job_id,))
        return cur.rowcount > 0


def reject_job(job_id):
    with connect() as conn:
        cur = conn.execute("UPDATE jobs SET status='rejected' WHERE id=? AND status='pending'", (job_id,))
        return cur.rowcount > 0


def get_approved_jobs(job_type, category, limit=30):
    with connect() as conn:
        return conn.execute("""
        SELECT * FROM jobs WHERE status='approved' AND job_type=? AND category=?
        ORDER BY CASE WHEN plan='vip' AND premium_expires_at > CURRENT_TIMESTAMP THEN 0
                      WHEN plan='premium' AND premium_expires_at > CURRENT_TIMESTAMP THEN 1 ELSE 2 END,
                 id DESC LIMIT ?
        """, (job_type, category, limit)).fetchall()


def create_or_get_match(job_id, applicant_id, score):
    with connect() as conn:
        row = conn.execute("SELECT id FROM matches WHERE job_id=? AND applicant_id=?", (job_id, applicant_id)).fetchone()
        if row:
            return row["id"], False
        cur = conn.execute("INSERT INTO matches (job_id, applicant_id, score) VALUES (?, ?, ?)",
                           (job_id, applicant_id, score))
        return cur.lastrowid, True


def get_match(match_id):
    with connect() as conn:
        return conn.execute("""
        SELECT m.*, j.employer_id, j.employer_username, j.company, j.title, j.job_type, j.salary,
               u.username AS applicant_username, u.full_name, u.phone, u.profession, u.experience, u.desired_salary
        FROM matches m JOIN jobs j ON j.id=m.job_id JOIN users u ON u.telegram_id=m.applicant_id
        WHERE m.id=?
        """, (match_id,)).fetchone()


def set_employer_decision(match_id, accepted):
    with connect() as conn:
        if accepted:
            cur = conn.execute("""
            UPDATE matches
            SET employer_accepted=1,
                status='connected',
                connected_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='waiting_employer'
            """, (match_id,))
        else:
            cur = conn.execute("""
            UPDATE matches
            SET employer_accepted=0,
                status='rejected'
            WHERE id=? AND status='waiting_employer'
            """, (match_id,))
        return cur.rowcount > 0



def approve_user(telegram_id, plan="free", hours=None):
    with connect() as conn:
        if hours:
            cur = conn.execute(
                "UPDATE users SET status='approved', plan=?, premium_expires_at=datetime('now', ?) WHERE telegram_id=? AND status='pending'",
                (plan, f"+{int(hours)} hours", telegram_id),
            )
        else:
            cur = conn.execute(
                "UPDATE users SET status='approved', plan='free', premium_expires_at=NULL WHERE telegram_id=? AND status='pending'",
                (telegram_id,),
            )
        return cur.rowcount > 0


def reject_user(telegram_id):
    with connect() as conn:
        cur = conn.execute("UPDATE users SET status='rejected' WHERE telegram_id=? AND status='pending'", (telegram_id,))
        return cur.rowcount > 0


def set_job_channel_message(job_id, message_id):
    with connect() as conn:
        conn.execute("UPDATE jobs SET channel_message_id=? WHERE id=?", (message_id, job_id))


def set_user_channel_message(telegram_id, message_id):
    with connect() as conn:
        conn.execute("UPDATE users SET channel_message_id=? WHERE telegram_id=?", (message_id, telegram_id))


def get_promoted_jobs():
    with connect() as conn:
        return conn.execute("""
        SELECT * FROM jobs
        WHERE status='approved' AND plan IN ('premium','vip')
          AND premium_expires_at > CURRENT_TIMESTAMP
          AND channel_message_id IS NOT NULL
        """).fetchall()


def get_promoted_users():
    with connect() as conn:
        return conn.execute("""
        SELECT * FROM users
        WHERE status='approved' AND plan='premium'
          AND premium_expires_at > CURRENT_TIMESTAMP
          AND channel_message_id IS NOT NULL
        """).fetchall()


def get_notifiable_users(exclude_id=None):
    with connect() as conn:
        if exclude_id is None:
            return conn.execute("SELECT telegram_id FROM users WHERE status='approved' AND notifications_enabled=1").fetchall()
        return conn.execute("SELECT telegram_id FROM users WHERE status='approved' AND notifications_enabled=1 AND telegram_id<>?", (exclude_id,)).fetchall()


def toggle_notifications(telegram_id):
    with connect() as conn:
        conn.execute("UPDATE users SET notifications_enabled=CASE notifications_enabled WHEN 1 THEN 0 ELSE 1 END WHERE telegram_id=?", (telegram_id,))
        row = conn.execute("SELECT notifications_enabled FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return bool(row and row[0])



def expire_promotions():
    """Хугацаа дууссан premium/vip төлөвийг энгийн төлөвт шилжүүлнэ."""
    with connect() as conn:
        conn.execute("""
        UPDATE jobs
        SET plan='free', premium_expires_at=NULL
        WHERE plan IN ('premium','vip')
          AND premium_expires_at IS NOT NULL
          AND premium_expires_at <= CURRENT_TIMESTAMP
        """)
        conn.execute("""
        UPDATE users
        SET plan='free', premium_expires_at=NULL
        WHERE plan='premium'
          AND premium_expires_at IS NOT NULL
          AND premium_expires_at <= CURRENT_TIMESTAMP
        """)

def stats():
    with connect() as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        return {
            "users": q("SELECT COUNT(*) FROM users"),
            "businesses": q("SELECT COUNT(*) FROM businesses"),
            "approved_businesses": q("SELECT COUNT(*) FROM businesses WHERE status='approved'"),
            "services": q("SELECT COUNT(*) FROM services"),
            "bookings": q("SELECT COUNT(*) FROM bookings"),
            "jobs": q("SELECT COUNT(*) FROM jobs"),
            "part_time_jobs": q("SELECT COUNT(*) FROM jobs WHERE job_type='part_time'"),
            "matches": q("SELECT COUNT(*) FROM matches"),
            "connected_matches": q("SELECT COUNT(*) FROM matches WHERE status='connected'"),
        }
