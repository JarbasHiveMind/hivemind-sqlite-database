import json
import os.path
import sqlite3
import threading
from typing import ClassVar, List, Optional, Union, Iterable

from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home

from hivemind_plugin_manager.database import Client, AbstractDB

from dataclasses import dataclass


_VALID_COLUMNS = frozenset({
    "client_id", "api_key", "name", "description", "is_admin",
    "last_seen", "intent_blacklist", "skill_blacklist", "message_blacklist",
    "allowed_types", "crypto_key", "password",
    "can_broadcast", "can_escalate", "can_propagate", "metadata",
})


@dataclass
class SQLiteDB(AbstractDB):
    """Database implementation using SQLite."""
    name: str = "clients"
    subfolder: str = "hivemind-core"
    password: Optional[str] = None

    # How long SQLite waits for a file lock held by another connection
    # before giving up with SQLITE_BUSY, in milliseconds.
    BUSY_TIMEOUT_MS: ClassVar[int] = 10000

    def __post_init__(self):
        """
        Initialize the SQLiteDB connection.

        When *password* is set the database is opened via ``sqlcipher3`` and
        encrypted with AES-256 (SQLCipher).  The system library
        ``libsqlcipher0`` must be installed and ``sqlcipher3`` must be
        available (``pip install hivemind-sqlite-database[cipher]``).

        When *password* is ``None`` (default) the standard ``sqlite3`` module
        is used and the database file is unencrypted.

        Each thread gets its own connection (see :attr:`conn`). A single
        shared connection is not usable from several threads at once: the
        transaction state belongs to the connection, so one thread's
        ``COMMIT`` ends another thread's transaction and resets its
        in-flight statements. Under a threaded network backend that shows
        up as ``sqlite3.ProgrammingError: bad parameter or other API
        misuse`` and as writes that land with corrupted bindings.
        """
        self._db_path = os.path.join(xdg_data_home(), self.subfolder, self.name + ".db")
        LOG.debug(f"sqlite database path: {self._db_path}")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        if self.password is not None and self.password == "":
            raise ValueError("password must be non-empty when encryption is enabled")

        self._write_lock = threading.Lock()
        # opening the first connection also applies the WAL pragma
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._initialize_database()
        self._maybe_migrate()

    def _connect(self):
        """Open one new connection to the backing file."""
        if self.password is not None:
            try:
                import sqlcipher3 as _sqlcipher
            except ImportError:
                raise ImportError(
                    "sqlcipher3 is required to open an encrypted SQLite database. "
                    "Install the system library (e.g. 'apt install libsqlcipher-dev') "
                    "then: pip install hivemind-sqlite-database[cipher]"
                )
            conn = _sqlcipher.connect(self._db_path, check_same_thread=False)
            conn.row_factory = _sqlcipher.Row
            escaped_password = self.password.replace("'", "''")
            conn.execute(f"PRAGMA key='{escaped_password}'")
        else:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(self.BUSY_TIMEOUT_MS)}")
        return conn

    @property
    def conn(self):
        """The calling thread's own connection, opened on first use.

        Connections are cheap and WAL lets many readers run beside one
        writer, so a per-thread connection costs a file handle and buys
        real thread safety. ``_write_lock`` still serialises writers
        in-process so they do not fight over the file lock.
        """
        local = self._thread_state()
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = local.conn = self._connect()
        return conn

    @conn.setter
    def conn(self, value) -> None:
        """Adopt an already-open connection for the calling thread.

        Only the calling thread sees it; other threads still open their
        own. Tests use this to inject an in-memory database.
        """
        self._thread_state().conn = value

    def _thread_state(self) -> threading.local:
        local = self.__dict__.get("_local")
        if local is None:
            local = self.__dict__["_local"] = threading.local()
        return local

    def close(self) -> None:
        """Close the calling thread's connection, if it has one."""
        local = self._thread_state()
        conn = getattr(local, "conn", None)
        if conn is not None:
            local.conn = None
            try:
                conn.close()
            except sqlite3.Error as e:
                LOG.error(f"Failed to close SQLite connection: {e}")

    def _initialize_database(self):
        """Initialize the database schema."""
        with self.conn:
            # crypto key is always 16 chars
            # name description and api_key shouldnt be allowed to go over 255
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id INTEGER PRIMARY KEY,
                    api_key VARCHAR(255) NOT NULL,
                    name VARCHAR(255),
                    description VARCHAR(255),
                    is_admin BOOLEAN DEFAULT FALSE,
                    last_seen REAL DEFAULT -1,
                    intent_blacklist TEXT,
                    skill_blacklist TEXT,
                    message_blacklist TEXT,
                    allowed_types TEXT,
                    crypto_key VARCHAR(16),
                    password TEXT,
                    can_broadcast BOOLEAN DEFAULT TRUE,
                    can_escalate BOOLEAN DEFAULT TRUE,
                    can_propagate BOOLEAN DEFAULT TRUE,
                    metadata TEXT
                )
            """)
            # api_key is looked up on every client connection admission
            # (get_client_by_api_key), so a full table scan there is hot.
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_clients_api_key ON clients(api_key)"
            )
            columns = {
                row["name"]
                for row in self.conn.execute("PRAGMA table_info(clients)").fetchall()
            }
            if "metadata" not in columns:
                self.conn.execute("ALTER TABLE clients ADD COLUMN metadata TEXT")

    def _maybe_migrate(self) -> None:
        """Run schema migration if the on-disk version is behind ``SCHEMA_VERSION``.

        Persisted version lives in SQLite's ``PRAGMA user_version`` (a
        signed integer slot reserved exactly for this use case).
        Tolerates older HPM versions that predate ``SCHEMA_VERSION``.
        """
        target = getattr(AbstractDB, "SCHEMA_VERSION", 1)
        stored = self.conn.execute("PRAGMA user_version").fetchone()[0]
        # Tolerate older HPM that predates the forward-compat guard, the
        # same way SCHEMA_VERSION is read defensively above.
        if hasattr(self, "_check_forward_compat"):
            self._check_forward_compat(int(stored))
        if stored < target:
            LOG.info("SQLiteDB: migrating schema v%d -> v%d", stored, target)
            # Migrate row rewrites and the user_version bump share one
            # transaction so a crash never leaves the DB at "migrated rows
            # but stale sentinel" or vice versa.
            with self._write_lock, self.conn:
                self._migrate_locked(from_version=stored)
                self.conn.execute(f"PRAGMA user_version = {int(target)}")

    def migrate(self, from_version: int) -> None:
        """Migrate on-disk rows to the current ``SCHEMA_VERSION``.

        Idempotent and crash-safe: a partial migration re-run produces the
        same final state because the merge is ``setdefault``-style (never
        clobbers explicit metadata values) and the legacy columns are
        unconditionally NULLed in the same transaction.

        v1 -> v2: fold ``intent_blacklist`` / ``skill_blacklist`` column
        values into each row's ``metadata`` JSON dict, then NULL the
        legacy columns. ``message_blacklist`` is purged outright (the
        field is not part of the ``Client`` data model). The columns
        themselves remain in the table (SQLite ``ALTER TABLE ... DROP
        COLUMN`` is unreliable on older versions) but are no longer
        written by ``add_item``.
        """
        if from_version >= 2:
            return
        with self._write_lock, self.conn:
            self._migrate_locked(from_version=from_version)

    def _migrate_locked(self, from_version: int) -> None:
        """Inner migration body — assumes the caller already holds
        ``_write_lock`` and is inside a ``with self.conn`` transaction.
        Lets ``_maybe_migrate`` bundle the version-sentinel bump into the
        same transaction as the row rewrites."""
        if from_version >= 2:
            return
        for row in self.conn.execute(
            "SELECT client_id, intent_blacklist, skill_blacklist, "
            "message_blacklist, metadata FROM clients"
        ).fetchall():
            metadata = self._metadata_from_row(row) or {}
            # Drop any pre-existing metadata["message_blacklist"]
            # from earlier migration runs that folded it in.
            metadata.pop("message_blacklist", None)
            for key in ("intent_blacklist", "skill_blacklist"):
                raw = row[key]
                if not raw:
                    continue
                try:
                    legacy = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if legacy and key not in metadata:
                    metadata[key] = list(legacy)
            self.conn.execute(
                "UPDATE clients SET intent_blacklist = NULL, "
                "skill_blacklist = NULL, message_blacklist = NULL, "
                "metadata = ? WHERE client_id = ?",
                (self._metadata_to_json(metadata), int(row["client_id"])),
            )

    def add_item(self, client: Client) -> bool:
        """
        Add a client to the SQLite database.

        Args:
            client: The client to be added.

        Returns:
            True if the addition was successful, False otherwise.
        """
        try:
            metadata_json = self._metadata_to_json(client.metadata or {})
            with self._write_lock, self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO clients (
                        client_id, api_key, name, description, is_admin,
                        last_seen, intent_blacklist, skill_blacklist,
                        message_blacklist, allowed_types, crypto_key, password,
                        can_broadcast, can_escalate, can_propagate, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    client.client_id, client.api_key, client.name, client.description,
                    client.is_admin, client.last_seen,
                    # Legacy OVOS blacklist columns are no longer written —
                    # the data lives in ``Client.metadata`` (see SCHEMA_VERSION
                    # v2 migration). Columns kept in the table for back-compat
                    # with older readers; NULLed on write so the disk stays
                    # clean.
                    None,
                    None,
                    None,
                    json.dumps(client.allowed_types),
                    client.crypto_key, client.password,
                    client.can_broadcast, client.can_escalate, client.can_propagate,
                    metadata_json,
                ))
            return True
        except sqlite3.Error as e:
            LOG.error(f"Failed to add client to SQLite: {e}")
            return False

    def search_by_value(self, key: str, val: Union[str, bool, int, float]) -> List[Client]:
        """
        Search for clients by a specific key-value pair in the SQLite database.

        Args:
            key: The key to search by.
            val: The value to search for.

        Returns:
            A list of clients that match the search criteria.
        """
        if key not in _VALID_COLUMNS:
            LOG.error(f"Invalid search key: {key!r}")
            return []
        try:
            # deliberately NOT wrapped in ``with self.conn`` — that context
            # manager commits the connection's transaction on exit, which a
            # read has no business doing.
            cur = self.conn.execute(f"SELECT * FROM clients WHERE {key} = ?", (val,))
            rows = cur.fetchall()
            return [self._row_to_client(row) for row in rows]
        except sqlite3.Error as e:
            LOG.error(f"Failed to search clients in SQLite: {e}")
            return []

    def get_client_by_id(self, client_id: int) -> Optional[Client]:
        """Fetch a single client row by primary key.

        Targeted lookup used by :meth:`refresh` on the admission hot
        path — avoids the full ``search_by_value`` fallback. Returns
        ``None`` if the row does not exist or on any DB error.
        """
        if client_id is None:
            return None
        try:
            cur = self.conn.execute(
                "SELECT * FROM clients WHERE client_id = ?", (int(client_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_client(row)
        except (sqlite3.Error, TypeError, ValueError) as e:
            LOG.error(f"Failed to fetch client {client_id} from SQLite: {e}")
            return None

    def __len__(self) -> int:
        """Get the number of clients in the database."""
        try:
            cur = self.conn.execute("SELECT COUNT(*) FROM clients")
            return cur.fetchone()[0]
        except sqlite3.Error as e:
            LOG.error(f"Failed to count clients in SQLite: {e}")
            return 0

    def __iter__(self) -> Iterable['Client']:
        """
        Iterate over all clients in the SQLite database.

        Returns:
            An iterator over the clients in the database.
        """
        cur = self.conn.execute("SELECT * FROM clients")
        for row in cur:
            yield self._row_to_client(row)

    def commit(self) -> bool:
        """Commit changes to the SQLite database."""
        try:
            with self._write_lock:
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            LOG.error(f"Failed to commit SQLite database: {e}")
            return False

    @staticmethod
    def _row_to_client(row: sqlite3.Row) -> Client:
        """Convert a database row to a Client instance.

        Legacy OVOS blacklist columns are no longer passed as kwargs to
        ``Client(...)`` — after the v2 migration they are NULL on disk
        and the canonical data lives in ``metadata``. If a row predates
        migration (e.g. read by an older plugin version that didn't
        migrate, then read again here), the values are folded into
        ``metadata`` locally as a defensive fallback.
        """
        metadata = SQLiteDB._metadata_from_row(row) or {}
        # message_blacklist was removed from the Client data model — drop
        # any residual metadata key from earlier migrations.
        metadata.pop("message_blacklist", None)
        for key in ("intent_blacklist", "skill_blacklist"):
            raw = row[key] if key in row.keys() else None
            if not raw or key in metadata:
                continue
            try:
                legacy = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if legacy:
                metadata[key] = list(legacy)
        return Client(
            client_id=int(row["client_id"]),
            api_key=row["api_key"],
            name=row["name"],
            description=row["description"],
            is_admin=bool(row["is_admin"]),
            last_seen=row["last_seen"],
            allowed_types=json.loads(row["allowed_types"] or "[]"),
            crypto_key=row["crypto_key"],
            password=row["password"],
            can_broadcast=bool(row["can_broadcast"]),
            can_escalate=bool(row["can_escalate"]),
            can_propagate=bool(row["can_propagate"]),
            metadata=metadata,
        )

    @staticmethod
    def _metadata_to_json(metadata: object) -> str:
        """Serialize ``Client.metadata`` for storage in the ``metadata`` column.

        ``metadata`` is documented as a free-form dict; we use ``default=str``
        so callers can stash convenience values like ``datetime`` or ``UUID``
        without crashing on insert. Note that these come back as strings on
        read — the column is opaque JSON, not a typed map. Returns ``"{}"``
        for non-dict input and on any (unexpected) serialisation failure
        rather than corrupting the row.
        """
        if not isinstance(metadata, dict):
            return "{}"
        try:
            return json.dumps(metadata, default=str)
        except (TypeError, ValueError):
            return "{}"

    @staticmethod
    def _metadata_from_row(row: sqlite3.Row) -> dict:
        """Decode the ``metadata`` column into a dict, swallowing garbage.

        Returns ``{}`` for NULL, malformed JSON, or valid-JSON-that-isn't-an-object.
        Lets a single bad row not poison iteration over the table.
        """
        if "metadata" not in row.keys() or not row["metadata"]:
            return {}
        try:
            metadata = json.loads(row["metadata"])
        except (TypeError, ValueError):
            return {}
        return metadata if isinstance(metadata, dict) else {}
