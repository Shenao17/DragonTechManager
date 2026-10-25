"""Pruebas aisladas del comprobador de metadatos de releases."""

from io import BytesIO
import json
import unittest
from unittest.mock import Mock
from urllib.error import URLError

from dragontech_manager.services.updates import UpdateChecker


class UpdateCheckerTests(unittest.TestCase):
    def manifest(self, **overrides) -> bytes:
        payload = {
            "version": "0.2.0",
            "release_url": "https://updates.example.test/releases/0.2.0",
            "artifact_sha256": "a" * 64,
            "signature": "signed-manifest-placeholder",
        }
        payload.update(overrides)
        return json.dumps(payload).encode("utf-8")

    def test_unconfigured_channel_is_honest_and_does_not_make_network_call(self) -> None:
        opener = Mock()
        result = UpdateChecker(manifest_url=None, opener=opener).check("0.1.0")
        self.assertEqual(result.status, "not_configured")
        self.assertIn("no está configurado", result.message)
        opener.assert_not_called()

    def test_available_version_uses_mocked_https_manifest_and_finite_timeout(self) -> None:
        opener = Mock(return_value=BytesIO(self.manifest()))
        result = UpdateChecker("https://updates.example.test/manifest.json", opener).check("0.1.0")
        self.assertEqual(result.status, "available")
        self.assertEqual(result.latest_version, "0.2.0")
        self.assertEqual(result.release_url, "https://updates.example.test/releases/0.2.0")
        self.assertEqual(result.artifact_sha256, "a" * 64)
        opener.assert_called_once()
        self.assertEqual(opener.call_args.kwargs["timeout"], 4)

    def test_current_version_and_invalid_release_host(self) -> None:
        current_opener = Mock(return_value=BytesIO(self.manifest(version="0.1.0")))
        self.assertEqual(
            UpdateChecker("https://updates.example.test/manifest.json", current_opener)
            .check("0.1.0").status,
            "current",
        )
        invalid_opener = Mock(return_value=BytesIO(self.manifest(
            release_url="https://unrelated.example.test/release"
        )))
        self.assertEqual(
            UpdateChecker("https://updates.example.test/manifest.json", invalid_opener)
            .check("0.1.0").status,
            "error",
        )

    def test_network_failure_is_reported_without_raising(self) -> None:
        opener = Mock(side_effect=URLError("offline"))
        result = UpdateChecker("https://updates.example.test/manifest.json", opener).check("0.1.0")
        self.assertEqual(result.status, "offline")
