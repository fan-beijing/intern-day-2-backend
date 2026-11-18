"""测试前置：在导入应用之前把配置指向临时数据库。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="ledger-test-"))
_DB_PATH = (_TMP_DIR / "test.db").as_posix()

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["SEED_USERNAME"] = "demo"
os.environ["SEED_PASSWORD"] = "test-password-123"
os.environ["SESSION_TTL_MINUTES"] = "120"
