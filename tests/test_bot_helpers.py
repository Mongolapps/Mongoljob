import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import bot
from bot import match_score, remaining_text


class BotHelperTests(unittest.TestCase):
    def test_match_score_rewards_profession_location_and_salary(self):
        seeker = {
            "profession": "Python developer",
            "location": "Ulaanbaatar",
            "desired_salary": "3,000,000",
        }
        job = {
            "title": "Senior Python developer",
            "requirements": "Python API experience",
            "category": "💻 IT",
            "location": "Ulaanbaatar",
            "salary": "3,500,000",
        }

        score, reason = match_score(seeker, job)

        self.assertGreaterEqual(score, 70)
        self.assertIn("Байршил", reason)

    def test_remaining_text_handles_expired_timestamp(self):
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertEqual(remaining_text(expired), "⌛ Хугацаа дууссан")

    def test_invalid_token_has_clear_startup_error(self):
        with patch.object(bot, "BOT_TOKEN", "invalid"), patch.object(bot, "ADMIN_ID", 123):
            with self.assertRaisesRegex(RuntimeError, "BOT_TOKEN буруу форматтай"):
                bot.validate_config()

    def test_missing_admin_has_clear_startup_error(self):
        with patch.object(bot, "BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz"), patch.object(bot, "ADMIN_ID", 0):
            with self.assertRaisesRegex(RuntimeError, "ADMIN_ID"):
                bot.validate_config()


if __name__ == "__main__":
    unittest.main()
