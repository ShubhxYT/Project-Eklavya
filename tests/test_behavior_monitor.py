import unittest

from behavior_monitor import BehaviorPolicy, BehaviorSample


def sample(t: float, *, enabled: bool = True, engagement: float = 0.8, boredom: float = 0.1,
           confusion: float = 0.1, frustration: float = 0.1) -> BehaviorSample:
    return BehaviorSample(
        timestamp=t,
        face_present=True,
        monitoring_enabled=enabled,
        scores={
            "engagement": engagement,
            "boredom": boredom,
            "confusion": confusion,
            "frustration": frustration,
        },
    )


class BehaviorPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BehaviorPolicy(ema_alpha=1.0)

    def test_calibration_mode_never_triggers(self) -> None:
        for t in range(20):
            self.assertIsNone(self.policy.update(sample(t, enabled=False, engagement=0.0), now=t))

    def test_short_spike_does_not_trigger(self) -> None:
        self.policy.update(sample(0, engagement=0.0), now=0)
        self.policy.update(sample(4.9, engagement=0.0), now=4.9)
        self.policy.update(sample(5.0, engagement=0.8), now=5.0)
        self.assertFalse(self.policy.concise_mode_active)

    def test_sustained_breach_triggers_once(self) -> None:
        self.policy.update(sample(0, engagement=0.0), now=0)
        event = self.policy.update(sample(5.0, engagement=0.0), now=5.0)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.reasons, ("engagement",))
        self.assertIsNone(self.policy.update(sample(7.0, engagement=0.0), now=7.0))

    def test_recovery_rearms_after_hysteresis(self) -> None:
        self.policy.update(sample(0, engagement=0.0), now=0)
        event = self.policy.update(sample(5.0, engagement=0.0), now=5.0)
        self.assertIsNotNone(event)
        for t in (6.0, 10.9, 11.0):
            self.policy.update(sample(t, engagement=0.5), now=t)
        self.assertFalse(self.policy.concise_mode_active)

    def test_cooldown_suppresses_retrigger(self) -> None:
        self.policy.update(sample(0, engagement=0.0), now=0)
        self.assertIsNotNone(self.policy.update(sample(5.0, engagement=0.0), now=5.0))
        for t in (6.0, 11.0):
            self.policy.update(sample(t, engagement=0.8), now=t)
        self.policy.update(sample(12.0, engagement=0.0), now=12.0)
        self.assertIsNone(self.policy.update(sample(20.0, engagement=0.0), now=20.0))


if __name__ == "__main__":
    unittest.main()
