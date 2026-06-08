import unittest

from cold_backup_automation.api_models import MappingPayload, VideoPayload, sha256_text
from cold_backup_automation.repository import SucaiMetaRepository


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, tuple(params or ())))

    def fetchone(self):
        return self.connection.fetchone_row

    def fetchall(self):
        return self.connection.fetchall_rows


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.fetchone_row = None
        self.fetchall_rows = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class RepositoryTest(unittest.TestCase):
    def test_upsert_video_uses_business_identity_unique_columns(self):
        connection = FakeConnection()
        repo = SucaiMetaRepository(connection)
        video = VideoPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 100,
                "stationId": 200,
                "videoId": 14708948,
                "requiredObjectCount": 5,
            }
        )

        repo.upsert_video(video)

        sql, params = connection.executed[0]
        self.assertIn("INSERT INTO meta_video", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(params[:4], ("oldminio1", 100, 200, 14708948))
        self.assertEqual(connection.commits, 1)

    def test_attach_video_to_batch_keeps_company_station_video_identity(self):
        connection = FakeConnection()
        repo = SucaiMetaRepository(connection)
        video = VideoPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 100,
                "stationId": 200,
                "videoId": 14708948,
            }
        )

        repo.attach_video_to_batch("batch-1", video)

        sql, params = connection.executed[0]
        self.assertIn("INSERT INTO meta_batch_video", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(params[:5], ("batch-1", "oldminio1", 100, 200, 14708948))

    def test_upsert_mapping_writes_mapping_hash_and_identity(self):
        connection = FakeConnection()
        repo = SucaiMetaRepository(connection)
        mapping = MappingPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 100,
                "stationId": 200,
                "videoId": 14708948,
                "fileRole": "playback_video",
                "sourceBucket": "sucaiwang",
                "sourceKey": "sucaiwang/100/200/example.mp4",
                "sourceSha256": "a" * 64,
                "targetId": "newminio1",
                "coldBucket": "tier-oldminio1-sucaiwang",
                "coldPrefix": "oldminio1/sucaiwang/",
                "coldObjectKey": "oldminio1/sucaiwang/.minio.sys/example",
                "coldSha256": "b" * 64,
                "tierName": "COLD_OLDMINIO1_SUCAIWANG",
                "transitionBatchId": "batch-1",
            }
        )

        repo.upsert_mapping(mapping)

        sql, params = connection.executed[0]
        self.assertIn("INSERT INTO meta_object_mapping", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertIn(sha256_text("sucaiwang/100/200/example.mp4"), params)
        self.assertEqual(params[:5], ("oldminio1", 100, 200, 14708948, "playback_video"))

    def test_lookup_mapping_uses_source_bucket_key_hash(self):
        connection = FakeConnection()
        connection.fetchone_row = {"source_id": "oldminio1"}
        repo = SucaiMetaRepository(connection)

        row = repo.lookup_mapping("oldminio1", "sucaiwang", "sucaiwang/100/200/example.mp4")

        sql, params = connection.executed[0]
        self.assertIn("FROM meta_object_mapping", sql)
        self.assertEqual(params, ("oldminio1", "sucaiwang", sha256_text("sucaiwang/100/200/example.mp4"), ""))
        self.assertEqual(row, {"source_id": "oldminio1"})


if __name__ == "__main__":
    unittest.main()
