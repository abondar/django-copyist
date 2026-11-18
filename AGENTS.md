# AGENTS.md

Instructions for AI coding agents that work on this repository. To *use* the library,
read `README.rst` and https://abondar.github.io/django-copyist/llms.txt instead.

## Layout

- `django_copyist/`: the package.
  - `__init__.py`: public API. Everything in `__all__` follows semantic versioning.
  - `config.py`: config dataclasses and shortcuts (`MakeCopy`, `UpdateToCopied`, ...).
  - `copyist.py`: the copy engine (`Copyist`).
  - `copy_request.py`: `CopyRequest`, `CopyResult`, `AbortReason`.
  - `checks.py`: `check_config()`. Issue codes are public: never renumber them.
  - `scaffold.py` and `management/commands/copyist_scaffold.py`: config generator.
- `example/`: Django project for tests and docs examples.
  - `demo/`: models used in the docs. Keep docs examples and `demo/tests` in sync.
  - `transport_network/`: a large real-world config.
  - `edge_cases/`: models for engine edge cases and regression tests.
  - `conftest.py`: runs `check_config()` on every config a test copies. A test that
    copies an invalid config on purpose needs `@pytest.mark.invalid_config`.
- `benchmarks/`: benchmark against django-clone. Not part of the test suite.
- `docs/source/`: Sphinx docs. `index.rst` includes `README.rst`.

## Commands

```bash
uv sync --extra dev
make lint                     # ruff check + ruff format --check
make test                     # pytest with coverage, SQLite
make docs                     # Sphinx, also writes llms.txt and llms-full.txt
POSTGRES_HOST=localhost make test   # PostgreSQL; needs a server with user/password postgres
uv run --extra dev --extra bench python -m benchmarks.run --sizes small,medium
```

## Rules

- The engine must keep a constant number of queries per tree level. Every new code path
  that reads rows by a list of ids goes through `Copyist._filter_in()` so that long lists
  are chunked. `test_query_count_does_not_grow_with_row_count` guards this.
- Build map keys only with `Copyist._key(model)`. It returns the class name or the label,
  depending on `CopyistConfig.map_keys`. Never write `__name__` or `_meta.label` as a key.
- Use `model._default_manager.db_manager(self.using)` (`Copyist._manager()`), never
  `Model.objects`.
- Every bug fix comes with a regression test in `example/edge_cases/tests/`.
- New public names go into `__all__`, `docs/source/api.rst` and `CHANGELOG.rst`.
- Run `make lint test` before you finish. CI also runs PostgreSQL 14, 15 and 18.
