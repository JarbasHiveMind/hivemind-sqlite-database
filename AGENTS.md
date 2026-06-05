# AGENTS.md

SQLite (and optional SQLCipher-encrypted) `AbstractDB` backend plugin for hivemind-core, storing HiveMind client records (API keys, crypto keys, ACLs).

## Setup

```bash
pip install -e .
# encrypted-database support (SQLCipher / AES-256):
pip install -e ".[cipher]"   # needs libsqlcipher system lib (apt install libsqlcipher-dev)
```

## Test

```bash
pytest tests/
```

Single suite lives in `tests/test_sqlitedb.py`. The repo's own `tests.yml` runs it with `-p no:ovoscope` and exercises both the plain and the SQLCipher path. Cipher tests need `libsqlcipher-dev` installed.

## Lint/Typecheck

Ruff, via the shared `lint.yml` workflow (`ruff: true`, no pre-commit config present). No typecheck configured.

## Layout

- `hivemind_sqlite_database/__init__.py` — the entire plugin: `SQLiteDB` dataclass extending `AbstractDB`. Schema creation, `PRAGMA user_version` migration (v1→v2 folds legacy `intent_blacklist`/`skill_blacklist` columns into `Client.metadata`), and CRUD (`add_item`, `search_by_value`, `get_client_by_id`, `__iter__`, `__len__`, `commit`).
- `hivemind_sqlite_database/version.py` — version constants (do not edit).
- `tests/test_sqlitedb.py` — full behavioural suite.

Entry-point group: `hivemind.database` → `hivemind-sqlite-db-plugin = hivemind_sqlite_database:SQLiteDB`. Discovered by `hivemind-plugin-manager`; selected in hivemind-core config under `database.module`.

## Conventions

- Branches: `dev` (work) and `master` (stable). NEVER `main`.
- Never edit `version.py`; gh-automations bumps semver from conventional-commit prefixes (`feat:`/`fix:`/`feat!:`).
- New repos private by default.
- Commit identity: JarbasAi <jarbasai@mailfence.com>.
- Reference `OpenVoiceOS/gh-automations` reusable workflows at `@dev`.
- No Neon / `neon-*` references.
- No meta-commentary (no history, no dates) in code, docs, commits, or PRs — describe current state only.
- CI is provided by OpenVoiceOS/gh-automations.

## Gotchas

- `_VALID_COLUMNS` allowlist gates `search_by_value` keys; SQL column name is interpolated only after passing that frozenset (issue #1 tracks an SQL-security review).
- Legacy `intent_blacklist`/`skill_blacklist`/`message_blacklist` columns remain in the table but are NULLed on write; canonical data lives in `metadata` JSON. `message_blacklist` is purged entirely (not part of `Client`).
- `migrate()` guards on `getattr(AbstractDB, "SCHEMA_VERSION", 1)` so it tolerates older hivemind-plugin-manager that predates the constant — do not assume the attribute exists.
- WAL journal mode is enabled for both plain and encrypted DBs; `check_same_thread=False` with a `threading.Lock` guarding writes.
- Encrypted and plaintext databases are not interchangeable and there is no migration between them; lost passphrase = unrecoverable data.
- `tests.yml` is a repo-local workflow separate from the shared build-tests; both run the same suite.
