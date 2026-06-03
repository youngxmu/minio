import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(ROOT, "scripts", "dual_minio_s3bench.py")


def load_module():
    spec = importlib.util.spec_from_file_location("dual_minio_s3bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FileOperationsTest(unittest.TestCase):
    def test_file_chunks_reads_file_bytes(self):
        module = load_module()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"abcdef")
            path = f.name
        try:
            chunks = list(module.file_chunks(path, chunk_size=2))
        finally:
            os.unlink(path)

        self.assertEqual(chunks, [b"ab", b"cd", b"ef"])

    def test_put_file_object_sends_file_body_and_length(self):
        module = load_module()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"0123456789")
            path = f.name
        calls = []

        def fake_request(endpoint, method, object_path, access_key, secret_key, body_iter=None, length=None):
            body = b"".join(body_iter)
            calls.append((endpoint, method, object_path, access_key, secret_key, body, length))
            return {"ok": True, "status": 200, "seconds": 0.1, "sent": len(body), "read": 0, "error": None}

        original = module.request
        module.request = fake_request
        try:
            result = module.put_file_object("http://127.0.0.1:9000", "ak", "sk", "bucket", "prefix-", 3, path)
        finally:
            module.request = original
            os.unlink(path)

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][2], "/bucket/prefix-000003.bin")
        self.assertEqual(calls[0][5], b"0123456789")
        self.assertEqual(calls[0][6], 10)

    def test_parser_accepts_file_commands(self):
        module = load_module()
        parser = module.build_parser()

        put_args = parser.parse_args(
            [
                "put-file",
                "--endpoint",
                "http://127.0.0.1:9000",
                "--bucket",
                "b",
                "--file",
                "/tmp/input.MOV",
                "--count",
                "2",
            ]
        )
        transcode_args = parser.parse_args(
            [
                "transcode-file",
                "--src-endpoint",
                "http://127.0.0.1:9000",
                "--src-bucket",
                "raw",
                "--dst-endpoint",
                "http://127.0.0.1:9001",
                "--dst-bucket",
                "out",
                "--output-file",
                "/tmp/input.MOV",
                "--count",
                "2",
            ]
        )

        self.assertEqual(put_args.command, "put-file")
        self.assertEqual(transcode_args.command, "transcode-file")


if __name__ == "__main__":
    unittest.main()
