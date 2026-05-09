import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest


class TestCommandRouterNonCoding(unittest.TestCase):
    def test_play_request_does_not_invoke_agent(self) -> None:
        from mini_ai.commands import CommandRouter
        from mini_ai.config import Config

        cfg = Config()
        router = CommandRouter(cfg)

        def _boom(_: str) -> None:
            raise AssertionError("run_agent should not be called for play requests")

        router.run_agent = _boom  # type: ignore[method-assign]
        self.assertTrue(router.handle("play panaginip by nicole"))


if __name__ == "__main__":
    unittest.main()

