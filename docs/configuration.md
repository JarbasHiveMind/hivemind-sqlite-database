# Configuration

`SQLiteDB` accepts three constructor parameters. Defaults match the layout
`hivemind-core` expects out-of-the-box.

| Parameter | Default | Description |
|---|---|---|
| `name` | `"clients"` | Base filename (without extension). The database file is `<name>.db`. |
| `subfolder` | `"hivemind-core"` | XDG subfolder under `$XDG_DATA_HOME`. |
| `password` | `None` | When set to a non-empty string, enables AES-256 encryption via SQLCipher. Requires `pip install "hivemind-sqlite-database[cipher]"`. |

All three are passed via the `hivemind-sqlite-db-plugin` block in
`~/.config/hivemind-core/server.json`:

```json
{
  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core",
      "password": null
    }
  }
}
```

## Paths

`SQLiteDB` uses `ovos_utils.xdg_utils.xdg_data_home()` for the data root:

- If `$XDG_DATA_HOME` is set, use it.
- Otherwise, default to `~/.local/share`.

With the defaults the full path resolves to:

```
~/.local/share/hivemind-core/clients.db
```

The directory is created on first open — no manual `mkdir` needed.

### Relocating the database

Override `$XDG_DATA_HOME` per-process:

```bash
XDG_DATA_HOME=/srv/hivemind hivemind-core listen
# Resolves to /srv/hivemind/hivemind-core/clients.db
```

Or use a symlink inside `~/.local/share/hivemind-core/` pointing to the real
file.

## Encryption

Setting a non-empty `password` selects SQLCipher. The system library
and Python binding must be installed first:

```bash
# Debian/Ubuntu
sudo apt install libsqlcipher0
pip install "hivemind-sqlite-database[cipher]"
```

```json
{
  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "password": "your-strong-passphrase"
    }
  }
}
```

The password maps directly to SQLCipher's `PRAGMA key`. SQLCipher derives
an AES-256-CBC key from the passphrase via PBKDF2. Any non-empty string is
valid as a passphrase — SQLCipher stretches it internally.

**Constraints:**

- A plain (unencrypted) `.db` file cannot be opened with a key.
- An encrypted file cannot be opened without the key.
- There is no built-in re-key or passphrase-change flow.
- There is no password recovery. A lost passphrase means the data is gone.

## Multiple HiveMind instances on the same host

Give each instance distinct `name` or `subfolder` values. The plugin uses
WAL journal mode, which is safe for multi-reader single-writer access from
different processes, but `hivemind-core` is not designed for two writers on
the same file simultaneously.

## Schema version

`SQLiteDB` tracks the schema version in `PRAGMA user_version` — a built-in
SQLite slot, no sibling files. The current target version is `2`. See
[Architecture → Schema migration](architecture.md#schema-migration) for
what the migration does and how it runs.
