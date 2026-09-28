# Publishing AutoResearcher

This is the release checklist for testing a distribution on TestPyPI and publishing it to PyPI.
Publishing changes external state and should be done only by the package owner.

## Important: verify the distribution name

This repository is configured to publish as:

```toml
name = "autoresearcher-ai"
```

Verify this name is still available on both PyPI services before the first upload:

```text
https://pypi.org/project/autoresearcher-ai/
https://test.pypi.org/project/autoresearcher-ai/
```

The distribution name and import name differ. Users install:

```bash
python -m pip install autoresearcher-ai
```

while Python code can continue to use:

```python
from autoresearcher import AutoResearcher
```

The `src/autoresearcher` directory does not need to be renamed.

## 1. Complete the project identity

Before the first public release, replace the placeholder metadata in `pyproject.toml`:

- `authors`: the real maintainer or organization
- `project.urls.Homepage`: the repository or product page you control
- `project.urls.Issues`: the real issue tracker
- `project.name`: the verified unique distribution name

Also review `README.md`, `LICENSE`, security expectations, supported Python versions, and every
runtime dependency. Replace relative documentation links in the PyPI README with URLs that will
work on your public repository. Public PyPI packages cannot rely on private or local dependency
paths.

## 2. Select a release version

This repository currently uses version `0.1.0`. Update both locations for every release:

1. `[project].version` in `pyproject.toml`
2. `__version__` in `src/autoresearcher/__init__.py`

Add release notes to `CHANGELOG.md`. PyPI does not allow replacing a file or reusing an already
published version, so increment the version before every new upload.

Suggested early versions:

- `0.1.0` for the first alpha release
- `0.1.1` for backward-compatible fixes
- `0.2.0` for new public features or meaningful API expansion

## 3. Run the release checks

From a clean checkout and an activated development environment:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

Build into a version-specific directory so old artifacts cannot be uploaded accidentally:

```bash
python -m build --outdir dist/0.1.0
python -m twine check dist/0.1.0/*
```

Inspect the contents:

```bash
python -m zipfile --list dist/0.1.0/*.whl
tar -tzf dist/0.1.0/*.tar.gz
```

Test the wheel in a fresh virtual environment before uploading:

```bash
python3 -m venv /tmp/autoresearcher-wheel-test
source /tmp/autoresearcher-wheel-test/bin/activate
python -m pip install dist/0.1.0/*.whl
python -c "from autoresearcher import AutoResearcher; print('wheel import passed')"
autoresearcher --help
deactivate
```

Use a new temporary directory if that path already exists; do not delete an unknown directory.

## 4. Upload to TestPyPI first

TestPyPI and PyPI use separate accounts and API tokens. Register and verify an email address at
TestPyPI, then create a TestPyPI API token.

Upload only the current release artifacts:

```bash
python -m twine upload --repository testpypi dist/0.1.0/*
```

When prompted:

- Username: `__token__`
- Password: the full TestPyPI token, including its `pypi-` prefix

Do not put the token in source code, shell history, `.env`, or the repository.

Verify the uploaded artifact in a new environment. TestPyPI does not mirror all dependencies,
so install dependencies with the local wheel first, then reinstall the package from TestPyPI
without resolving dependencies:

```bash
python3 -m venv /tmp/autoresearcher-testpypi
source /tmp/autoresearcher-testpypi/bin/activate
python -m pip install dist/0.1.0/*.whl
python -m pip install --force-reinstall --no-deps \
  --index-url https://test.pypi.org/simple/ \
  your-unique-distribution-name==0.1.0
python -c "from autoresearcher import AutoResearcher; print('TestPyPI import passed')"
```

## 5. Publish to PyPI

Create and verify a separate PyPI account. For a first manual release, create an API token and
upload the exact artifacts that passed TestPyPI verification:

```bash
python -m twine upload dist/0.1.0/*
```

Confirm the release page and test installation in a clean environment:

```bash
python3 -m venv /tmp/autoresearcher-pypi-test
source /tmp/autoresearcher-pypi-test/bin/activate
python -m pip install your-unique-distribution-name==0.1.0
python -c "from autoresearcher import AutoResearcher; print('PyPI install passed')"
```

Create a source-control tag only after confirming that the published files are correct:

```bash
git tag -a v0.1.0 -m "AutoResearcher 0.1.0"
git push origin v0.1.0
```

## 6. Move to Trusted Publishing

For repeatable releases, PyPA recommends Trusted Publishing instead of a long-lived API token.
With GitHub Actions, create a protected `pypi` environment, add a release workflow, and register
that repository owner, repository, workflow filename, and environment on the PyPI project's
Publishing page. Require manual approval for the GitHub environment.

Do this only after the real repository URL and final distribution name are known. The trusted
publisher configuration must match them exactly.

## Release checklist

- [ ] Unique distribution name verified on TestPyPI and PyPI
- [ ] Author, homepage, and issue URLs replaced with real values
- [ ] README documentation links work from the PyPI project page
- [ ] Version updated in `pyproject.toml` and `src/autoresearcher/__init__.py`
- [ ] `CHANGELOG.md` updated
- [ ] Ruff, mypy, and pytest pass
- [ ] Wheel and source archive build successfully
- [ ] `twine check` passes
- [ ] Fresh-environment wheel installation passes
- [ ] TestPyPI upload and import pass
- [ ] Final artifacts uploaded to PyPI
- [ ] PyPI installation passes
- [ ] Release tag created
- [ ] API tokens stored only in an approved secret manager or replaced by Trusted Publishing

## Official references

- [Python Packaging User Guide: Packaging Python Projects](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [Python Packaging User Guide: Installing Packages](https://packaging.python.org/en/latest/tutorials/installing-packages/)
- [PyPA tool recommendations](https://packaging.python.org/en/latest/guides/tool-recommendations/)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
