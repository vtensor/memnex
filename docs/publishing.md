# Publishing to PyPI

This document covers how Memnex is published as a Python package. It is for **maintainers**, not tenants or operators.

## What goes into the wheel

The wheel is built from `pyproject.toml`. The relevant sections:

| Field | Purpose |
|---|---|
| `[project] name` | The PyPI package name (`memnex`). Must be unique on PyPI. |
| `[project] version` | The release version. SemVer. Update before every release. |
| `[project] description` | One-line summary shown in `pip search` and on the PyPI page. |
| `[project] readme` | Path to the long description. Currently `README.md` — its content becomes the PyPI page body. |
| `[project] license` | SPDX identifier (`Apache-2.0`). Must match the `LICENSE` file at the repo root. |
| `[project] authors` | Author / maintainer info shown on PyPI. |
| `[project] requires-python` | Minimum Python (`>=3.11`). |
| `[project] dependencies` | Hard runtime deps (Pydantic, Click, phonenumbers, anyio, rapidfuzz, dateutil). |
| `[project.optional-dependencies]` | Extras (`postgres`, `redis`, `qdrant`, `embeddings-google`, `mcp`, etc.). Users opt in with `pip install memnex[postgres,redis]`. |
| `[project.scripts] memnex` | The `memnex` CLI entry point — wires `memnex.cli.main:cli` to a console script. |
| `[project.urls]` | Homepage / Issues / Documentation links shown on PyPI. |
| `[tool.hatch.build.targets.wheel] packages` | Tells Hatch what to ship in the wheel: `["src/memnex"]`. Includes all Python files plus non-Python assets (SQL migrations, eval JSON datasets) that live inside the package tree. |

### What does NOT go into the wheel

- `tests/` — not in the package tree, not shipped.
- `docs/` — not shipped to PyPI; users read docs on GitHub.
- `Dockerfile`, `docker-compose*.yml` — not shipped; only relevant in the source repo.
- `CLAUDE.md` — internal contributor guidance.
- `.github/`, `.gitignore`, `.env.example` — repo-only.
- `dist/`, `build/`, `__pycache__/`, `.venv/` — build artefacts, never ship.

The sdist (`*.tar.gz`) ships everything the wheel ships **plus** the `pyproject.toml` and `LICENSE`. PyPI requires the sdist for full reproducibility; users mostly install the wheel.

## Pre-flight checklist

Before publishing a new version:

1. **All tests pass.**
   ```bash
   pytest -q
   ```
2. **Lint and types are clean.**
   ```bash
   ruff check .
   mypy src
   ```
3. **`pyproject.toml` version bumped.** Use SemVer:
   - `0.1.0 -> 0.1.1` for bug fixes
   - `0.1.0 -> 0.2.0` for new features that don't break existing usage
   - `0.1.0 -> 1.0.0` for the first stable / breaking release
4. **`CHANGELOG.md` has a section for the new version.** Move items from `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`.
5. **README is current.** It becomes the PyPI page body; broken links and stale examples are visible to everyone.
6. **No secrets in code.** Grep for `MEMNEX_AUDIT_KEY`, API keys, anything `xxx`.

## Build the artefacts

```bash
# Clean any previous build output first.
rm -rf dist build *.egg-info

# Build sdist + wheel into dist/
pip install --upgrade build
python -m build
```

This produces:

```
dist/memnex-X.Y.Z.tar.gz          # source distribution
dist/memnex-X.Y.Z-py3-none-any.whl # built wheel
```

## Validate before uploading

```bash
pip install --upgrade twine
twine check dist/*
```

This catches RST/markdown rendering issues, missing `long_description`, malformed metadata.

Then **smoke-test the wheel in a clean venv** — this is the single most important step before publishing. Editable installs (`pip install -e .`) hide many real packaging bugs.

```bash
# In a separate scratch directory
python -m venv /tmp/memnex_check
/tmp/memnex_check/bin/pip install /path/to/dist/memnex-X.Y.Z-py3-none-any.whl
/tmp/memnex_check/bin/memnex --version
/tmp/memnex_check/bin/python -c "
import asyncio
from memnex import Memnex, MemnexConfig

async def main():
    mx = await Memnex.create(config=MemnexConfig(tenant_id='t_smoke'))
    result = await mx.user_write(
        user_id='u1', channel='voice',
        facts=[{'fact': 'Smoke test', 'type': 'profile', 'entities': []}],
    )
    print('OK:', len(result), 'memory written')
    await mx.close()

asyncio.run(main())
"
```

Real packaging bugs caught by this step in the past:
- Duplicate file entries in the wheel from a redundant `[tool.hatch.build.targets.wheel.force-include]` block.
- Missing SQL migration files because they weren't under the package tree.
- CLI entry point pointing at an internal symbol that wasn't re-exported.
- `__init__.py` re-exports working in editable mode but failing in installed mode due to circular imports.

## Publish

### Option 1 — Manual upload (first release / one-off)

```bash
# Test PyPI first (recommended for a first release)
twine upload --repository testpypi dist/*

# Real PyPI
twine upload dist/*
```

You'll be prompted for a username (`__token__`) and an API token. Generate the token at <https://pypi.org/manage/account/token/> with scope limited to the `memnex` project.

### Option 2 — Trusted publishing via GitHub Actions (recommended for ongoing releases)

Trusted publishing replaces the long-lived API token with short-lived OIDC credentials minted by GitHub. Set up once:

1. On PyPI: <https://pypi.org/manage/project/memnex/settings/publishing/> → "Add a new publisher" → fill in repo owner, repo name, workflow filename (`release.yml`), environment name (`pypi`).
2. In the repo, create `.github/workflows/release.yml`:

   ```yaml
   name: release
   on:
     push:
       tags: ["v*"]
   jobs:
     publish:
       runs-on: ubuntu-latest
       environment: pypi
       permissions:
         id-token: write     # for trusted publishing
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.12" }
         - run: pip install build
         - run: python -m build
         - uses: pypa/gh-action-pypi-publish@release/v1
   ```

3. To publish: bump the version, update CHANGELOG, commit, then `git tag v0.1.1 && git push --tags`. The workflow runs on tag push and uploads to PyPI.

This is what google/jax, anthropic/anthropic-sdk-python, and most modern Python OSS projects use.

## After publishing

1. **Verify on PyPI**: <https://pypi.org/project/memnex/X.Y.Z/> renders correctly and shows the README body.
2. **Verify install works from PyPI** (not from local dist):
   ```bash
   pip install --no-cache-dir memnex==X.Y.Z
   memnex --version
   ```
3. **Tag the release on GitHub** (if you used the manual path; trusted publishing already does this).
4. **Announce.** A short post linking the GitHub release notes is enough.

## Yanking a bad release

If you ship a release with a serious bug:

```bash
twine yank --reason "Critical bug in conflict resolver" memnex==X.Y.Z
```

Yanking *hides* the version from `pip install memnex` (won't be selected) but doesn't delete it — anyone with the version pinned can still install it. Then publish a fixed version (`X.Y.Z+1`).

Do not delete versions from PyPI. Once you yank, leave it yanked.
