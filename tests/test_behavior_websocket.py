import unittest

from fastapi.testclient import TestClient

import bot
from behavior_monitor import BehaviorSample


class FakeMonitor:
    def __init__(self):
        self.streaming = []
        self.frames = []
        self.latest_sample = BehaviorSample(
            timestamp=1.0,
            face_present=True,
            monitoring_enabled=True,
            scores={"engagement": 0.72, "boredom": 0.1, "confusion": 0.1, "frustration": 0.1},
        )

    async def set_streaming(self, enabled):
        self.streaming.append(enabled)

    async def submit_frame(self, frame):
        self.frames.append(frame)
        return True


class BehaviorWebSocketTests(unittest.TestCase):
    def test_binary_frames_are_forwarded_and_stream_resets(self):
        monitor = FakeMonitor()
        previous = bot.active_behavior_monitor
        bot.active_behavior_monitor = monitor
        try:
            with TestClient(bot.app) as client:
                with client.websocket_connect("/behavior/ws") as socket:
                    socket.send_bytes(b"jpeg-frame")
                    self.assertEqual(socket.receive_json()["engagement"], 0.72)
            self.assertEqual(monitor.streaming, [True, False])
            self.assertEqual(monitor.frames, [b"jpeg-frame"])
        finally:
            bot.active_behavior_monitor = previous


if __name__ == "__main__":
    unittest.main()
