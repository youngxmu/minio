import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from cold_backup_automation.api import create_app


class FakeRepository:
    def __init__(self):
        self.sources = []

    def upsert_source(self, payload):
        self.sources.append(payload)
        return {"sourceId": payload.source_id}

    def lookup_mapping(self, source_id, bucket, key, version_id=""):
        return {"source_id": source_id, "source_bucket": bucket, "source_key": key}


class ApiAuthTest(unittest.TestCase):
    def test_auth_disabled_when_no_api_keys_are_configured(self):
        repo = FakeRepository()
        client = TestClient(create_app(repository=repo))

        response = client.post(
            "/api/v1/sources",
            json={
                "sourceId": "oldminio1",
                "sourceName": "old MinIO 1",
                "endpoint": "http://old",
                "minioVersion": "RELEASE.2022-11-08T05-27-07Z",
                "serviceType": "systemd",
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_write_endpoint_requires_write_key_when_configured(self):
        repo = FakeRepository()
        with patch.dict("os.environ", {"SUCAI_META_WRITE_KEYS": "write-token"}, clear=False):
            client = TestClient(create_app(repository=repo))

        payload = {
            "sourceId": "oldminio1",
            "sourceName": "old MinIO 1",
            "endpoint": "http://old",
            "minioVersion": "RELEASE.2022-11-08T05-27-07Z",
            "serviceType": "systemd",
        }

        self.assertEqual(client.post("/api/v1/sources", json=payload).status_code, 401)
        self.assertEqual(client.post("/api/v1/sources", json=payload, headers={"Authorization": "Bearer wrong"}).status_code, 403)
        self.assertEqual(client.post("/api/v1/sources", json=payload, headers={"Authorization": "Bearer write-token"}).status_code, 200)

    def test_read_endpoint_accepts_read_or_write_key(self):
        repo = FakeRepository()
        with patch.dict("os.environ", {"SUCAI_META_WRITE_KEYS": "write-token", "SUCAI_META_READ_KEYS": "read-token"}, clear=False):
            client = TestClient(create_app(repository=repo))

        url = "/api/v1/mappings/lookup?sourceId=oldminio1&bucket=sucaiwang&key=a/b.mp4"

        self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(client.get(url, headers={"Authorization": "Bearer read-token"}).status_code, 200)
        self.assertEqual(client.get(url, headers={"Authorization": "Bearer write-token"}).status_code, 200)

    def test_healthz_does_not_require_api_key(self):
        with patch.dict("os.environ", {"SUCAI_META_WRITE_KEYS": "write-token"}, clear=False):
            client = TestClient(create_app(repository=FakeRepository()))

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
