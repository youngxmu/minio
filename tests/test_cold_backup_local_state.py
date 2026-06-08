import os
import tempfile
import unittest

from cold_backup_automation.local_state import LocalStateStore, sha256_json


class LocalStateStoreTest(unittest.TestCase):
    def test_batch_state_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "state.sqlite3")
            store = LocalStateStore(db_path)
            store.initialize()
            store.upsert_batch(
                batch_id="batch-1",
                source_id="oldminio1",
                target_id="newminio1",
                status="RUNNING",
                manifest_uri="/data/batch-1.jsonl",
            )
            store.close()

            reopened = LocalStateStore(db_path)
            reopened.initialize()
            try:
                batch = reopened.get_batch("batch-1")
            finally:
                reopened.close()

        self.assertEqual(batch["batch_id"], "batch-1")
        self.assertEqual(batch["source_id"], "oldminio1")
        self.assertEqual(batch["target_id"], "newminio1")
        self.assertEqual(batch["status"], "RUNNING")

    def test_object_state_uses_source_bucket_key_version_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                store.upsert_object(
                    batch_id="batch-1",
                    source_id="oldminio1",
                    source_bucket="sucaiwang",
                    source_key="sucaiwang/100/200/example.mp4",
                    source_version_id="",
                    company_id=100,
                    station_id=200,
                    video_id=14708948,
                    file_role="playback_video",
                    status="SOURCE_VERIFIED",
                    size_bytes=1234,
                )
                obj = store.get_object(
                    batch_id="batch-1",
                    source_id="oldminio1",
                    source_bucket="sucaiwang",
                    source_key="sucaiwang/100/200/example.mp4",
                )
            finally:
                store.close()

        self.assertEqual(obj["company_id"], 100)
        self.assertEqual(obj["station_id"], 200)
        self.assertEqual(obj["video_id"], 14708948)
        self.assertEqual(obj["status"], "SOURCE_VERIFIED")

    def test_outbox_enqueue_is_idempotent_by_request_hash(self):
        payload = {"sourceId": "oldminio1", "companyId": 100, "stationId": 200, "videoId": 14708948}
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                first_id = store.enqueue_outbox("upsert-video", "/api/v1/batches/batch-1/videos", payload, "batch-1")
                second_id = store.enqueue_outbox("upsert-video", "/api/v1/batches/batch-1/videos", payload, "batch-1")
                pending = store.next_outbox(limit=10)
            finally:
                store.close()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["request_hash"], sha256_json(payload))

    def test_outbox_sent_item_is_not_returned_as_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                item_id = store.enqueue_outbox("event", "/api/v1/events", {"eventType": "started"}, "batch-1")
                self.assertEqual(len(store.next_outbox()), 1)
                store.mark_outbox_sent(item_id, response_status="200", response_json={"ok": True})
                self.assertEqual(store.next_outbox(), [])
            finally:
                store.close()

    def test_record_event_persists_json_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                store.record_event(
                    batch_id="batch-1",
                    event_type="transition-started",
                    message="started",
                    detail={"count": 5},
                )
                events = store.list_events("batch-1")
            finally:
                store.close()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "transition-started")
        self.assertEqual(events[0]["detail_json"], {"count": 5})


if __name__ == "__main__":
    unittest.main()
