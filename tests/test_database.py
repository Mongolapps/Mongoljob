import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tempdir.name) / "test.db"
        database.init_db()

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed(self):
        database.save_seeker(
            {
                "telegram_id": 100,
                "username": "applicant",
                "full_name": "Test Applicant",
                "profession": "Python developer",
                "location": "Ulaanbaatar",
                "desired_salary": "3,000,000",
                "phone": "99000000",
                "experience": "2 years",
            }
        )
        database.set_seeker_status(100, "approved")
        business_id = database.save_business(
            {
                "owner_id": 200,
                "owner_username": "employer",
                "name": "Test LLC",
                "phone": "88000000",
                "location": "Ulaanbaatar",
            }
        )
        database.set_business_status(business_id, "approved", True)
        job_id = database.add_job(
            {
                "employer_id": 200,
                "business_id": business_id,
                "title": "Python developer",
                "category": "💻 IT",
                "salary": "3,500,000",
                "location": "Ulaanbaatar",
                "schedule": "Full time",
                "job_type": "full_time",
                "requirements": "Python",
            }
        )
        database.set_job_status(job_id, "approved")
        return job_id

    def test_duplicate_match_is_reported_without_creating_another_row(self):
        job_id = self._seed()
        first, first_created = database.create_match(job_id, 100, 90, "match")
        second, second_created = database.create_match(job_id, 100, 90, "match")

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(database.stats()["matches"], 1)

    def test_expired_promotion_returns_to_free_plan(self):
        job_id = self._seed()
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        database.set_job_plan(job_id, "vip", expired)

        job = database.get_job(job_id)

        self.assertEqual(job["plan"], "free")
        self.assertIsNone(job["premium_expires_at"])

    def test_old_schema_is_migrated_before_indexes_are_created(self):
        database.DB_PATH.unlink()
        with sqlite3.connect(database.DB_PATH) as conn:
            conn.executescript(
                """
                CREATE TABLE seekers (
                    telegram_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL,
                    profession TEXT NOT NULL, location TEXT NOT NULL,
                    desired_salary TEXT NOT NULL, phone TEXT NOT NULL
                );
                CREATE TABLE businesses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL UNIQUE,
                    name TEXT NOT NULL, phone TEXT NOT NULL, location TEXT NOT NULL
                );
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, employer_id INTEGER NOT NULL,
                    business_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
                    salary TEXT NOT NULL, location TEXT NOT NULL, schedule TEXT NOT NULL,
                    requirements TEXT NOT NULL
                );
                CREATE TABLE matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
                    applicant_id INTEGER NOT NULL, UNIQUE(job_id, applicant_id)
                );
                """
            )

        database.init_db()

        with database.connect() as conn:
            job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        self.assertIn("job_type", job_columns)
        self.assertIn("plan", job_columns)
        self.assertIn("views", job_columns)


if __name__ == "__main__":
    unittest.main()
