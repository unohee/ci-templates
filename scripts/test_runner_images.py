#!/usr/bin/env python3
"""Checks on `runner-images/`: every scale set directory names itself, and is indexed.

Plain unittest, no dependencies (same rule as the gates). Run: python3 scripts/test_runner_images.py

The values files are applied with `helm upgrade` from this public repository, so two
mistakes matter: a directory whose `runnerScaleSetName` names another scale set (the
upgrade lands on the wrong release), and a credential written inline instead of read
from the `arc-github-app` secret.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "runner-images"
CREDENTIAL = re.compile(
    r"github_token|github_app_private_key|-----BEGIN|\bghp_[A-Za-z0-9]{20,}|\bghs_[A-Za-z0-9]{20,}"
)


def scale_set_dirs() -> list[Path]:
    return sorted(p.parent for p in ROOT.glob("*/values.yaml"))


class RunnerImages(unittest.TestCase):
    def test_there_are_scale_sets(self) -> None:
        self.assertGreaterEqual(len(scale_set_dirs()), 9)

    def test_each_directory_names_its_own_scale_set(self) -> None:
        for d in scale_set_dirs():
            text = (d / "values.yaml").read_text()
            names = re.findall(r"^runnerScaleSetName:\s*(\S+)\s*$", text, re.M)
            with self.subTest(d.name):
                self.assertEqual(names, [d.name])

    def test_credentials_come_from_the_secret(self) -> None:
        for d in scale_set_dirs():
            text = (d / "values.yaml").read_text()
            with self.subTest(d.name):
                self.assertRegex(text, r"(?m)^githubConfigSecret:\s*arc-github-app\s*$")
                self.assertIsNone(CREDENTIAL.search(text))

    def test_every_directory_is_in_the_index(self) -> None:
        index = (ROOT / "README.md").read_text()
        for d in scale_set_dirs():
            with self.subTest(d.name):
                self.assertIn(f"`{d.name}/`", index)


if __name__ == "__main__":
    unittest.main()
