import os
import tempfile
import unittest
from unittest.mock import patch

from cold_backup_automation.cli import build_parser, run_small_file_smoke, run_videoid_smoke_plan
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

    def test_small_file_smoke_run_builds_runner_config(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, mc_runner=None, http_code=None, state_store=None, command_builder=None):
                captured["config"] = config
                captured["state_store"] = state_store
                captured["command_builder"] = command_builder

            def run(self):
                return {"transition": "OK", "batchId": captured["config"].batch_id}

        with tempfile.TemporaryDirectory() as tmpdir:
            state_db = os.path.join(tmpdir, "state.sqlite3")
            args = build_parser().parse_args(
                [
                    "small-file-smoke",
                    "--state-db",
                    state_db,
                    "--batch-id",
                    "smoke-1",
                    "--source-id",
                    "oldminio1",
                    "--source-alias",
                    "old1",
                    "--source-endpoint",
                    "http://old",
                    "--source-bucket",
                    "sucaiwang",
                    "--source-prefix",
                    "smoke/smoke-1",
                    "--target-id",
                    "newminio1",
                    "--cold-alias",
                    "cold1",
                    "--cold-endpoint",
                    "http://cold",
                    "--cold-bucket",
                    "tier-bucket",
                    "--cold-prefix",
                    "oldminio1/smoke-1/",
                    "--tier-name",
                    "COLD_SMOKE",
                    "--cold-access-key",
                    "ak",
                    "--cold-secret-key",
                    "sk",
                    "--work-dir",
                    tmpdir,
                    "--file-size-bytes",
                    "1024",
                    "--poll-interval-seconds",
                    "0",
                    "--timeout-seconds",
                    "1",
                    "--mc-binary",
                    "/usr/local/bin/mc",
                ]
            )

            summary = run_small_file_smoke(args, runner_factory=FakeRunner)

        self.assertEqual(summary["transition"], "OK")
        self.assertEqual(captured["config"].batch_id, "smoke-1")
        self.assertEqual(captured["config"].cold_prefix, "oldminio1/smoke-1/")
        self.assertIsNotNone(captured["state_store"])
        self.assertEqual(captured["command_builder"].mc_binary, "/usr/local/bin/mc")

    def test_small_file_smoke_can_read_cold_credentials_from_environment(self):
        captured = {}

        class FakeRunner:
            def __init__(self, config, mc_runner=None, http_code=None, state_store=None, command_builder=None):
                captured["config"] = config

            def run(self):
                return {"transition": "OK"}

        with tempfile.TemporaryDirectory() as tmpdir:
            args = build_parser().parse_args(
                [
                    "small-file-smoke",
                    "--state-db",
                    os.path.join(tmpdir, "state.sqlite3"),
                    "--batch-id",
                    "smoke-env",
                    "--source-id",
                    "oldminio1",
                    "--source-alias",
                    "old1",
                    "--source-endpoint",
                    "http://old",
                    "--source-bucket",
                    "sucaiwang",
                    "--source-prefix",
                    "smoke/smoke-env",
                    "--target-id",
                    "newminio1",
                    "--cold-alias",
                    "cold1",
                    "--cold-endpoint",
                    "http://cold",
                    "--cold-bucket",
                    "tier-bucket",
                    "--cold-prefix",
                    "oldminio1/smoke-env/",
                    "--tier-name",
                    "COLD_SMOKE_ENV",
                    "--cold-access-key-env",
                    "COLD_AK",
                    "--cold-secret-key-env",
                    "COLD_SK",
                    "--work-dir",
                    tmpdir,
                ]
            )

            with patch.dict(os.environ, {"COLD_AK": "ak-from-env", "COLD_SK": "sk-from-env"}):
                run_small_file_smoke(args, runner_factory=FakeRunner)

        self.assertEqual(captured["config"].cold_access_key, "ak-from-env")
        self.assertEqual(captured["config"].cold_secret_key, "sk-from-env")


if __name__ == "__main__":
    unittest.main()
