from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from scripts import probe_nitter_fetch


class ProbeNitterFetchArgsTest(unittest.TestCase):
    def test_plain_text_flags_are_mutually_exclusive(self):
        argv = [
            "probe_nitter_fetch.py",
            "nasa",
            "5",
            "--skip-plain-text",
            "--include-plain-text",
        ]

        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as caught:
                probe_nitter_fetch._parse_args()

        self.assertEqual(caught.exception.code, 2)

    def test_skip_plain_text_flag_defaults_false(self):
        with patch.object(sys, "argv", ["probe_nitter_fetch.py", "nasa", "5"]):
            args = probe_nitter_fetch._parse_args()

        self.assertFalse(args.skip_plain_text)
        self.assertFalse(args.include_plain_text)

    def test_skip_plain_text_flag_can_be_enabled(self):
        argv = ["probe_nitter_fetch.py", "nasa", "5", "--skip-plain-text"]

        with patch.object(sys, "argv", argv):
            args = probe_nitter_fetch._parse_args()

        self.assertTrue(args.skip_plain_text)
        self.assertFalse(args.include_plain_text)


if __name__ == "__main__":
    unittest.main()
