import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cold_backup_automation.local_state import LocalStateStore
from cold_backup_automation.small_file_smoke import ShellMcRunner, SmallFileSmokeConfig, SmallFileSmokeRunner, _extract_rule_ids


class FakeMcRunner:
    def __init__(self, tier_name):
        self.tier_name = tier_name
        self.calls = []
        self.source_bytes = {}
        self.delete_issued = False

    def run(self, command, input_bytes=None):
        self.calls.append(command)
        if command[1:3] == ["cp", "--quiet"]:
            local_path = command[3]
            remote_ref = command[4]
            with open(local_path, "rb") as f:
                self.source_bytes[remote_ref] = f.read()
            return ""
        if command[1:3] == ["stat", "--json"]:
            return json.dumps({"metadata": {"X-Amz-Storage-Class": self.tier_name}})
        if command[1:4] == ["ls", "--recursive", "--json"]:
            return "\n".join(
                [
                    json.dumps({"type": "file", "key": "verify-cold-object", "size": 1024}),
                    json.dumps({"type": "file", "key": "delete-cold-object", "size": 1024}),
                ]
            )
        if command[1] == "cat" and command[2].endswith("verify-cold-object"):
            return self._source_bytes("verify.bin")
        if command[1] == "cat" and command[2].endswith("delete-cold-object"):
            return self._source_bytes("delete.bin")
        if command[1] == "rm":
            self.delete_issued = True
            return ""
        if command[1:4] == ["ilm", "rule", "export"]:
            return json.dumps(
                {
                    "Rules": [
                        {
                            "ID": "rule-1",
                            "Filter": {"Prefix": "smoke/batch-1/"},
                            "Transition": {"StorageClass": self.tier_name},
                        }
                    ]
                }
            )
        return ""

    def _source_bytes(self, suffix):
        for key, value in self.source_bytes.items():
            if key.endswith(suffix):
                return value
        raise AssertionError("missing source bytes for " + suffix)


class SmallFileSmokeTest(unittest.TestCase):
    def test_small_file_smoke_transitions_maps_and_deletes(self):
        tier_name = "COLD_TEST"
        fake_runner = FakeMcRunner(tier_name)

        def fake_http_code(url):
            if "delete.bin" in url and fake_runner.delete_issued:
                return "404"
            if "delete-cold-object" in url and fake_runner.delete_issued:
                return "404"
            return "206"

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalStateStore(os.path.join(tmpdir, "state.sqlite3"))
            store.initialize()
            try:
                result = SmallFileSmokeRunner(
                    config=SmallFileSmokeConfig(
                        batch_id="batch-1",
                        source_id="oldminio1",
                        source_alias="old1",
                        source_endpoint="http://old",
                        source_bucket="sucaiwang",
                        source_prefix="smoke/batch-1",
                        target_id="newminio1",
                        cold_alias="cold1",
                        cold_endpoint="http://cold",
                        cold_bucket="tier-bucket",
                        cold_prefix="cold-prefix/",
                        tier_name=tier_name,
                        cold_access_key="ak",
                        cold_secret_key="sk",
                        work_dir=tmpdir,
                        file_size_bytes=1024,
                        poll_interval_seconds=0,
                        timeout_seconds=1,
                    ),
                    mc_runner=fake_runner,
                    http_code=fake_http_code,
                    state_store=store,
                ).run()
                outbox = store.next_outbox(limit=20)
            finally:
                store.close()

        endpoints = [item["endpoint"] for item in outbox]
        self.assertEqual(result["transition"], "OK")
        self.assertEqual(result["deleteSourceFinalCode"], "404")
        self.assertEqual(result["deleteColdFinalCode"], "404")
        self.assertEqual(endpoints.count("/api/v1/mappings/upsert"), 2)
        self.assertTrue(any(call[1:4] == ["ilm", "rule", "add"] for call in fake_runner.calls))
        self.assertTrue(any(call[1:4] == ["ilm", "rule", "rm"] for call in fake_runner.calls))

    def test_extract_rule_ids_accepts_xml_lifecycle_export(self):
        raw = """<LifecycleConfiguration>
          <Rule>
            <ID>keep-this-rule</ID>
            <Filter><Prefix>smoke/batch-1/</Prefix></Filter>
            <Transition><StorageClass>COLD_TEST</StorageClass></Transition>
          </Rule>
          <Rule>
            <ID>other-rule</ID>
            <Filter><Prefix>other/</Prefix></Filter>
            <Transition><StorageClass>COLD_TEST</StorageClass></Transition>
          </Rule>
        </LifecycleConfiguration>"""

        self.assertEqual(_extract_rule_ids(raw, "smoke/batch-1/", "COLD_TEST"), ["keep-this-rule"])

    def test_shell_runner_redacts_credentials_on_failure(self):
        command = ["mc", "ilm", "tier", "add", "--access-key", "real-ak", "--secret-key", "real-secret"]

        def fail_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, command, stderr=b"boom")

        with patch("subprocess.run", fail_run):
            with self.assertRaises(RuntimeError) as ctx:
                ShellMcRunner().run(command)

        message = str(ctx.exception)
        self.assertNotIn("real-ak", message)
        self.assertNotIn("real-secret", message)
        self.assertIn("<redacted>", message)


if __name__ == "__main__":
    unittest.main()
