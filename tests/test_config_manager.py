import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest


class TestConfigManager(unittest.TestCase):
    def test_get_config_does_not_require_cpu_info(self) -> None:
        from mini_ai.core.config_manager import get_config

        cfg = get_config()
        self.assertIsNotNone(cfg)


if __name__ == "__main__":
    unittest.main()

