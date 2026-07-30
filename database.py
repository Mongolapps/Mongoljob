import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name('jobs.db')

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.executescript('''
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
            salary TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, applicant_id)
        );
        ''')

def save_user(data):
    with connect() as conn:
        conn.execute('''
        INSERT INTO users (telegram_id, username, full_name, phone, profession, experience, desired_salary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
          username=excluded.username, full_name=excluded.full_name,
          phone=excluded.phone, profession=excluded.profession,
          experience=excluded.experience, desired_salary=excluded.desired_salary
        ''', (data['telegram_id'], data.get('username'), data['full_name'], data['phone'],
              data['profession'], data['experience'], data['desired_salary']))

def get_user(telegram_id):
    with connect() as conn:
        return conn.execute('SELECT * FROM users WHERE telegram_id=?', (telegram_id,)).fetchone()

def add_job(data):
    with connect() as conn:
        cur = conn.execute('''
        INSERT INTO jobs (employer_id, employer_username, company, title, salary, location, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (data['employer_id'], data.get('employer_username'), data['company'], data['title'],
              data['salary'], data['location'], data['description']))
        return cur.lastrowid

def get_job(job_id):
    with connect() as conn:
        return conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()

def get_pending_jobs():
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id DESC").fetchall()

def get_approved_jobs(limit=30):
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE status='approved' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

def approve_job(job_id):
    with connect() as conn:
        cur = conn.execute("UPDATE jobs SET status='approved' WHERE id=? AND status='pending'", (job_id,))
        return cur.rowcount > 0

def reject_job(job_id):
    with connect() as conn:
        cur = conn.execute("UPDATE jobs SET status='rejected' WHERE id=? AND status='pending'", (job_id,))
        return cur.rowcount > 0

def apply_to_job(job_id, applicant_id):
    try:
        with connect() as conn:
            conn.execute('INSERT INTO applications (job_id, applicant_id) VALUES (?, ?)', (job_id, applicant_id))
        return True
    except sqlite3.IntegrityError:
        return False

def stats():
    with connect() as conn:
        return {
            'users': conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],
            'jobs': conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
            'approved': conn.execute("SELECT COUNT(*) FROM jobs WHERE status='approved'").fetchone()[0],
            'applications': conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0],
        }
