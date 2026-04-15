# HiveMind SQLite Database

SQLite database plugin for [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core).

Implements the `AbstractDB` interface via `hivemind-plugin-manager` and stores HiveMind
client records (API keys, crypto keys, access-control lists) in a local SQLite file.

## Installation

```bash
pip install hivemind-sqlite-database
```

### With encryption support (SQLCipher)

```bash
# 1. Install the SQLCipher system library
#    Debian/Ubuntu:
sudo apt install libsqlcipher0

# 2. Install the Python binding via the optional extra
pip install "hivemind-sqlite-database[cipher]"
```

> The `sqlcipher3` wheel on PyPI ships its own libsqlcipher for x86_64 Linux, so the
> `apt` step may be optional on that platform.  On ARM or Alpine you must build from
> source and will need the system library.

## Usage

### Plain (unencrypted) database — default

```python
from hivemind_sqlite_database import SQLiteDB

db = SQLiteDB()           # stores data in XDG_DATA_HOME/hivemind-core/clients.db
```

### Encrypted database (SQLCipher / AES-256)

```python
from hivemind_sqlite_database import SQLiteDB

db = SQLiteDB(password="your-strong-passphrase")
```

Pass the same `password` every time you open the database.  The encryption is
transparent — all existing methods (`add_item`, `search_by_value`, etc.) work
identically.

> **Data-loss warning**: There is no password recovery.  If you lose the passphrase
> the database is permanently unrecoverable.  Back up your passphrase securely.

### hivemind-core configuration

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

Leave `"password"` out (or set it to `null`) to use an unencrypted database.

## Notes

- An encrypted database cannot be opened by the plain `sqlite3` CLI or stdlib module.
- A plaintext database cannot be opened as encrypted.  There is no automatic migration.
- The `password` field maps directly to SQLCipher's `PRAGMA key`.
- WAL journal mode is enabled for both encrypted and unencrypted databases.
