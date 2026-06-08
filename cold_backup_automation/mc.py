from typing import Iterable, List


class McCommandBuilder:
    def __init__(self, mc_binary: str = "mc"):
        self.mc_binary = mc_binary

    def add_minio_tier(
        self,
        source_alias: str,
        tier_name: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        prefix: str,
        storage_class: str = "STANDARD",
    ) -> List[str]:
        return [
            self.mc_binary,
            "ilm",
            "tier",
            "add",
            "minio",
            source_alias,
            tier_name,
            "--endpoint",
            endpoint,
            "--access-key",
            access_key,
            "--secret-key",
            secret_key,
            "--bucket",
            bucket,
            "--prefix",
            prefix,
            "--storage-class",
            storage_class,
        ]

    def add_lifecycle_rule(self, source_alias: str, bucket: str, prefix: str, tier_name: str) -> List[str]:
        return [
            self.mc_binary,
            "ilm",
            "rule",
            "add",
            self._bucket_ref(source_alias, bucket),
            "--prefix",
            prefix,
            "--transition-days",
            "0",
            "--transition-tier",
            tier_name,
        ]

    def remove_lifecycle_rule(self, source_alias: str, bucket: str, rule_id: str) -> List[str]:
        return [
            self.mc_binary,
            "ilm",
            "rule",
            "rm",
            self._bucket_ref(source_alias, bucket),
            "--id",
            rule_id,
        ]

    def export_lifecycle_rules(self, source_alias: str, bucket: str) -> List[str]:
        return [self.mc_binary, "ilm", "rule", "export", self._bucket_ref(source_alias, bucket)]

    def make_bucket(self, alias: str, bucket: str) -> List[str]:
        return [self.mc_binary, "mb", "-p", self._bucket_ref(alias, bucket)]

    def anonymous_download(self, alias: str, bucket: str) -> List[str]:
        return [self.mc_binary, "anonymous", "set", "download", self._bucket_ref(alias, bucket)]

    def cp(self, local_path: str, alias: str, bucket: str, key: str) -> List[str]:
        return [self.mc_binary, "cp", "--quiet", local_path, self._object_ref(alias, bucket, key)]

    def rm(self, alias: str, bucket: str, key: str) -> List[str]:
        return [self.mc_binary, "rm", self._object_ref(alias, bucket, key)]

    def stat_json(self, source_alias: str, bucket: str, key: str) -> List[str]:
        return [self.mc_binary, "stat", "--json", self._object_ref(source_alias, bucket, key)]

    def list_recursive_json(self, alias: str, bucket: str, prefix: str) -> List[str]:
        return [self.mc_binary, "ls", "--recursive", "--json", self._object_ref(alias, bucket, prefix)]

    def cat(self, alias: str, bucket: str, key: str) -> List[str]:
        return [self.mc_binary, "cat", self._object_ref(alias, bucket, key)]

    def display_command(self, command: Iterable[str]) -> str:
        redacted = []
        mask_next = False
        for part in command:
            if mask_next:
                redacted.append("<redacted>")
                mask_next = False
                continue
            redacted.append(part)
            if part in ("--access-key", "--secret-key"):
                mask_next = True
        return " ".join(redacted)

    def _bucket_ref(self, alias: str, bucket: str) -> str:
        return alias.rstrip("/") + "/" + bucket.strip("/")

    def _object_ref(self, alias: str, bucket: str, key: str) -> str:
        return self._bucket_ref(alias, bucket) + "/" + key.lstrip("/")
