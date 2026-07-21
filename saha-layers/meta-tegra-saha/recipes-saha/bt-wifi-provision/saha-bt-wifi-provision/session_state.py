#!/usr/bin/env python3
"""Bounded request-idempotency and provisioning-owner state."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

MAX_COMPLETED_REQUESTS = 32
COMPLETED_REQUEST_TTL = 300.0


@dataclass(frozen=True)
class CachedTerminal:
    payload_hash: bytes
    message_type: int
    payload: dict[str, object]
    completed_at: float


class RequestTracker:
    """Track active request hashes and bounded terminal tombstones."""

    def __init__(
        self,
        *,
        max_completed: int = MAX_COMPLETED_REQUESTS,
        completed_ttl: float = COMPLETED_REQUEST_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_completed = max_completed
        self.completed_ttl = completed_ttl
        self.clock = clock
        self.active: dict[int, bytes] = {}
        self.completed: OrderedDict[int, CachedTerminal] = OrderedDict()

    @staticmethod
    def payload_hash(payload: bytes) -> bytes:
        return hashlib.sha256(payload).digest()

    def expire(self) -> None:
        now = self.clock()
        while self.completed:
            request_id, terminal = next(iter(self.completed.items()))
            if now - terminal.completed_at <= self.completed_ttl:
                break
            del self.completed[request_id]

    def inspect(self, request_id: int, payload: bytes) -> tuple[str, CachedTerminal | None]:
        self.expire()
        digest = self.payload_hash(payload)
        active_digest = self.active.get(request_id)
        if active_digest is not None:
            return ("in_progress", None) if active_digest == digest else ("conflict", None)
        terminal = self.completed.get(request_id)
        if terminal is not None:
            self.completed.move_to_end(request_id)
            return ("completed", terminal) if terminal.payload_hash == digest else ("conflict", None)
        self.active[request_id] = digest
        return "new", None

    def complete(self, request_id: int, message_type: int, payload: dict[str, object]) -> None:
        digest = self.active.pop(request_id)
        self.completed[request_id] = CachedTerminal(digest, message_type, dict(payload), self.clock())
        self.completed.move_to_end(request_id)
        while len(self.completed) > self.max_completed:
            self.completed.popitem(last=False)

    def abandon(self, request_id: int) -> None:
        self.active.pop(request_id, None)

    def clear(self) -> None:
        self.active.clear()
        self.completed.clear()


class ProvisioningOwner:
    """Allow one authenticated provisioning owner at a time."""

    def __init__(self, idle_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.idle_seconds = idle_seconds
        self.clock = clock
        self.device: str | None = None
        self.last_seen = 0.0

    def _expire(self) -> None:
        if self.device is not None and self.clock() - self.last_seen > self.idle_seconds:
            self.device = None

    def claim(self, device: str) -> bool:
        self._expire()
        if self.device not in (None, device):
            return False
        self.device = device
        self.last_seen = self.clock()
        return True

    def touch(self, device: str) -> bool:
        self._expire()
        if self.device != device:
            return False
        self.last_seen = self.clock()
        return True

    def release(self, device: str) -> None:
        if self.device == device:
            self.device = None
