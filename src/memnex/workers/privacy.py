"""Privacy worker — enforces TTLs and processes queued forget requests."""
from __future__ import annotations

import asyncio

from memnex.client import Memnex
from memnex.privacy.ttl import enforce


class PrivacyWorker:
    def __init__(self, mx: Memnex, *, interval_seconds: int = 300) -> None:
        self._mx = mx
        self._interval = interval_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await enforce(self._mx._stores.warm)
            except Exception as exc:
                print(f"privacy worker error: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
