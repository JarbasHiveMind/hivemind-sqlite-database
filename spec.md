# Spec: SQLite Database Plugin — Release Ready

## Objective
Bring `hivemind-sqlite-database` to a stable `0.1.0` release. The plugin already has a working implementation but is missing thread-safety hardening, a test suite, and CI. This spec covers the changes needed inside the `hivemind-sqlite-database` repository only: reliability fixes, a comprehensive pytest suite using in-memory SQLite, a version bump to stable, and a GitHub Actions CI workflow.

## Functional Requirements

1. `SQLiteDB.__post_init__` MUST enable WAL journal mode (`PRAGMA journal_mode=WAL`) on every new connection.
2. `SQLiteDB.__post_init__` MUST pass `check_same_thread=False` to `sqlite3.connect` so the instance is safe to call from any thread.
3. `SQLiteDB.add_item` MUST insert a new client row when the `client_id` does not already exist.
4. `SQLiteDB.add_item` MUST replace (upsert) an existing row when the `client_id` already exists.
5. `SQLiteDB.add_item` MUST return `True` on success and `False` on `sqlite3.Error`.
6. `SQLiteDB.delete_item` (inherited from `AbstractDB`) MUST retain the row in the database with `api_key` set to `"revoked"` — it MUST NOT physically delete the row.
7. `SQLiteDB.search_by_value` MUST return a list of `Client` objects whose column `key` equals `val`; MUST return `[]` on no match or on `sqlite3.Error`.
8. `SQLiteDB.__len__` MUST return the total row count including revoked entries.
9. `SQLiteDB.__iter__` MUST yield every row as a `Client` instance, including revoked entries.
10. `SQLiteDB.commit` MUST return `True` on success and `False` on `sqlite3.Error`.
11. All JSON-serialised list columns (`intent_blacklist`, `skill_blacklist`, `message_blacklist`, `allowed_types`) MUST round-trip correctly through `add_item` → `search_by_value` / `__iter__`.
12. The package version MUST be `0.1.0` with `VERSION_ALPHA = 0`.
13. A `pytest` test suite MUST exist under `tests/` and cover requirements 3–11 using an in-memory SQLite database (no file system, no external services).
14. A GitHub Actions workflow MUST run `pytest` on every push and pull-request targeting `main`.

## Non-Goals
- Migration utility from the JSON DB backend.
- Changes to `hivemind-core` default configuration (handled separately).
- Schema migrations / Alembic integration.
- Redis plugin changes.
- Multi-process locking beyond WAL mode.
- `pyproject.toml` migration (keep `setup.py`).

## Interfaces & Contracts
- `AbstractDB` (`hivemind_plugin_manager.database`) — `SQLiteDB` must satisfy all abstract methods: `add_item`, `search_by_value`, `__len__`, `__iter__`; and the concrete helpers: `delete_item`, `update_item`, `replace_item`, `commit`, `sync`.
- `Client` dataclass — all 15 fields must be persisted and restored without loss; boolean fields must remain `bool` (not `int`) after round-trip.
- Entry point — `hivemind.database` group, name `hivemind-sqlite-db-plugin`, class `hivemind_sqlite_database:SQLiteDB` (unchanged).

## Acceptance Criteria
- [ ] `pytest tests/ -v` exits 0 with no external services; all tests pass.
- [ ] A test asserts that after `delete_item(client)`, the row still exists and its `api_key == "revoked"`.
- [ ] A test asserts that `search_by_value("api_key", key)` returns the correct client after `add_item`.
- [ ] A test asserts that `search_by_value("is_admin", True)` returns only admin clients.
- [ ] A test asserts that `search_by_value("name", "ghost")` returns `[]` for a non-existent name.
- [ ] A test asserts that list fields (`intent_blacklist`, `allowed_types`) survive a full add → retrieve round-trip unchanged.
- [ ] A test asserts that `len(db) == 0` on a fresh DB and increments correctly after `add_item`.
- [ ] A test asserts that `list(db)` yields all rows including revoked ones.
- [ ] A test asserts `add_item` returns `False` when a simulated `sqlite3.Error` is raised (mock or force an error).
- [ ] `version.py` has `VERSION_BUILD = 1`, `VERSION_MINOR = 0` (or equivalent `0.1.0` string).
- [ ] GitHub Actions workflow file exists at `.github/workflows/` and references `pytest`.
- [ ] The WAL pragma is confirmed active: a test opens an in-memory DB and asserts `PRAGMA journal_mode` returns `"wal"` — or at minimum the `__post_init__` code contains the pragma call.
