import os
import tempfile
import unittest

from cold_backup_automation.local_state import LocalStateStore
from cold_backup_automation.manifest import parse_manifest_lines
from cold_backup_automation.mc import McCommandBuilder
from cold_backup_automation.migrator import MigrationConfig, MigrationPlanner, derive_common_object_prefix


class McCommandBuilderTest(unittest.TestCase):
    def test_lifecycle_rule_command_is_scoped_to_one_prefix(self):
        builder = McCommandBuilder(mc_binary="/opt/minio-tools/mc")

        command = builder.add_lifecycle_rule(
            source_alias="old1",
            bucket="sucaiwang",
            prefix="sucaiwang/100/200/",
            tier_name="COLD_OLDMINIO1_SUCAIWANG",
        )

        self.assertEqual(
            command,
            [
                "/opt/minio-tools/mc",
                "ilm",
                "rule",
                "add",
                "old1/sucaiwang",
                "--prefix",
                "sucaiwang/100/200/",
                "--transition-days",
                "0",
                "--transition-tier",
                "COLD_OLDMINIO1_SUCAIWANG",
            ],
        )

    def test_tier_add_display_command_masks_secret_key(self):
        builder = McCommandBuilder()

        command = builder.add_minio_tier(
            source_alias="old1",
            tier_name="COLD_OLDMINIO1_SUCAIWANG",
            endpoint="http://newminio1:9000",
            access_key="access",
            secret_key="test-redaction-value",
            bucket="tier-oldminio1-sucaiwang",
            prefix="oldminio1/sucaiwang/",
        )

        display = builder.display_command(command)

        self.assertIn("--secret-key", display)
        self.assertNotIn("test-redaction-value", display)
        self.assertIn("<redacted>", display)


class MigrationPlannerTest(unittest.TestCase):
    def test_common_prefix_uses_deepest_shared_directory(self):
        prefix = derive_common_object_prefix(
            [
                "sucaiwang/100/200/example_h265.MOV",
                "sucaiwang/100/200/example_mark919.MOV",
                "sucaiwang/100/200/example.mp4",
            ]
        )

        self.assertEqual(prefix, "sucaiwang/100/200/")

    def test_videoid_plan_selects_company_station_specific_video(self):
        videos = parse_manifest_lines(
            [
                """
                {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
                 "bucket":"sucaiwang","objects":[{"role":"cover","key":"sucaiwang/100/200/a.jpg"}]}
                """,
                """
                {"sourceId":"oldminio1","companyId":101,"stationId":200,"videoId":14708948,
                 "bucket":"sucaiwang","objects":[{"role":"cover","key":"sucaiwang/101/200/b.jpg"}]}
                """,
            ]
        )
        planner = MigrationPlanner(
            MigrationConfig(
                batch_id="batch-1",
                source_id="oldminio1",
                source_alias="old1",
                target_id="newminio1",
                cold_bucket="tier-oldminio1-sucaiwang",
                cold_prefix="oldminio1/sucaiwang/",
                tier_name="COLD_OLDMINIO1_SUCAIWANG",
            )
        )

        plan = planner.plan_videoid_smoke(videos, company_id=101, station_id=200, video_id=14708948)

        self.assertEqual(plan.video.identity, ("oldminio1", 101, 200, 14708948))
        self.assertEqual(plan.lifecycle_prefix, "sucaiwang/101/200/")
        self.assertEqual(plan.lifecycle_rule_command[4], "old1/sucaiwang")

    def test_plan_writes_batch_video_and_object_requests_to_local_outbox(self):
        videos = parse_manifest_lines(
            [
                """
                {"sourceId":"oldminio1","companyId":100,"stationId":200,"videoId":14708948,
                 "bucket":"sucaiwang","objects":[
                   {"role":"cover","key":"sucaiwang/100/200/a.jpg"},
                   {"role":"playback_video","key":"sucaiwang/100/200/a.mp4"}
                 ]}
                """
            ]
        )
        planner = MigrationPlanner(
            MigrationConfig(
                batch_id="batch-1",
                source_id="oldminio1",
                source_alias="old1",
                target_id="newminio1",
                cold_bucket="tier-oldminio1-sucaiwang",
                cold_prefix="oldminio1/sucaiwang/",
                tier_name="COLD_OLDMINIO1_SUCAIWANG",
                max_migratable_bytes=1024,
            )
        )
        plan = planner.plan_videoid_smoke(videos, company_id=100, station_id=200, video_id=14708948)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                planner.write_plan_to_local_state(store, plan)
                batch = store.get_batch("batch-1")
                outbox = store.next_outbox(limit=20)
            finally:
                store.close()

        self.assertEqual(batch["status"], "PLANNED")
        self.assertEqual([item["endpoint"] for item in outbox].count("/api/v1/batches"), 1)
        self.assertEqual([item["endpoint"] for item in outbox].count("/api/v1/batches/batch-1/videos"), 1)
        self.assertEqual([item["endpoint"] for item in outbox].count("/api/v1/objects/upsert"), 2)


if __name__ == "__main__":
    unittest.main()
