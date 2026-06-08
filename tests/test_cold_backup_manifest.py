import unittest

from cold_backup_automation.api_models import sha256_text
from cold_backup_automation.manifest import ManifestValidationError, parse_manifest_lines


class ManifestParserTest(unittest.TestCase):
    def test_parse_manifest_line_computes_object_key_hashes(self):
        videos = parse_manifest_lines(
            [
                """
                {
                  "sourceId": "oldminio1",
                  "companyId": 100,
                  "stationId": 200,
                  "videoId": 14708948,
                  "bucket": "sucaiwang",
                  "objects": [
                    {"role": "playback_video", "key": "sucaiwang/100/200/example.mp4", "required": true}
                  ]
                }
                """
            ]
        )

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].identity, ("oldminio1", 100, 200, 14708948))
        self.assertEqual(videos[0].objects[0].source_key_sha256, sha256_text("sucaiwang/100/200/example.mp4"))

    def test_manifest_requires_company_station_and_video_identity(self):
        with self.assertRaisesRegex(ManifestValidationError, "companyId"):
            parse_manifest_lines(
                [
                    """
                    {
                      "sourceId": "oldminio1",
                      "stationId": 200,
                      "videoId": 14708948,
                      "bucket": "sucaiwang",
                      "objects": []
                    }
                    """
                ]
            )

    def test_manifest_allows_same_video_id_for_different_company(self):
        videos = parse_manifest_lines(
            [
                """
                {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
                 "bucket":"sucaiwang","objects":[{"role":"cover","key":"a.jpg"}]}
                """,
                """
                {"sourceId":"oldminio1","companyId":101,"stationId":200,"videoId":14708948,
                 "bucket":"sucaiwang","objects":[{"role":"cover","key":"b.jpg"}]}
                """,
            ]
        )

        self.assertEqual(len(videos), 2)
        self.assertNotEqual(videos[0].identity, videos[1].identity)

    def test_manifest_rejects_duplicate_full_video_identity(self):
        lines = [
            """
            {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
             "bucket":"sucaiwang","objects":[{"role":"cover","key":"a.jpg"}]}
            """,
            """
            {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
             "bucket":"sucaiwang","objects":[{"role":"cover","key":"b.jpg"}]}
            """,
        ]

        with self.assertRaisesRegex(ManifestValidationError, "duplicate"):
            parse_manifest_lines(lines)

    def test_manifest_rejects_unknown_file_role(self):
        with self.assertRaisesRegex(ManifestValidationError, "unknown file role"):
            parse_manifest_lines(
                [
                    """
                    {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
                     "bucket":"sucaiwang","objects":[{"role":"mystery","key":"x.bin"}]}
                    """
                ]
            )


if __name__ == "__main__":
    unittest.main()
