#!/usr/bin/env python3
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import statistics
import sys
import time
import urllib.parse


MB = 1024 * 1024
REGION = "us-east-1"
SERVICE = "s3"


def parse_endpoint(endpoint):
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("endpoint must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("endpoint must include hostname")
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    host_header = parsed.netloc
    return parsed.scheme, parsed.hostname, port, host_header


def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_key, date_stamp):
    k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = sign(k_date, REGION)
    k_service = sign(k_region, SERVICE)
    return sign(k_service, "aws4_request")


def canonical_uri(path):
    return urllib.parse.quote(path, safe="/-_.~")


def auth_headers(method, endpoint, path, query, access_key, secret_key):
    _, _, _, host_header = parse_endpoint(endpoint)
    now = dt.datetime.now(dt.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = "UNSIGNED-PAYLOAD"
    headers = {
        "host": host_header,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amzdate,
    }
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_headers = (
        "host:{host}\n"
        "x-amz-content-sha256:{payload}\n"
        "x-amz-date:{date}\n"
    ).format(host=host_header, payload=payload_hash, date=amzdate)
    canonical_request = "\n".join(
        [
            method,
            canonical_uri(path),
            query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = "/".join([datestamp, REGION, SERVICE, "aws4_request"])
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amzdate,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        signing_key(secret_key, datestamp),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["Authorization"] = (
        "AWS4-HMAC-SHA256 "
        "Credential={access}/{scope}, "
        "SignedHeaders={signed}, "
        "Signature={sig}"
    ).format(
        access=access_key,
        scope=credential_scope,
        signed=signed_headers,
        sig=signature,
    )
    return headers


def new_conn(endpoint):
    scheme, host, port, _ = parse_endpoint(endpoint)
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return cls(host, port, timeout=120)


def generated_chunks(size_bytes, seed, chunk_size=MB):
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    block = (digest * ((chunk_size // len(digest)) + 1))[:chunk_size]
    remaining = size_bytes
    while remaining > 0:
        n = chunk_size if remaining >= chunk_size else remaining
        yield block[:n]
        remaining -= n


def request(endpoint, method, path, access_key, secret_key, body_iter=None, length=None):
    query = ""
    headers = auth_headers(method, endpoint, path, query, access_key, secret_key)
    if length is not None:
        headers["Content-Length"] = str(length)
    conn = new_conn(endpoint)
    started = time.monotonic()
    bytes_sent = 0
    bytes_read = 0
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.endheaders()
        if body_iter is not None:
            for chunk in body_iter:
                conn.send(chunk)
                bytes_sent += len(chunk)
        resp = conn.getresponse()
        status = resp.status
        while True:
            data = resp.read(MB)
            if not data:
                break
            bytes_read += len(data)
        elapsed = time.monotonic() - started
        return {
            "ok": 200 <= status < 300,
            "status": status,
            "seconds": elapsed,
            "sent": bytes_sent,
            "read": bytes_read,
            "error": None,
        }
    except Exception as exc:
        elapsed = time.monotonic() - started
        return {
            "ok": False,
            "status": None,
            "seconds": elapsed,
            "sent": bytes_sent,
            "read": bytes_read,
            "error": str(exc),
        }
    finally:
        conn.close()


def object_key(prefix, index):
    return "{prefix}{idx:06d}.bin".format(prefix=prefix, idx=index)


def put_object(endpoint, access_key, secret_key, bucket, prefix, index, size_mib):
    key = object_key(prefix, index)
    path = "/" + bucket + "/" + urllib.parse.quote(key, safe="/-_.~")
    size = size_mib * MB
    return request(
        endpoint,
        "PUT",
        path,
        access_key,
        secret_key,
        body_iter=generated_chunks(size, key),
        length=size,
    )


def get_object(endpoint, access_key, secret_key, bucket, prefix, index):
    key = object_key(prefix, index)
    path = "/" + bucket + "/" + urllib.parse.quote(key, safe="/-_.~")
    return request(endpoint, "GET", path, access_key, secret_key)


def make_bucket(endpoint, access_key, secret_key, bucket):
    path = "/" + bucket
    result = request(endpoint, "PUT", path, access_key, secret_key, body_iter=None, length=0)
    if result["status"] == 409:
        result["ok"] = True
    return result


def run_parallel(name, count, concurrency, func):
    started = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(func, index) for index in range(count)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    wall = time.monotonic() - started
    print_summary(name, results, wall)


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    index = int(round((pct / 100.0) * (len(values) - 1)))
    return values[index]


def print_summary(name, results, wall_seconds):
    ok = [r for r in results if r["ok"]]
    errors = [r for r in results if not r["ok"]]
    durations = [r["seconds"] for r in results]
    total_bytes = sum(r["sent"] + r["read"] for r in results)
    summary = {
        "name": name,
        "operations": len(results),
        "ok": len(ok),
        "errors": len(errors),
        "wall_seconds": round(wall_seconds, 3),
        "total_bytes": total_bytes,
        "throughput_mib_s": round(total_bytes / MB / wall_seconds, 3) if wall_seconds > 0 else 0,
        "latency_p50_s": round(statistics.median(durations), 3) if durations else None,
        "latency_p95_s": round(percentile(durations, 95), 3) if durations else None,
        "latency_p99_s": round(percentile(durations, 99), 3) if durations else None,
    }
    if errors:
        summary["sample_errors"] = errors[:5]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def get_creds(args):
    access_key = args.access_key or os.environ.get("S3_ACCESS_KEY")
    secret_key = args.secret_key or os.environ.get("S3_SECRET_KEY")
    if not access_key or not secret_key:
        raise SystemExit("missing S3 credentials; pass --access-key/--secret-key or set env")
    return access_key, secret_key


def cmd_mb(args):
    access_key, secret_key = get_creds(args)
    results = [make_bucket(args.endpoint, access_key, secret_key, bucket) for bucket in args.bucket]
    print_summary("mb", results, max(sum(r["seconds"] for r in results), 0.001))


def cmd_put(args):
    access_key, secret_key = get_creds(args)
    run_parallel(
        "put",
        args.count,
        args.concurrency,
        lambda index: put_object(
            args.endpoint,
            access_key,
            secret_key,
            args.bucket,
            args.prefix,
            index,
            args.size_mib,
        ),
    )


def cmd_get(args):
    access_key, secret_key = get_creds(args)
    run_parallel(
        "get",
        args.count,
        args.concurrency,
        lambda index: get_object(args.endpoint, access_key, secret_key, args.bucket, args.prefix, index),
    )


def cmd_transcode(args):
    access_key, secret_key = get_creds(args)

    def one(index):
        src = get_object(args.src_endpoint, access_key, secret_key, args.src_bucket, args.src_prefix, index)
        if not src["ok"]:
            return src
        dst = put_object(
            args.dst_endpoint,
            access_key,
            secret_key,
            args.dst_bucket,
            args.dst_prefix,
            index,
            args.output_size_mib,
        )
        return {
            "ok": dst["ok"],
            "status": dst["status"],
            "seconds": src["seconds"] + dst["seconds"],
            "sent": dst["sent"],
            "read": src["read"],
            "error": dst["error"],
        }

    run_parallel("transcode", args.count, args.concurrency, one)


def build_parser():
    parser = argparse.ArgumentParser(description="S3-compatible MinIO benchmark helper")
    parser.add_argument("--access-key")
    parser.add_argument("--secret-key")
    sub = parser.add_subparsers(dest="command", required=True)

    mb = sub.add_parser("mb")
    mb.add_argument("--endpoint", required=True)
    mb.add_argument("--bucket", nargs="+", required=True)
    mb.set_defaults(func=cmd_mb)

    put = sub.add_parser("put")
    put.add_argument("--endpoint", required=True)
    put.add_argument("--bucket", required=True)
    put.add_argument("--prefix", default="obj-")
    put.add_argument("--count", type=int, required=True)
    put.add_argument("--size-mib", type=int, required=True)
    put.add_argument("--concurrency", type=int, default=8)
    put.set_defaults(func=cmd_put)

    get = sub.add_parser("get")
    get.add_argument("--endpoint", required=True)
    get.add_argument("--bucket", required=True)
    get.add_argument("--prefix", default="obj-")
    get.add_argument("--count", type=int, required=True)
    get.add_argument("--concurrency", type=int, default=8)
    get.set_defaults(func=cmd_get)

    transcode = sub.add_parser("transcode")
    transcode.add_argument("--src-endpoint", required=True)
    transcode.add_argument("--src-bucket", required=True)
    transcode.add_argument("--src-prefix", default="raw-")
    transcode.add_argument("--dst-endpoint", required=True)
    transcode.add_argument("--dst-bucket", required=True)
    transcode.add_argument("--dst-prefix", default="out-")
    transcode.add_argument("--count", type=int, required=True)
    transcode.add_argument("--output-size-mib", type=int, required=True)
    transcode.add_argument("--concurrency", type=int, default=8)
    transcode.set_defaults(func=cmd_transcode)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
