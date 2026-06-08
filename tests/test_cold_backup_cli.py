import os
import tempfile
import unittest

from cold_backup_automation.cli import build_parser, run_videoid_smoke_plan
from cold_backup_automation.local_state import LocalStateStore


class CliTest(unittest.TestCase):
    def test_parser_accepts_first_phase_commands(self):
        parser = build_parser()

        small = parser.parse_args(["small-file-smoke", "--plan-only"])
        video = parser.parse_args(
            [
                "videoid-smoke",
                "--manifest",
                "/tmp/manifest.jsonl",
                "--company-id",
                "100",
                "--station-id",
                "200",
                "--video-id",
                "14708948",
                "--batch-id",
                "batch-1",
                "--source-id",
                "oldminio1",
                "--source-alias",
                "old1",
                "--target-id",
                "newminio1",
                "--cold-bucket",
                "tier-oldminio1-sucaiwang",
                "--cold-prefix",
                "oldminio1/sucaiwang/",
                "--tier-name",
                "COLD_OLDMINIO1_SUCAIWANG",
            ]
        )
        sync = parser.parse_args(["sync-outbox", "--state-db", "/tmp/state.sqlite3", "--api-base-url", "http://127.0.0.1:18080"])
        summary = parser.parse_args(["batch-summary", "--batch-id", "batch-1"])

        self.assertEqual(small.command, "small-file-smoke")
        self.assertEqual(video.command, "videoid-smoke")
        self.assertEqual(sync.command, "sync-outbox")
        self.assertEqual(summary.command, "batch-summary")

    def test_videoid_smoke_plan_writes_local_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "manifest.jsonl")
            state_db = os.path.join(tmpdir, "state.sqlite3")
            with open(manifest_path, "w", encoding="utf-8") as manifest:
                manifest.write(
                    '{"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,'
                    '"bucket":"sucaiwang","objects":[{"role":"cover","key":"sucaiwang/100/200/a.jpg"}]}\n'
                )

            args = build_parser().parse_args(
                [
                    "videoid-smoke",
                    "--plan-only",
                    "--manifest",
                    manifest_path,
                    "--state-db",
                    state_db,
                    "--company-id",
                    "100",
                    "--station-id",
                    "200",
                    "--video-id",
                    "14708948",
                    "--batch-id",
                    "batch-1",
                    "--source-id",
                    "oldminio1",
                    "--source-alias",
                    "old1",
                    "--target-id",
                    "newminio1",
                    "--cold-bucket",
                    "tier-oldminio1-sucaiwang",
                    "--cold-prefix",
                    "oldminio1/sucaiwang/",
                    "--tier-name",
                    "COLD_OLDMINIO1_SUCAIWANG",
                ]
            )

            summary = run_videoid_smoke_plan(args)
            store = LocalStateStore(state_db)
            store.initialize()
            try:
                batch = store.get_batch("batch-1")
                outbox = store.next_outbox()
            finally:
                store.close()

        self.assertEqual(summary["batchId"], "batch-1")
        self.assertEqual(summary["lifecyclePrefix"], "sucaiwang/100/200/")
        self.assertEqual(batch["status"], "PLANNED")
        self.assertEqual(len(outbox), 3)


if __name__ == "__main__":
    unittest.main()
