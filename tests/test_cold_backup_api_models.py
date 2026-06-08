import unittest

from cold_backup_automation.api_models import (
    MappingPayload,
    ObjectPayload,
    PayloadValidationError,
    VideoPayload,
    sha256_text,
)


class ApiModelTest(unittest.TestCase):
    def test_video_identity_includes_source_company_station_and_video(self):
        first = VideoPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 100,
                "stationId": 200,
                "videoId": 14708948,
            }
        )
        second = VideoPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 101,
                "stationId": 200,
                "videoId": 14708948,
            }
        )

        self.assertEqual(first.identity, ("oldminio1", 100, 200, 14708948))
        self.assertNotEqual(first.identity, second.identity)

    def test_video_payload_rejects_missing_company_id(self):
        with self.assertRaisesRegex(PayloadValidationError, "companyId"):
            VideoPayload.from_api(
                {
                    "sourceId": "oldminio1",
                    "stationId": 200,
                    "videoId": 14708948,
                }
            )

    def test_object_payload_computes_source_key_hash(self):
        payload = ObjectPayload.from_api(
            {
                "sourceId": "oldminio1",
                "companyId": 100,
                "stationId": 200,
                "videoId": 14708948,
                "fileRole": "playback_video",
                "sourceBucket": "sucaiwang",
                "sourceKey": "sucaiwang/100/200/example.mp4",
                "sizeBytes": 1234,
            }
        )

        self.assertEqual(payload.source_key_sha256, sha256_text("sucaiwang/100/200/example.mp4"))
        self.assertEqual(payload.identity, ("oldminio1", 100, 200, 14708948, "playback_video"))

    def test_mapping_payload_computes_source_and_cold_key_hashes(self):
        payload = MappingPayload.from_api(
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

        self.assertEqual(payload.source_key_sha256, sha256_text("sucaiwang/100/200/example.mp4"))
        self.assertEqual(payload.cold_object_key_sha256, sha256_text("oldminio1/sucaiwang/.minio.sys/example"))


if __name__ == "__main__":
    unittest.main()
