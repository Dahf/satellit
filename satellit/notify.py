"""Pushover-Benachrichtigung (https://pushover.net/api)."""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)
PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def send_pushover(title: str, message: str, priority: int = 0, url: str | None = None,
                  token: str | None = None, user: str | None = None) -> bool:
    token = token or os.environ.get("PUSHOVER_TOKEN", "")
    user = user or os.environ.get("PUSHOVER_USER", "")
    if not token or not user:
        log.warning("Pushover: PUSHOVER_TOKEN / PUSHOVER_USER fehlen — keine Push-Nachricht")
        return False
    payload = {"token": token, "user": user, "title": title[:250], "message": message[:1024], "priority": priority}
    if url:
        payload["url"] = url
    try:
        r = requests.post(PUSHOVER_URL, data=payload, timeout=30)
        ok = r.status_code == 200 and r.json().get("status") == 1
        if not ok:
            log.warning("Pushover-Antwort: %s %s", r.status_code, r.text[:200])
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("Pushover fehlgeschlagen: %s", exc)
        return False
