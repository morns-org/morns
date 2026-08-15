from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


class HttpObservationSink:
    """Deliver normalized observations to a MORNs server with bounded retries."""

    def __init__(self, url: str, token: str, retries: int = 5):
        self.url = f"{url.rstrip('/')}/api/v1/ingest"
        self.token = token
        self.retries = retries

    def add(self, observation: dict[str, Any]) -> int:
        payload = json.dumps(observation, separators=(",", ":"), default=str).encode()
        request = urllib.request.Request(
            self.url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "MORNs-Collector/0.1",
            },
        )
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    result = json.load(response)
                    return int(result["id"])
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    raise RuntimeError(f"MORNs ingest rejected the observation ({exc.code})") from exc
                last_error: Exception = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            delay = min(2**attempt, 16)
            log.warning("Ingest unavailable; retrying in %ss", delay)
            time.sleep(delay)
        raise RuntimeError("MORNs ingest unavailable after retries") from last_error
