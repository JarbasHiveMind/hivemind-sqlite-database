# Architecture

## Class hierarchy

```
hivemind_plugin_manager.database.AbstractDB   (abstract)
        │
        └─ hivemind_sqlite_database.SQLiteDB
                │
                └─ sqlite3.Connection (stdlib) or sqlcipher3.Connection (when password is set)
```

`SQLiteDB` is a thin adapter: it maps `AbstractDB`'s CRUD contract to a
single `clients` table in a local SQLite file.

## On-disk layout

One file per database under the XDG path (`$XDG_DATA_HOME/<subfolder>/`):

| File | Purpose |
|---|---|
| `<name>.db` | The SQLite database. Contains the `clients` table. |
| `<name>.db-wal` | Write-Ahead Log (WAL) journal. Present while the database is open or has unflushed writes. |
| `<name>.db-shm` | WAL shared memory index. Present alongside the WAL file. |

WAL journal mode is set on every open (`PRAGMA journal_mode=WAL`). This
allows multiple readers to proceed concurrently with a single writer without
blocking each other.

## Table schema

```sql
CREATE TABLE IF NOT EXISTS clients (
    client_id      INTEGER PRIMARY KEY,
    api_key        VARCHAR(255) NOT NULL,
    name           VARCHAR(255),
    description    VARCHAR(255),
    is_admin       BOOLEAN DEFAULT FALSE,
    last_seen      REAL    DEFAULT -1,
    intent_blacklist  TEXT,   -- legacy column, NULLed after v2 migration
    skill_blacklist   TEXT,   -- legacy column, NULLed after v2 migration
    message_blacklist TEXT,   -- legacy column, NULLed after v2 migration
    allowed_types  TEXT,
    crypto_key     VARCHAR(16),
    password       TEXT,
    can_broadcast  BOOLEAN DEFAULT TRUE,
    can_escalate   BOOLEAN DEFAULT TRUE,
    can_propagate  BOOLEAN DEFAULT TRUE,
    metadata       TEXT
);
```

The legacy `intent_blacklist`, `skill_blacklist`, and `message_blacklist`
columns remain in the schema for backward compatibility with older readers
but are NULLed on every write after the v2 schema migration. The canonical
data for blacklists lives in the JSON `metadata` column.

`allowed_types` and `metadata` are stored as JSON strings and
deserialised with `json.loads` on read.

## Schema migration

`SQLiteDB` tracks its on-disk schema version in `PRAGMA user_version` — a
signed integer slot built into every SQLite file, reserved exactly for
application-level versioning. No sibling files.

On every `__post_init__`, `_maybe_migrate()` reads `user_version` and
compares it to `AbstractDB.SCHEMA_VERSION` (defaults to `1` if the
attribute is absent on older HPM). If the stored version is lower, it calls
`_migrate_locked()` and bumps `user_version` in the **same transaction**,
so a crash never leaves the DB at "migrated rows but stale sentinel" or vice
versa.

### v1 → v2

For each row:

- `intent_blacklist` and `skill_blacklist` column values are folded into
  the row's `metadata` JSON dict via `setdefault` — explicit `metadata`
  values are never clobbered.
- `message_blacklist` is purged outright (top-level column and any
  pre-existing `metadata["message_blacklist"]`).
- All three legacy columns are NULLed.

The operation is idempotent: if a row has NULL legacy columns or
`metadata` already contains the canonical values, the row is unchanged.

## Thread safety

`SQLiteDB` connects with `check_same_thread=False` and protects writes
with a `threading.Lock` (`_write_lock`). All `INSERT`, `UPDATE`, and
schema mutations acquire the lock before entering the `with self.conn`
transaction context. Reads (`SELECT`, `PRAGMA table_info`) do not acquire
the lock — SQLite's WAL mode allows concurrent readers.

For multi-process concurrency (e.g. two `hivemind-core` processes on the
same file), WAL mode provides safe concurrent reads and SQLite's built-in
writer-lock serialises writes. However, `hivemind-core` does not design for
multi-process writes to the same DB — use Redis if you need that.

## Encryption (SQLCipher)

When `password` is a non-empty string, `SQLiteDB` opens the file via
`sqlcipher3` instead of the standard `sqlite3` module and issues
`PRAGMA key='<password>'` immediately after opening the connection.

The encryption is transparent to all methods — `add_item`, `search_by_value`,
and `__iter__` work identically whether the file is encrypted or not.

An encrypted file is **not** a standard SQLite file. You cannot open it with
the `sqlite3` CLI, DB Browser for SQLite, or any other tool without the key.
Conversely, a plain SQLite file cannot be opened by SQLCipher with a key.
There is no automatic migration between the two modes.

## Authoring a plugin with the same contract

To write a different database backend, implement `AbstractDB` from
`hivemind_plugin_manager.database`:

```python
from dataclasses import dataclass
from hivemind_plugin_manager.database import AbstractDB, Client
from typing import List, Union, Iterable

@dataclass
class MyDB(AbstractDB):
    name: str = "clients"
    subfolder: str = "hivemind-core"

    def add_item(self, client: Client) -> bool: ...
    def search_by_value(self, key: str, val: Union[str, bool, int, float]) -> List[Client]: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterable[Client]: ...
    def commit(self) -> bool: ...
    def migrate(self, from_version: int) -> None: ...
```

Register it under the `hivemind.database` entry-point group in
`pyproject.toml`:

```toml
[project.entry-points."hivemind.database"]
"my-db-plugin" = "my_package:MyDB"
```

`DatabaseFactory.create("my-db-plugin")` then discovers and instantiates it.
