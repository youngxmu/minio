import json
from typing import Callable, Dict, Optional
from urllib import request

from .local_state import LocalStateStore


def sync_outbox(
    store: LocalStateStore,
    api_base_url: str,
    limit: int = 100,
    post_json: Optional[Callable[[str, Dict], Dict]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, int]:
    post = post_json or http_post_json
    summary = {"sent": 0, "failed": 0}
    for item in store.next_outbox(limit=limit):
        try:
            url = _join_url(api_base_url, item["endpoint"])
            response = post(url, item["payload_json"], api_key=api_key) if api_key else post(url, item["payload_json"])
            status = str(response.get("status", "200"))
            if not status.startswith("2"):
                raise RuntimeError("metadata API returned status " + status)
            store.mark_outbox_sent(item["id"], response_status=status, response_json=response.get("json"))
            summary["sent"] += 1
        except Exception as exc:
            store.mark_outbox_failed(item["id"], str(exc))
            summary["failed"] += 1
    return summary


def http_post_json(url: str, payload: Dict, api_key: Optional[str] = None) -> Dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    with request.urlopen(req, timeout=30) as response:
        raw = response.read()
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return {"status": str(response.status), "json": parsed}


def _join_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")
