# Plan: SQLite Database Plugin — Release Ready

## Steps

1. Fix thread-safety: add `check_same_thread=False` and WAL mode to `__post_init__`
2. Create `tests/` directory with `test_sqlitedb.py` — full pytest suite using `:memory:`
3. Bump version to `0.1.0` in `version.py`
4. Add `.gitignore`
5. Add GitHub Actions CI workflow (`.github/workflows/tests.yml`)
