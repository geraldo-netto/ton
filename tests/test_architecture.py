"""Dependency boundaries that keep contracts and infrastructure independent."""

import subprocess
import sys


def test_json_does_not_import_generator_implementations():
    """ARCH-025: parsing a config must not load generation implementations."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import sys",
                    "from ton._json import parse_json",
                    "assert parse_json('[1, 2]') == [1, 2]",
                    "assert not any(name.startswith('ton.generators') for name in sys.modules)",
                ]
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
