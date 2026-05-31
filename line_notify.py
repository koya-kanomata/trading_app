from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def send_line_notify(token: str, to: str, message: str) -> tuple[int, str]:
    # Keep message under common LINE text limits.
    text = message[:4500]
    payload = json.dumps(
        {
            "to": to,
            "messages": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = Request("https://api.line.me/v2/bot/message/push", data=payload, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")

    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except URLError as exc:
        raise RuntimeError(f"LINE Messaging API request failed: {exc.reason}") from exc