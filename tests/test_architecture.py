"""Dependency boundaries that keep contracts and infrastructure independent."""

import subprocess
import sys

import pytest


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


@pytest.mark.parametrize("module", ["_contracts", "_references", "_pipeline", "_distribution"])
def test_extension_foundations_do_not_load_catalogs(module):
    """ARCH-026: contracts/runtime foundations never depend on concrete catalogs."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import importlib, sys",
                    f"importlib.import_module('ton.{module}')",
                    "assert 'ton._registry' not in sys.modules",
                    "assert 'ton._compiler' not in sys.modules",
                    "assert not any(name.startswith('ton.generators') for name in sys.modules)",
                    "assert 'ton._pipeline' not in sys.modules"
                    if module == "_contracts"
                    else "pass",
                ]
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
