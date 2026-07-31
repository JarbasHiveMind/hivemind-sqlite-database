# hivemind-sqlite-database

SQLite database backend for [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core).

Implements the [`hivemind-plugin-manager`](https://github.com/JarbasHiveMind/hivemind-plugin-manager)
`AbstractDB` contract on top of Python's built-in `sqlite3` module (or `sqlcipher3` when
encryption is enabled). Client records (API keys, crypto keys, access-control lists) are stored in
a local `.db` file with WAL journal mode for safe multi-reader, single-writer access.

This is the default database backend for fresh hivemind-core installations.

## Where it fits

```
hivemind-core
  └── hivemind-plugin-manager  (DatabaseFactory loads plugins by entry-point)
        └── hivemind-sqlite-database  ← this repo
              └── sqlite3 (stdlib) or sqlcipher3 (optional encryption)
```

The plugin registers under the `hivemind.database` entry-point group as
`hivemind-sqlite-db-plugin`. `hivemind-core` loads it automatically when `server.json`
sets `database.module` to this name.

## Install

```bash
pip install hivemind-sqlite-database
```

### With encryption support (SQLCipher / AES-256)

```bash
# Debian/Ubuntu — system library
sudo apt install libsqlcipher0

# Python binding
pip install "hivemind-sqlite-database[cipher]"
```

> The `sqlcipher3` wheel on PyPI ships its own `libsqlcipher` for x86_64 Linux,
> so the `apt` step may be optional on that platform. On ARM or Alpine you must
> build from source and need the system library.

## Quickstart

Add or update the `"database"` block in `~/.config/hivemind-core/server.json`:

```json
{
  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  }
}
```

Then start (or restart) hivemind-core:

```bash
hivemind-core listen
```

The database file is created automatically at
`$XDG_DATA_HOME/hivemind-core/clients.db` (typically `~/.local/share/hivemind-core/clients.db`).

### Optional encryption (SQLCipher)

```json
{
  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core",
      "password": "your-strong-passphrase"
    }
  }
}
```

> **Warning**: There is no password recovery. If you lose the passphrase the database
> is permanently unrecoverable. Back up the passphrase securely.

## Configuration reference

| Key | Default | Description |
|---|---|---|
| `name` | `"clients"` | Base filename (without extension). The database is `<name>.db`. |
| `subfolder` | `"hivemind-core"` | XDG subfolder under `$XDG_DATA_HOME`. |
| `password` | `null` | When set (non-empty string), opens the database with SQLCipher AES-256 encryption. Requires the `[cipher]` extra. |

The full path resolves to `$XDG_DATA_HOME/<subfolder>/<name>.db`,
typically `~/.local/share/hivemind-core/clients.db`.

## Schema migration

On first open after an upgrade, `SQLiteDB` runs an automatic schema migration.
Version tracking uses SQLite's built-in `PRAGMA user_version`. There are no sibling files.

The v1→v2 migration folds legacy `intent_blacklist` / `skill_blacklist` column
data into each row's `metadata` JSON field and NULLs the legacy columns.
`message_blacklist` is purged outright.

The migration is idempotent and crash-safe. The row rewrites
and the `user_version` bump happen in one transaction.

To migrate an existing installation to this backend, use hivemind-core's built-in
command:

```bash
hivemind-core migrate-db
```

## Docs

- [docs/architecture.md](docs/architecture.md): internals, WAL mode, schema, migration
- [docs/configuration.md](docs/configuration.md): full configuration reference
- [docs/operations.md](docs/operations.md): file locations, backup, encryption, authoring a plugin
