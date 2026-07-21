#!/usr/bin/env python3

from __future__ import annotations

import unittest

from session_state import ProvisioningOwner, RequestTracker


class SessionStateTests(unittest.TestCase):
    def test_duplicate_active_completed_and_conflict(self) -> None:
        tracker = RequestTracker(max_completed=2)
        self.assertEqual(tracker.inspect(7, b"same")[0], "new")
        self.assertEqual(tracker.inspect(7, b"same")[0], "in_progress")
        self.assertEqual(tracker.inspect(7, b"different")[0], "conflict")
        terminal = {"terminal": True, "request_id": 7}
        tracker.complete(7, 17, terminal)
        state, cached = tracker.inspect(7, b"same")
        self.assertEqual(state, "completed")
        self.assertEqual(cached.payload, terminal)
        self.assertEqual(tracker.inspect(7, b"different")[0], "conflict")

    def test_completed_cache_is_bounded_and_expires(self) -> None:
        now = [0.0]
        tracker = RequestTracker(max_completed=2, completed_ttl=5, clock=lambda: now[0])
        for request_id in (1, 2, 3):
            tracker.inspect(request_id, str(request_id).encode())
            tracker.complete(request_id, 17, {"request_id": request_id})
        self.assertNotIn(1, tracker.completed)
        now[0] = 6.0
        tracker.expire()
        self.assertFalse(tracker.completed)

    def test_owner_is_exclusive_and_released_by_idle_or_close(self) -> None:
        now = [0.0]
        owner = ProvisioningOwner(5, clock=lambda: now[0])
        self.assertTrue(owner.claim("a"))
        self.assertFalse(owner.claim("b"))
        owner.release("a")
        self.assertTrue(owner.claim("b"))
        now[0] = 6.0
        self.assertTrue(owner.claim("a"))


if __name__ == "__main__":
    unittest.main()
