#!/usr/bin/env python3
"""Negative tests for corruption-detection primitives."""

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_dataset import array_is_finite, missing_paths, timestamps_match


class HealthCheckNegativeTests(unittest.TestCase):
    def test_detects_nan(self) -> None:
        self.assertFalse(array_is_finite(np.array([0.0, np.nan], dtype=np.float32)))

    def test_detects_timestamp_gap(self) -> None:
        timestamps = np.array([0.0, 0.1, 0.3], dtype=np.float32)
        self.assertFalse(timestamps_match(timestamps, fps=10))

    def test_detects_missing_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "present.json").write_text("{}\n")
            self.assertEqual(missing_paths(root, ["present.json", "missing.json"]), ["missing.json"])


if __name__ == "__main__":
    unittest.main()

