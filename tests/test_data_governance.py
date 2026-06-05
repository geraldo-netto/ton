"""Repository-level data governance guards."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_OR_SECRET_RE = re.compile(
    rb"/home/|/backups/|API[_-]?KEY\s*[=:]|SECRET\s*[=:]|TOKEN\s*[=:]|"
    rb"PASSWORD\s*[=:]|PRIVATE KEY|BEGIN RSA|BEGIN OPENSSH"
)


def test_tracked_text_files_do_not_contain_private_paths_or_secrets() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    offenders: list[str] = []
    for relative in result.stdout.splitlines():
        path = REPO_ROOT / relative
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        if PRIVATE_OR_SECRET_RE.search(data):
            offenders.append(relative)
    assert offenders == []
