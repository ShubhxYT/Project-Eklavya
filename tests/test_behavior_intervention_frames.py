import unittest

from behavior_monitor import BehaviorIntervention
from bot import behavior_intervention_frames
from grounded_tutor import BehaviorInterventionFrame
from pipecat.frames.frames import InterruptionFrame, LLMRunFrame


class FakeContext:
    def __init__(self, messages):
        self._messages = messages

    def get_messages(self):
        return self._messages


class BehaviorInterventionFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = BehaviorIntervention(("engagement",), {"engagement": 0.2})

    def test_replays_latest_user_question_after_warning(self) -> None:
        context = FakeContext([{"role": "user", "content": "What are tech cells?"}])
        frames = behavior_intervention_frames(self.event, context)
        self.assertIsInstance(frames[0], InterruptionFrame)
        self.assertIsInstance(frames[1], BehaviorInterventionFrame)
        self.assertIsInstance(frames[2], LLMRunFrame)

    def test_no_user_question_has_no_replay(self) -> None:
        frames = behavior_intervention_frames(self.event, FakeContext([]))
        self.assertEqual(len(frames), 2)


if __name__ == "__main__":
    unittest.main()
