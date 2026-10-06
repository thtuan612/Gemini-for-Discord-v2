import unittest
from datetime import timedelta

import dashboard_views as v


class DashboardViewsTests(unittest.TestCase):
    def test_session_store_has_csrf_and_expiry(self):
        store = v.SessionStore(ttl=60)
        token, session = store.create()
        self.assertEqual(len(token), 43)
        self.assertTrue(session.csrf)
        self.assertIs(store.get(token), session)
        store.delete(token)
        self.assertIsNone(store.get(token))

    def test_login_limiter_blocks_after_five_failures(self):
        limiter = v.LoginLimiter(max_failures=5, window=60, block_time=60)
        for _ in range(5):
            limiter.fail("127.0.0.1")
        self.assertTrue(limiter.blocked("127.0.0.1"))
        limiter.reset("127.0.0.1")
        self.assertFalse(limiter.blocked("127.0.0.1"))

    def test_renderers_escape_untrusted_values(self):
        body = v.overview_body(
            {
                "ping_ms": 1, "uptime": timedelta(seconds=1), "guild_count": 1,
                "members": 1, "ram": 1024, "ram_limit": 2048, "disk": 1024,
                "db_size": 1024, "reminders": 0, "autochat": 0,
                "model": "<script>alert(1)</script>", "python": "3", "dpy": "2",
            },
            [{"name": '<img src=x onerror=alert(1)>', "id": 1, "members": 1,
              "autochat": 0, "reminders": 0}],
        )
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img src=x onerror=alert(1)>", body)
        self.assertIn("&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()
