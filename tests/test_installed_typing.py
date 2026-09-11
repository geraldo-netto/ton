"""ARCH-036: validate typing in the actual wheel, outside the source checkout."""

import os
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd):
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "MYPYPATH"):
        environment.pop(key, None)
    return subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True)


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory):
    work = tmp_path_factory.mktemp("installed-typing")
    built = run([sys.executable, "-m", "hatchling", "build", "-t", "wheel", "-d", str(work)], ROOT)
    assert built.returncode == 0, built.stderr
    (wheel,) = work.glob("*.whl")
    environment = work / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = run(
        [
            str(interpreter),
            "-I",
            "-m",
            "pip",
            "--disable-pip-version-check",
            "install",
            "--no-index",
            "--no-deps",
            str(wheel),
        ],
        work,
    )
    assert installed.returncode == 0, installed.stderr
    imported = run([str(interpreter), "-I", "-c", "import ton; print(ton.__file__)"], work)
    assert imported.returncode == 0, imported.stderr
    assert Path(imported.stdout.strip()).is_relative_to(environment)
    for name in ("consumer.py", "invalid_consumer.py"):
        shutil.copyfile(ROOT / "tests" / "typing" / name, work / name)
    (work / "mypy.ini").write_text("[mypy]\n", encoding="utf-8")
    return work, wheel, interpreter


def typecheck(work, interpreter, filename):
    return run(
        [
            sys.executable,
            "-I",
            "-m",
            "mypy",
            "--strict",
            "--no-incremental",
            "--cache-dir",
            str(work / "mypy-cache"),
            "--config-file",
            str(work / "mypy.ini"),
            "--python-executable",
            str(interpreter),
            str(work / filename),
        ],
        work,
    )


def test_built_wheel_contains_inline_typing_marker(installed_wheel):
    """ARCH-036: source-tree annotations alone do not make an installed package typed."""
    _, wheel, _ = installed_wheel
    with zipfile.ZipFile(wheel) as archive:
        assert "ton/py.typed" in archive.namelist()


def test_installed_public_protocols_accept_typed_plugins(installed_wheel):
    work, _, interpreter = installed_wheel
    checked = typecheck(work, interpreter, "consumer.py")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    executed = run([str(interpreter), "-I", str(work / "consumer.py")], work)
    assert executed.returncode == 0, executed.stderr


def test_installed_public_api_rejects_invalid_calls(installed_wheel):
    work, _, interpreter = installed_wheel
    checked = typecheck(work, interpreter, "invalid_consumer.py")
    assert checked.returncode == 1, checked.stdout + checked.stderr
    assert "import-untyped" not in checked.stdout
    assert checked.stdout.count("error:") == 5, checked.stdout
    assert checked.stdout.count("[arg-type]") == 4, checked.stdout
    assert "[dict-item]" in checked.stdout
