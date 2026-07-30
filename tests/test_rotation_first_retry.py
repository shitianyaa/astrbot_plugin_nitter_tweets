"""Test rotation-first retry strategy."""

from __future__ import annotations

import asyncio
import unittest

from media_support.client import NitterClient


class RotationFirstRetryTest(unittest.TestCase):
    def test_rotation_first_order(self):
        """Verify instances are tried in rotation-first order: A→B→C→A→B→C."""
        client = NitterClient(
            {
                "instances": [
                    "https://a.example",
                    "https://b.example",
                    "https://c.example",
                ],
                "retry_attempts": 2,
                "retry_delay_seconds": 0,
            }
        )
        attempts = []

        def mock_fetch(*args, **kwargs):
            instance = args[0]
            attempts.append(instance)
            raise RuntimeError(f"{instance} failed")

        client._fetch_from_instance = mock_fetch

        with self.assertRaises(RuntimeError):
            asyncio.run(
                client._fetch_tweets_with_stats_from_instances(
                    "test_user",
                    10,
                    client.instances,
                    retry_attempts=2,
                )
            )

        expected = [
            "https://a.example",
            "https://b.example",
            "https://c.example",
            "https://a.example",
            "https://b.example",
            "https://c.example",
        ]
        self.assertEqual(attempts, expected)

    def test_rotation_first_success_early(self):
        """Verify retry stops when an instance succeeds."""
        client = NitterClient(
            {
                "instances": [
                    "https://a.example",
                    "https://b.example",
                    "https://c.example",
                ],
                "retry_attempts": 2,
                "retry_delay_seconds": 0,
            }
        )
        attempts = []

        def mock_fetch(*args, **kwargs):
            instance = args[0]
            attempts.append(instance)
            if instance == "https://b.example":
                from media_support.client import InstanceFetchResult

                return InstanceFetchResult(tweets=[{"id": "123"}], saw_items=True)
            raise RuntimeError(f"{instance} failed")

        client._fetch_from_instance = mock_fetch

        instance, _tweets, _ = asyncio.run(
            client._fetch_tweets_with_stats_from_instances(
                "test_user",
                10,
                client.instances,
                retry_attempts=2,
            )
        )

        self.assertEqual(instance, "https://b.example")
        self.assertEqual(attempts, ["https://a.example", "https://b.example"])

    def test_rotation_first_scheduler_mode(self):
        """Verify scheduler fetch also uses rotation-first retry."""
        client = NitterClient(
            {
                "instances": ["https://a.example", "https://b.example"],
                "retry_attempts": 2,
                "retry_delay_seconds": 0,
            }
        )
        attempts = []

        def mock_fetch_scheduler(*args, **kwargs):
            instance = args[0]
            attempts.append((instance, args[-1]))
            raise RuntimeError(f"{instance} failed")

        client._fetch_for_scheduler_from_instance = mock_fetch_scheduler

        with self.assertRaises(RuntimeError):
            asyncio.run(
                client._fetch_tweets_for_scheduler_from_instances(
                    "test_user",
                    None,
                    client.instances,
                    retry_attempts=2,
                    filter_reposts=False,
                )
            )

        expected = [
            ("https://a.example", False),
            ("https://b.example", False),
            ("https://a.example", False),
            ("https://b.example", False),
        ]
        self.assertEqual(attempts, expected)


if __name__ == "__main__":
    unittest.main()
