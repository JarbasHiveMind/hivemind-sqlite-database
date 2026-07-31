# Operations

Backup, restore, hand-editing, and recovery for `SQLiteDB` on disk.

## Locating the files

By default:

```
~/.local/share/hivemind-core/clients.db
~/.local/share/hivemind-core/clients.db-wal   (present while DB is open)
~/.local/share/hivemind-core/clients.db-shm   (present while WAL file exists)
```

Substitute `$XDG_DATA_HOME` if set, and `<subfolder>` / `<name>` if configured
differently. See [Configuration](configuration.md).

## Backups

### Plain (unencrypted)

For a consistent snapshot, use SQLite's online backup API via the CLI:

```bash
sqlite3 ~/.local/share/hivemind-core/clients.db \
  ".backup /backup/clients.db.$(date +%F)"
```

This works even with a live `hivemind-core` process. The WAL-mode backup
stays internally consistent regardless of concurrent reads or writes.

For a quick file copy, stop the HiveMind process first and then copy all
three files:

```bash
systemctl --user stop hivemind-core
cp ~/.local/share/hivemind-core/clients.db     /backup/
cp ~/.local/share/hivemind-core/clients.db-wal /backup/ 2>/dev/null; true
cp ~/.local/share/hivemind-core/clients.db-shm /backup/ 2>/dev/null; true
systemctl --user start hivemind-core
```

### Encrypted (SQLCipher)

The `.backup` CLI command does not work with encrypted files unless you
compile the SQLCipher CLI. The safest approach is to stop the process and
copy the file:

```bash
systemctl --user stop hivemind-core
cp ~/.local/share/hivemind-core/clients.db /backup/clients.db.$(date +%F)
systemctl --user start hivemind-core
```

Keep the backup and the passphrase together (but stored separately and
securely).

## Verifying the schema version

```bash
sqlite3 ~/.local/share/hivemind-core/clients.db "PRAGMA user_version;"
# Output: 2
```

If the output is `0` or `1`, the migration has not yet run. Start
`hivemind-core` once to trigger it, or run:

```python
from hivemind_sqlite_database import SQLiteDB
db = SQLiteDB()  # migration runs automatically on __post_init__
```

## Inspecting the database

```bash
# List all clients
sqlite3 -header -column ~/.local/share/hivemind-core/clients.db \
  "SELECT client_id, name, is_admin, last_seen FROM clients;"

# Find a client by API key
sqlite3 ~/.local/share/hivemind-core/clients.db \
  "SELECT * FROM clients WHERE api_key = 'your-key';"
```

## Migration to another backend

```python
from hivemind_sqlite_database import SQLiteDB
from hivemind_plugin_manager import DatabaseFactory

src = SQLiteDB()
dst = DatabaseFactory.create("hivemind-redis-db-plugin",
                             config={"host": "127.0.0.1", "port": 6379})

for client in src:
    dst.add_item(client)
dst.commit()
```

Then update `server.json` to set `database.module` to the new plugin name and restart.

## Authoring a database backend plugin

To write a different database backend, implement `AbstractDB` from
`hivemind_plugin_manager.database`. The minimum required methods are:

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

Register it under `hivemind.database` in `pyproject.toml`:

```toml
[project.entry-points."hivemind.database"]
"my-db-plugin" = "my_package:MyDB"
```

`hivemind-core` discovers it automatically once installed.

---
[← Configuration](configuration.md) · [Home](../README.md)
