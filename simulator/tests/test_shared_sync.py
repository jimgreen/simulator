"""守卫 simulator 与 trainee 共享源码层零漂移。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_shared.py"


class SharedSyncGuardTests(unittest.TestCase):
    @unittest.skipUnless(SYNC_SCRIPT.is_file(), "仅在完整仓库结构下执行双端同步校验")
    def test_shared_codebase_has_zero_drift(self):
        result = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
