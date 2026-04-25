"""Timezone-aware 'now' helper. Py3.12+ deprecates datetime.utcnow()."""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    # Naive UTC (no tzinfo) so equality/subtraction with stored naive
    # timestamps keeps working. We're always in UTC — no mixing.
    return datetime.now(timezone.utc).replace(tzinfo=None)
