import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from controle_paie.licensing import (
    ACTIVE, CLOCK_ROLLBACK, DEVELOPMENT, EXPIRED, INVALID,
    TrialManager, TrialPolicy,
)


class LicensingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = TrialPolicy(days=30, build_id="test-build", state_secret="test-secret-with-at-least-32-characters", rollback_tolerance_hours=6)
        self.start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def test_source_mode_does_not_expire(self):
        manager = TrialManager(self.root, TrialPolicy(days=0))
        status = manager.check(self.start)
        self.assertEqual(status.code, DEVELOPMENT)
        self.assertTrue(status.allowed)
        self.assertFalse(manager.state_path.exists())

    def test_clock_before_build_date_is_blocked_on_first_run(self):
        policy = TrialPolicy(days=30, build_id="future-build", build_created_utc="2026-01-10T10:00:00+00:00", state_secret=self.policy.state_secret)
        status = TrialManager(self.root, policy).check(self.start)
        self.assertEqual(status.code, CLOCK_ROLLBACK)
        self.assertFalse(status.allowed)

    def test_trial_starts_on_first_run_and_expires(self):
        manager = TrialManager(self.root, self.policy)
        first = manager.check(self.start)
        self.assertEqual(first.code, ACTIVE)
        self.assertEqual(first.days_remaining, 30)
        self.assertTrue(manager.state_path.exists())
        expired = manager.check(self.start + timedelta(days=30))
        self.assertEqual(expired.code, EXPIRED)
        self.assertFalse(expired.allowed)

    def test_small_clock_correction_is_tolerated(self):
        manager = TrialManager(self.root, self.policy)
        manager.check(self.start)
        manager.check(self.start + timedelta(days=1))
        status = manager.check(self.start + timedelta(days=1, hours=-3))
        self.assertTrue(status.allowed)

    def test_abnormal_clock_rollback_is_blocked(self):
        manager = TrialManager(self.root, self.policy)
        manager.check(self.start)
        manager.check(self.start + timedelta(days=4))
        rollback = manager.check(self.start + timedelta(days=2))
        self.assertEqual(rollback.code, CLOCK_ROLLBACK)
        self.assertFalse(rollback.allowed)

    def test_modified_state_is_rejected(self):
        manager = TrialManager(self.root, self.policy)
        manager.check(self.start)
        document = json.loads(manager.state_path.read_text(encoding="utf-8"))
        document["first_run_utc"] = (self.start + timedelta(days=20)).isoformat()
        manager.state_path.write_text(json.dumps(document), encoding="utf-8")
        status = manager.check(self.start + timedelta(days=1))
        self.assertEqual(status.code, INVALID)
        self.assertFalse(status.allowed)


if __name__ == "__main__":
    unittest.main()
