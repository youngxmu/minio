import os
import tempfile
import unittest

from cold_backup_automation.local_state import LocalStateStore
from cold_backup_automation.outbox_sync import sync_outbox


class OutboxSyncTest(unittest.TestCase):
    def test_sync_outbox_posts_pending_items_and_marks_sent(self):
        calls = []

        def fake_post(url, payload):
            calls.append((url, payload))
            return {"status": "200", "json": {"ok": True}}

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                store.enqueue_outbox("event", "/api/v1/events", {"eventType": "started"}, "batch-1")
                summary = sync_outbox(store, "http://127.0.0.1:18080", post_json=fake_post)
                pending = store.next_outbox()
            finally:
                store.close()

        self.assertEqual(summary, {"sent": 1, "failed": 0})
        self.assertEqual(calls, [("http://127.0.0.1:18080/api/v1/events", {"eventType": "started"})])
        self.assertEqual(pending, [])

    def test_sync_outbox_marks_failed_item_for_retry(self):
        def fake_post(url, payload):
            raise RuntimeError("api unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                store.enqueue_outbox("event", "/api/v1/events", {"eventType": "started"}, "batch-1")
                summary = sync_outbox(store, "http://127.0.0.1:18080", post_json=fake_post)
                pending = store.next_outbox()
            finally:
                store.close()

        self.assertEqual(summary, {"sent": 0, "failed": 1})
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["attempt_count"], 1)
        self.assertEqual(pending[0]["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
