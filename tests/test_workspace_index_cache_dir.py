import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest


class TestWorkspaceIndexCacheDir(unittest.TestCase):
    def test_cache_dir_is_platform_appropriate(self) -> None:
        from mini_ai.core.environment import EnvironmentDetector
        from mini_ai.workspace_index import CACHE_DIR

        expected = EnvironmentDetector().get_cache_dir() / "workspace_index"
        self.assertEqual(CACHE_DIR, expected)


if __name__ == "__main__":
    unittest.main()
