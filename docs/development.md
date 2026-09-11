# Development and verification

[Documentation](README.md) · [Project overview](../README.md)

Run these commands from the repository root. The activation command below uses a POSIX shell.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                              # full suite, 100% line coverage enforced
pytest -m fuzz --no-cov             # seeded fuzz/property suites only
ruff check ton tests
ruff format --check ton tests
mypy ton                            # strict package type check
pyright ton
```

[`ton/py.typed`](../ton/py.typed) publishes the inline public API annotations. The normal test suite
builds a wheel, installs it in an isolated virtual environment, and checks typed
plugin implementations and invalid API calls from outside the checkout. Hatchling
is included in the development dependencies; this test builds and installs offline.

Enable the pre-commit gate once per clone so the CI lint + typecheck jobs
(`ruff check`, `ruff format --check`, `mypy ton`, `pyright ton`) run before
every commit and block it on failure:

```bash
git config core.hooksPath .githooks
```

Bypass in an emergency with `git commit --no-verify`.

Behavior guidelines for AI agents live in [`AGENTS.md`](../AGENTS.md); open review findings are tracked in [`TODO.md`](../TODO.md).

On Windows PowerShell, activate the environment with `.\.venv\Scripts\Activate.ps1`.
The quality commands are the same after activation.

See [architecture](architecture.md) for module boundaries and [benchmarks](benchmarks.md)
for the saved performance scripts, methodology and comparison.
