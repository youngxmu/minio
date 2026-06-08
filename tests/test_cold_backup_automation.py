import os
import re
import unittest

from cold_backup_automation.config import (
    ColdTargetConfig,
    default_max_migratable_bytes,
    validate_cold_target_config,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEMA = os.path.join(ROOT, "db", "sucai_meta_schema.sql")


def read_schema():
    with open(SCHEMA, "r", encoding="utf-8") as f:
        return f.read()


class SucaiMetaSchemaTest(unittest.TestCase):
    def test_database_name_is_sucai_meta(self):
        schema = read_schema()
        self.assertIn("CREATE DATABASE IF NOT EXISTS sucai_meta", schema)
        self.assertIn("USE sucai_meta", schema)

    def test_all_tables_use_meta_prefix(self):
        schema = read_schema()
        tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", schema)
        self.assertGreater(len(tables), 0)
        self.assertTrue(all(table.startswith("meta_") for table in tables))

    def test_video_identity_unique_key_includes_company_station_video(self):
        schema = read_schema()
        expected = "UNIQUE KEY uk_meta_video_identity (source_id, company_id, station_id, video_id)"
        self.assertIn(expected, schema)

    def test_object_mapping_unique_keys_include_company_station_video(self):
        schema = read_schema()
        self.assertIn(
            "UNIQUE KEY uk_meta_mapping_business_role "
            "(source_id, company_id, station_id, video_id, file_role, source_bucket, source_key_sha256, source_version_id)",
            schema,
        )


class CapacityConfigTest(unittest.TestCase):
    def test_default_max_migratable_bytes_uses_half_of_usable_capacity(self):
        self.assertEqual(default_max_migratable_bytes(1_000), 500)

    def test_requested_max_cannot_exceed_half_of_usable_capacity(self):
        self.assertEqual(default_max_migratable_bytes(1_000, requested_max_bytes=900), 500)
        self.assertEqual(default_max_migratable_bytes(1_000, requested_max_bytes=300), 300)

    def test_validate_cold_target_config_requires_core_fields(self):
        config = ColdTargetConfig(
            target_id="newminio1",
            endpoint="http://127.0.0.1:9000",
            cold_bucket="tier-oldminio1-sucaiwang",
            cold_prefix="oldminio1/sucaiwang/",
            tier_name="COLD_OLDMINIO1_SUCAIWANG",
            minio_version="RELEASE.2022-11-08T05-27-07Z",
            usable_free_bytes=10_000,
        )
        validate_cold_target_config(config)

    def test_validate_cold_target_config_rejects_missing_required_fields(self):
        config = ColdTargetConfig(
            target_id="",
            endpoint="http://127.0.0.1:9000",
            cold_bucket="tier-oldminio1-sucaiwang",
            cold_prefix="oldminio1/sucaiwang/",
            tier_name="COLD_OLDMINIO1_SUCAIWANG",
            minio_version="RELEASE.2022-11-08T05-27-07Z",
            usable_free_bytes=10_000,
        )
        with self.assertRaisesRegex(ValueError, "target_id"):
            validate_cold_target_config(config)


if __name__ == "__main__":
    unittest.main()
