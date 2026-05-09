import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest


class TestRecoveryRetry(unittest.TestCase):
    def test_recovery_manager_retries_callable(self) -> None:
        from mini_ai.core.recovery import RecoveryManager
        from mini_ai.core.errors import ExecutionError, ErrorContext

        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("fail once")
            return "ok"

        mgr = RecoveryManager()
        err = ExecutionError(
            "execution failed",
            context=ErrorContext(operation="test", recoverable=True, suggested_action="retry"),
        )
        result = mgr.attempt_recovery(err, operation="test_op", retry=flaky, max_attempts=2)
        self.assertTrue(result.success)
        self.assertEqual(result.result, "ok")
        self.assertEqual(result.attempts, 2)


if __name__ == "__main__":
    unittest.main()

