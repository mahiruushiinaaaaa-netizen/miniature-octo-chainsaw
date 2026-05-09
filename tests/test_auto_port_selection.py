import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import socket
import unittest


class TestAutoPortSelection(unittest.TestCase):
    def test_pick_free_port_returns_bindable_port(self) -> None:
        from mini_ai.cli_v2 import _pick_free_port, _port_is_available

        host = "127.0.0.1"
        port = _pick_free_port(host)
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        self.assertTrue(_port_is_available(host, port))

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))


if __name__ == "__main__":
    unittest.main()

