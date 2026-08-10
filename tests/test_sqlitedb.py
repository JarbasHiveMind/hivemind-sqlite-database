"""
Tests for SQLiteDB using an in-memory database.
No external services required.
"""
import sqlite3
import tempfile
import threading
import os
import unittest

from hivemind_plugin_manager.database import Client
from hivemind_sqlite_database import SQLiteDB


def make_db() -> SQLiteDB:
    """Return a fresh in-memory SQLiteDB instance."""
    db = object.__new__(SQLiteDB)
    db.name = "clients"
    db.subfolder = "hivemind-core"
    db.conn = sqlite3.connect(":memory:", check_same_thread=False)
    db.conn.row_factory = sqlite3.Row
    db.conn.execute("PRAGMA journal_mode=WAL")
    db._write_lock = threading.Lock()
    db._initialize_database()
    return db


def make_client(client_id: int = 1, api_key: str = "key-abc", **kwargs) -> Client:
    return Client(client_id=client_id, api_key=api_key, **kwargs)


class TestSQLiteDBWAL(unittest.TestCase):
    def test_wal_mode_pragma_in_source(self):
        """WAL pragma must be present in __post_init__ source code."""
        import inspect
        from hivemind_sqlite_database import SQLiteDB as _DB
        src = inspect.getsource(_DB.__post_init__)
        self.assertIn("journal_mode=WAL", src)

    def test_wal_mode_active_on_file_db(self):
        """WAL mode is confirmed active on a real file-based SQLite DB."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0]
            conn.close()
            self.assertEqual(mode, "wal")
        finally:
            os.unlink(path)


class TestSQLiteDBLen(unittest.TestCase):
    def test_empty_db_has_len_zero(self):
        db = make_db()
        self.assertEqual(len(db), 0)

    def test_len_increments_after_add(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        db.add_item(make_client(2, "k2"))
        self.assertEqual(len(db), 2)

    def test_len_includes_revoked_entries(self):
        db = make_db()
        c = make_client(1, "k1")
        db.add_item(c)
        db.delete_item(c)
        self.assertEqual(len(db), 1)

    def test_len_returns_zero_on_error(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        db.conn.close()
        self.assertEqual(len(db), 0)


class TestSQLiteDBAddItem(unittest.TestCase):
    def test_add_returns_true_on_success(self):
        db = make_db()
        result = db.add_item(make_client(1, "key"))
        self.assertTrue(result)

    def test_add_upserts_existing_client_id(self):
        db = make_db()
        db.add_item(make_client(1, "original"))
        db.add_item(make_client(1, "updated"))
        results = db.search_by_value("api_key", "updated")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].api_key, "updated")
        # original key is gone
        self.assertEqual(db.search_by_value("api_key", "original"), [])

    def test_add_returns_false_on_error(self):
        db = make_db()
        db.conn.close()  # closing the connection causes sqlite3.Error on next operation
        result = db.add_item(make_client(1, "key"))
        self.assertFalse(result)


class TestSQLiteDBDeleteItem(unittest.TestCase):
    def test_delete_sets_api_key_to_revoked(self):
        db = make_db()
        c = make_client(1, "live-key")
        db.add_item(c)
        db.delete_item(c)
        results = db.search_by_value("api_key", "revoked")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].client_id, 1)

    def test_delete_does_not_remove_row(self):
        db = make_db()
        c = make_client(1, "live-key")
        db.add_item(c)
        db.delete_item(c)
        self.assertEqual(len(db), 1)

    def test_original_key_no_longer_searchable_after_delete(self):
        db = make_db()
        c = make_client(1, "live-key")
        db.add_item(c)
        db.delete_item(c)
        self.assertEqual(db.search_by_value("api_key", "live-key"), [])


class TestSQLiteDBSearchByValue(unittest.TestCase):
    def test_search_by_api_key_returns_client(self):
        db = make_db()
        db.add_item(make_client(1, "my-key"))
        results = db.search_by_value("api_key", "my-key")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].api_key, "my-key")

    def test_search_returns_empty_list_on_no_match(self):
        db = make_db()
        db.add_item(make_client(1, "real-key"))
        self.assertEqual(db.search_by_value("api_key", "ghost"), [])

    def test_search_by_is_admin_true(self):
        db = make_db()
        db.add_item(make_client(1, "admin-key", is_admin=True))
        db.add_item(make_client(2, "user-key", is_admin=False))
        results = db.search_by_value("is_admin", True)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_admin)

    def test_search_by_is_admin_false(self):
        db = make_db()
        db.add_item(make_client(1, "admin-key", is_admin=True))
        db.add_item(make_client(2, "user-key", is_admin=False))
        results = db.search_by_value("is_admin", False)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].is_admin)

    def test_search_by_name(self):
        db = make_db()
        db.add_item(make_client(1, "k1", name="alice"))
        db.add_item(make_client(2, "k2", name="bob"))
        results = db.search_by_value("name", "alice")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "alice")

    def test_search_by_nonexistent_name_returns_empty(self):
        db = make_db()
        db.add_item(make_client(1, "k1", name="alice"))
        self.assertEqual(db.search_by_value("name", "ghost"), [])

    def test_search_returns_empty_on_sqlite_error(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        db.conn.close()
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(results, [])

    def test_search_rejects_invalid_column_name(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        results = db.search_by_value("1=1; DROP TABLE clients; --", "x")
        self.assertEqual(results, [])
        # table must still exist
        self.assertEqual(len(db), 1)

    def test_search_rejects_unknown_column(self):
        db = make_db()
        results = db.search_by_value("nonexistent_column", "value")
        self.assertEqual(results, [])


class TestSQLiteDBIter(unittest.TestCase):
    def test_iter_yields_all_rows(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        db.add_item(make_client(2, "k2"))
        all_clients = list(db)
        self.assertEqual(len(all_clients), 2)

    def test_iter_includes_revoked_entries(self):
        db = make_db()
        c = make_client(1, "k1")
        db.add_item(c)
        db.delete_item(c)
        all_clients = list(db)
        self.assertEqual(len(all_clients), 1)
        self.assertEqual(all_clients[0].api_key, "revoked")

    def test_iter_yields_client_instances(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        for client in db:
            self.assertIsInstance(client, Client)


class TestSQLiteDBRoundTrip(unittest.TestCase):
    def test_list_fields_survive_round_trip(self):
        db = make_db()
        intent_bl = ["skill:action1", "skill:action2"]
        allowed = ["recognizer_loop:utterance", "speak:b64_audio"]
        c = make_client(1, "k1",
                        intent_blacklist=intent_bl,
                        allowed_types=allowed)
        db.add_item(c)
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].intent_blacklist, intent_bl)
        self.assertEqual(results[0].allowed_types, allowed)

    def test_boolean_fields_remain_bool_after_round_trip(self):
        db = make_db()
        db.add_item(make_client(1, "k1", is_admin=True, can_broadcast=False))
        results = db.search_by_value("api_key", "k1")
        self.assertIs(type(results[0].is_admin), bool)
        self.assertTrue(results[0].is_admin)
        self.assertIs(type(results[0].can_broadcast), bool)
        self.assertFalse(results[0].can_broadcast)

    def test_metadata_survives_round_trip(self):
        db = make_db()
        db.add_item(
            make_client(
                1,
                "k1",
                metadata={"owner_id": "owner-123"},
            )
        )

        results = db.search_by_value("api_key", "k1")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata, {"owner_id": "owner-123"})

    def test_metadata_can_be_searched(self):
        db = make_db()
        db.add_item(
            make_client(
                1,
                "k1",
                metadata={"owner_id": "owner-123"},
            )
        )

        results = db.search_by_value("metadata", '{"owner_id": "owner-123"}')

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].api_key, "k1")

    def test_initialize_database_migrates_legacy_clients_table(self):
        db = object.__new__(SQLiteDB)
        db.name = "clients"
        db.subfolder = "hivemind-core"
        db.conn = sqlite3.connect(":memory:", check_same_thread=False)
        db.conn.row_factory = sqlite3.Row
        db._write_lock = threading.Lock()
        with db.conn:
            db.conn.execute("""
                CREATE TABLE clients (
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
                    can_propagate BOOLEAN DEFAULT TRUE
                )
            """)
            db.conn.execute("INSERT INTO clients (client_id, api_key) VALUES (1, 'k1')")

        db._initialize_database()

        columns = {
            row["name"]
            for row in db.conn.execute("PRAGMA table_info(clients)").fetchall()
        }
        self.assertIn("metadata", columns)
        client = db.search_by_value("api_key", "k1")[0]
        self.assertEqual(client.metadata, {})

    def test_metadata_nested_dict_round_trip(self):
        db = make_db()
        meta = {
            "owner": {"id": "owner-1", "tags": ["a", "b"]},
            "counts": {"x": 1, "y": 2},
        }
        db.add_item(make_client(1, "k1", metadata=meta))
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata, meta)

    def test_metadata_non_ascii_round_trip(self):
        db = make_db()
        meta = {"name": "Zé Ninguém", "emoji": "🚀", "ru": "Привет"}
        db.add_item(make_client(1, "k1", metadata=meta))
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata, meta)

    def test_metadata_survives_iteration(self):
        db = make_db()
        db.add_item(
            make_client(
                1,
                "k1",
                metadata={"owner_id": "owner-123"},
            )
        )

        clients = list(db)

        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].metadata, {"owner_id": "owner-123"})

    def test_metadata_defaults_to_empty_dict_when_not_provided(self):
        db = make_db()
        db.add_item(make_client(1, "k1"))
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(results[0].metadata, {})

    def test_metadata_overwritten_on_reinsert_with_same_client_id(self):
        db = make_db()
        db.add_item(make_client(1, "k1", metadata={"v": 1}))
        db.add_item(make_client(1, "k1", metadata={"v": 2, "extra": "x"}))
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata, {"v": 2, "extra": "x"})

    def test_metadata_to_json_returns_empty_for_non_dict(self):
        self.assertEqual(SQLiteDB._metadata_to_json("not a dict"), "{}")
        self.assertEqual(SQLiteDB._metadata_to_json(None), "{}")
        self.assertEqual(SQLiteDB._metadata_to_json(42), "{}")

    def test_metadata_from_row_returns_empty_for_garbage_or_missing(self):
        db = make_db()
        # legacy-style row with explicit NULL metadata
        db.add_item(make_client(1, "k1"))
        with db.conn:
            db.conn.execute("UPDATE clients SET metadata = NULL WHERE client_id = 1")
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(results[0].metadata, {})
        # garbage JSON in the metadata column → coerce to {}
        with db.conn:
            db.conn.execute("UPDATE clients SET metadata = 'not json{' WHERE client_id = 1")
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(results[0].metadata, {})
        # valid JSON but not an object → coerce to {}
        with db.conn:
            db.conn.execute("UPDATE clients SET metadata = '[1,2,3]' WHERE client_id = 1")
        results = db.search_by_value("api_key", "k1")
        self.assertEqual(results[0].metadata, {})

    def test_full_client_fields_preserved(self):
        db = make_db()
        c = make_client(
            client_id=42,
            api_key="full-key",
            name="test-client",
            description="a test",
            is_admin=False,
            last_seen=1234567890.0,
            intent_blacklist=["a:b"],
            skill_blacklist=["c:d"],
            allowed_types=["recognizer_loop:utterance"],
            crypto_key="1234567890123456",
            password="secret",
            can_broadcast=True,
            can_escalate=False,
            can_propagate=True,
            metadata={"owner_id": "owner-123"},
        )
        db.add_item(c)
        results = db.search_by_value("api_key", "full-key")
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.client_id, 42)
        self.assertEqual(r.name, "test-client")
        self.assertEqual(r.description, "a test")
        self.assertFalse(r.is_admin)
        self.assertEqual(r.last_seen, 1234567890.0)
        self.assertEqual(r.crypto_key, "1234567890123456")
        self.assertEqual(r.password, "secret")
        self.assertFalse(r.can_escalate)
        # After SCHEMA_VERSION=2: legacy skill/intent kwargs auto-migrate
        # into ``Client.metadata`` via Client.__init__. message_blacklist
        # is gone from the data model — not accepted as a kwarg and not
        # carried in metadata.
        self.assertEqual(r.metadata, {
            "owner_id": "owner-123",
            "intent_blacklist": ["a:b"],
            "skill_blacklist": ["c:d"],
        })
        # Property shims surface skill/intent blacklists at legacy names.
        self.assertEqual(r.skill_blacklist, ["c:d"])
        self.assertEqual(r.intent_blacklist, ["a:b"])


class TestSQLiteDBPathOverride(unittest.TestCase):
    """A worker thread must never fall back to the real client database
    just because the test only overrode `.conn` on the main thread."""

    def test_db_path_override_keeps_worker_threads_off_disk(self):
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "hivemind_sqlite_database.xdg_data_home", return_value=tmpdir
            ):
                db = SQLiteDB(name="clients", subfolder="hivemind-core",
                              db_path=":memory:")

                # Read a row written on this thread. "SELECT 1" would answer
                # the same against a private, empty database and so would
                # never notice a per-thread database.
                db.add_item(Client(client_id=1, api_key="key",
                                   name="kitchen"))

                errors = []
                seen = []

                def worker():
                    try:
                        seen.extend(db.search_by_value("name", "kitchen"))
                    except Exception as e:  # noqa: BLE001
                        errors.append(e)

                t = threading.Thread(target=worker)
                t.start()
                t.join()

            self.assertEqual(errors, [])
            self.assertEqual([c.client_id for c in seen], [1])
            real_db_file = os.path.join(tmpdir, "hivemind-core", "clients.db")
            self.assertFalse(os.path.exists(real_db_file))

    def test_two_in_memory_databases_stay_independent(self):
        first = SQLiteDB(db_path=":memory:")
        second = SQLiteDB(db_path=":memory:")
        first.add_item(Client(client_id=1, api_key="key", name="kitchen"))
        self.assertEqual(second.search_by_value("name", "kitchen"), [])

    def test_explicit_db_path_creates_missing_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "newdir", "clients.db")
            SQLiteDB(db_path=path)
            self.assertTrue(os.path.isfile(path))


class TestSQLiteDBCommit(unittest.TestCase):
    def test_commit_returns_true(self):
        db = make_db()
        self.assertTrue(db.commit())

    def test_commit_returns_false_on_error(self):
        db = make_db()
        db.conn.close()
        result = db.commit()
        self.assertFalse(result)


class TestSQLiteDBUpdateAndReplace(unittest.TestCase):
    def test_update_item_changes_fields(self):
        db = make_db()
        db.add_item(make_client(1, "k1", name="old"))
        updated = make_client(1, "k1", name="new")
        db.update_item(updated)
        results = db.search_by_value("name", "new")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "new")

    def test_replace_item(self):
        db = make_db()
        old = make_client(1, "old-key")
        new = make_client(2, "new-key")
        db.add_item(old)
        db.replace_item(old, new)
        self.assertEqual(db.search_by_value("api_key", "new-key")[0].client_id, 2)
        # old entry is revoked, not gone
        self.assertEqual(db.search_by_value("api_key", "revoked")[0].client_id, 1)


try:
    import sqlcipher3 as _sqlcipher3  # noqa: F401
    _SQLCIPHER_AVAILABLE = True
except ImportError:
    _SQLCIPHER_AVAILABLE = False


@unittest.skipUnless(_SQLCIPHER_AVAILABLE, "sqlcipher3 not installed")
class TestSQLiteDBEncrypted(unittest.TestCase):
    """Tests for the SQLCipher-encrypted path.  Skipped when sqlcipher3 is absent."""

    def _make_encrypted_db(self, path: str, password: str = "hunter2") -> SQLiteDB:
        import unittest.mock as mock
        db = SQLiteDB.__new__(SQLiteDB)
        db.name = os.path.splitext(os.path.basename(path))[0]
        db.subfolder = ""
        db.password = password
        with mock.patch(
            "hivemind_sqlite_database.xdg_data_home",
            return_value=os.path.dirname(path),
        ):
            db.__post_init__()
        return db

    def test_encrypted_file_unreadable_by_stdlib_sqlite3(self):
        """A file created with a password must be opaque to plain sqlite3."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        os.unlink(path)
        try:
            db = self._make_encrypted_db(path, password="secret123")
            db.add_item(make_client(1, "enc-key"))
            db.commit()
            # stdlib sqlite3 should not be able to read it
            plain_conn = sqlite3.connect(path)
            with self.assertRaises(sqlite3.DatabaseError):
                plain_conn.execute("SELECT * FROM clients").fetchall()
            plain_conn.close()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_encrypted_round_trip(self):
        """add_item then search_by_value works through the encryption layer."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        os.unlink(path)
        try:
            db = self._make_encrypted_db(path, password="roundtrip")
            db.add_item(make_client(1, "enc-api-key", name="alice"))
            db.commit()
            # Reopen with same password
            db2 = self._make_encrypted_db(path, password="roundtrip")
            results = db2.search_by_value("api_key", "enc-api-key")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].name, "alice")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_sqlitedb_password_kwarg_raises_importerror_without_sqlcipher3(self):
        """Confirmed separately in test_sqlitedb_no_sqlcipher.py; skip here."""
        pass


class TestSQLiteDBMissingCipher(unittest.TestCase):
    """Verify ImportError is raised when sqlcipher3 is absent and password is given."""

    def test_importerror_when_sqlcipher3_missing(self):
        import sys
        import unittest.mock as mock

        # Simulate sqlcipher3 not being installed
        with mock.patch.dict(sys.modules, {"sqlcipher3": None}):
            with tempfile.TemporaryDirectory() as tmpdir:
                with self.assertRaises(ImportError) as ctx:
                    db = SQLiteDB.__new__(SQLiteDB)
                    db.name = "test"
                    db.subfolder = tmpdir
                    db.password = "secret"
                    # Patch xdg_data_home so db_path resolves inside tmpdir
                    with mock.patch("hivemind_sqlite_database.xdg_data_home",
                                    return_value=tmpdir):
                        db.__post_init__()
                self.assertIn("sqlcipher3", str(ctx.exception))


class TestSQLiteDBMigration(unittest.TestCase):
    """v1 -> v2: legacy OVOS blacklist columns folded into metadata."""

    def _make_v1_db_with_legacy_rows(self) -> SQLiteDB:
        """Construct a DB in the v1 shape: legacy columns populated,
        ``PRAGMA user_version`` left at 0 (the SQLite default)."""
        db = object.__new__(SQLiteDB)
        db.name = "clients"
        db.subfolder = "hivemind-core"
        db.conn = sqlite3.connect(":memory:", check_same_thread=False)
        db.conn.row_factory = sqlite3.Row
        db._write_lock = threading.Lock()
        db._initialize_database()
        # Write a row directly with legacy column data — bypass add_item
        # which would NULL them.
        db.conn.execute(
            "INSERT INTO clients (client_id, api_key, intent_blacklist, "
            "skill_blacklist, message_blacklist, allowed_types, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (7, "legacy-key",
             '["i:1"]', '["s:1"]', '["m:1"]', '[]', '{"owner": "u"}'),
        )
        db.conn.commit()
        return db

    def test_pragma_user_version_starts_at_zero(self):
        db = self._make_v1_db_with_legacy_rows()
        stored = db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(stored, 0)

    def test_migrate_folds_legacy_columns_into_metadata(self):
        db = self._make_v1_db_with_legacy_rows()
        db.migrate(from_version=1)
        row = db.conn.execute(
            "SELECT intent_blacklist, skill_blacklist, message_blacklist, "
            "metadata FROM clients WHERE client_id = 7"
        ).fetchone()
        self.assertIsNone(row["intent_blacklist"])
        self.assertIsNone(row["skill_blacklist"])
        self.assertIsNone(row["message_blacklist"])
        import json as _json
        meta = _json.loads(row["metadata"])
        self.assertEqual(meta["owner"], "u")
        self.assertEqual(meta["intent_blacklist"], ["i:1"])
        self.assertEqual(meta["skill_blacklist"], ["s:1"])
        # message_blacklist is purged outright, NOT folded into metadata.
        self.assertNotIn("message_blacklist", meta)

    def test_migrate_purges_residual_metadata_message_blacklist(self):
        """An older plugin version may have folded message_blacklist
        into metadata before HPM removed the field. The newer migrate()
        must purge it on re-run, leaving the disk clean."""
        db = self._make_v1_db_with_legacy_rows()
        # Seed an already-half-migrated row: legacy columns NULL, but
        # metadata still carries the old key from the prior migration.
        db.conn.execute(
            "UPDATE clients SET intent_blacklist = NULL, "
            "skill_blacklist = NULL, message_blacklist = NULL, "
            "metadata = ? WHERE client_id = 7",
            ('{"owner": "u", "message_blacklist": ["m:1"]}',),
        )
        db.conn.commit()

        db.migrate(from_version=1)

        import json as _json
        meta = _json.loads(db.conn.execute(
            "SELECT metadata FROM clients WHERE client_id = 7"
        ).fetchone()["metadata"])
        self.assertNotIn("message_blacklist", meta)
        self.assertEqual(meta["owner"], "u")

    def test_migrate_is_idempotent(self):
        db = self._make_v1_db_with_legacy_rows()
        db.migrate(from_version=1)
        db.migrate(from_version=1)  # second run = no-op on already-migrated row
        row = db.conn.execute(
            "SELECT metadata FROM clients WHERE client_id = 7"
        ).fetchone()
        import json as _json
        meta = _json.loads(row["metadata"])
        self.assertEqual(meta["skill_blacklist"], ["s:1"])

    def test_migrate_setdefault_does_not_clobber_explicit_metadata(self):
        db = self._make_v1_db_with_legacy_rows()
        # Explicit metadata.skill_blacklist takes precedence over the
        # legacy column.
        db.conn.execute(
            "UPDATE clients SET metadata = ? WHERE client_id = 7",
            ('{"owner": "u", "skill_blacklist": ["explicit"]}',),
        )
        db.migrate(from_version=1)
        import json as _json
        meta = _json.loads(db.conn.execute(
            "SELECT metadata FROM clients WHERE client_id = 7"
        ).fetchone()["metadata"])
        self.assertEqual(meta["skill_blacklist"], ["explicit"])

    def test_migrate_skips_when_already_at_target(self):
        db = self._make_v1_db_with_legacy_rows()
        # Stub: a from_version >= 2 should not touch the row.
        db.migrate(from_version=2)
        row = db.conn.execute(
            "SELECT intent_blacklist FROM clients WHERE client_id = 7"
        ).fetchone()
        self.assertEqual(row["intent_blacklist"], '["i:1"]')

    def test_maybe_migrate_bumps_user_version(self):
        db = self._make_v1_db_with_legacy_rows()
        db._maybe_migrate()
        stored = db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(stored, 2)
        # second invocation is a no-op
        db._maybe_migrate()
        self.assertEqual(
            db.conn.execute("PRAGMA user_version").fetchone()[0], 2,
        )

    def test_post_init_runs_migration_on_existing_db(self):
        """End-to-end: open a v1 DB file, observe v2 on-disk shape."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "hivemind-core", "clients.db")
            os.makedirs(os.path.dirname(db_path))
            # Seed a v1-shape DB with legacy column data.
            seed = sqlite3.connect(db_path)
            seed.execute("""
                CREATE TABLE clients (
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
            seed.execute(
                "INSERT INTO clients (client_id, api_key, skill_blacklist) "
                "VALUES (?, ?, ?)",
                (9, "k", '["legacy.skill"]'),
            )
            seed.commit()
            seed.close()
            # Now open it via SQLiteDB — __post_init__ should migrate.
            import unittest.mock as mock
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                db = SQLiteDB(name="clients", subfolder="hivemind-core")
            self.assertEqual(
                db.conn.execute("PRAGMA user_version").fetchone()[0], 2,
            )
            row = db.conn.execute(
                "SELECT skill_blacklist, metadata FROM clients "
                "WHERE client_id = 9"
            ).fetchone()
            self.assertIsNone(row["skill_blacklist"])
            import json as _json
            self.assertEqual(_json.loads(row["metadata"])["skill_blacklist"],
                             ["legacy.skill"])


class TestSQLiteDBEmptyDatabaseMigration(unittest.TestCase):
    """A fresh DB (no rows, user_version=0) must still bump to the
    current SCHEMA_VERSION on first open. Validates the cotransactional
    migrate + sentinel write."""

    def test_empty_new_db_bumps_user_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            import unittest.mock as mock
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                db = SQLiteDB(name="clients", subfolder="hivemind-core")
            stored = db.conn.execute("PRAGMA user_version").fetchone()[0]
            from hivemind_plugin_manager.database import AbstractDB
            target = getattr(AbstractDB, "SCHEMA_VERSION", 1)
            self.assertEqual(stored, target)
            # No rows in the clients table — migration must be a no-op
            # over rows but the sentinel still moves.
            count = db.conn.execute(
                "SELECT COUNT(*) FROM clients"
            ).fetchone()[0]
            self.assertEqual(count, 0)


class TestSQLiteDBForwardCompat(unittest.TestCase):
    """A DB whose ``user_version`` is newer than this backend supports
    must fail loudly with a RuntimeError instead of silently downgrading.
    """

    def test_forward_version_raises_runtime_error(self):
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                db = SQLiteDB(name="clients", subfolder="hivemind-core")
                db.conn.execute("PRAGMA user_version = 999")
                db.conn.commit()
                db.conn.close()
                with self.assertRaises(RuntimeError) as ctx:
                    SQLiteDB(name="clients", subfolder="hivemind-core")
                self.assertIn("999", str(ctx.exception))


class TestSQLiteDBGetClientByID(unittest.TestCase):
    def test_get_client_by_id_returns_row(self):
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                db = SQLiteDB(name="clients", subfolder="hivemind-core")
                from hivemind_plugin_manager.database import Client
                db.add_item(Client(client_id=42, api_key="k", name="alice"))
                got = db.get_client_by_id(42)
                self.assertIsNotNone(got)
                self.assertEqual(got.client_id, 42)
                self.assertIsNone(db.get_client_by_id(999))

    def test_refresh_picks_up_updates(self):
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                db = SQLiteDB(name="clients", subfolder="hivemind-core")
                from hivemind_plugin_manager.database import Client
                db.add_item(Client(client_id=1, api_key="k", name="a",
                                   allowed_types=["x"]))
                self.assertEqual(db.refresh(1).allowed_types, ["x"])
                db.add_item(Client(client_id=1, api_key="k", name="a",
                                   allowed_types=["y"]))
                self.assertEqual(db.refresh(1).allowed_types, ["y"])


class TestSQLiteDBApiKeyIndex(unittest.TestCase):
    def test_index_exists_after_init(self):
        db = make_db()
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_clients_api_key'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_api_key_lookup_uses_index(self):
        db = make_db()
        plan = db.conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM clients WHERE api_key = ?",
            ("k1",),
        ).fetchall()
        detail = " ".join(row["detail"] for row in plan)
        self.assertIn("SEARCH", detail)
        self.assertNotIn("SCAN", detail)


class TestSQLiteDBSchemaV2RoundTrip(unittest.TestCase):
    """v2 schema: allowed_types + skill/intent blacklists (in metadata) survive
    add→search and add→refresh cycles without loss or mutation."""

    def test_allowed_types_survives_round_trip(self):
        db = make_db()
        allowed = ["recognizer_loop:utterance", "speak:b64_audio"]
        db.add_item(make_client(1, "k", allowed_types=allowed))
        found = db.search_by_value("api_key", "k")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].allowed_types, allowed)

    def test_skill_blacklist_in_metadata_survives_round_trip(self):
        db = make_db()
        c = make_client(2, "k2", metadata={"skill_blacklist": ["my.skill"]})
        db.add_item(c)
        found = db.search_by_value("api_key", "k2")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].skill_blacklist, ["my.skill"])
        self.assertEqual(found[0].metadata["skill_blacklist"], ["my.skill"])

    def test_intent_blacklist_in_metadata_survives_round_trip(self):
        db = make_db()
        c = make_client(3, "k3", metadata={"intent_blacklist": ["my.skill:action"]})
        db.add_item(c)
        found = db.search_by_value("api_key", "k3")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].intent_blacklist, ["my.skill:action"])
        self.assertEqual(found[0].metadata["intent_blacklist"], ["my.skill:action"])

    def test_message_blacklist_not_present_in_stored_record(self):
        """message_blacklist must not appear in a freshly-stored record."""
        db = make_db()
        db.add_item(make_client(4, "k4"))
        row = db.conn.execute(
            "SELECT message_blacklist, metadata FROM clients WHERE client_id = 4"
        ).fetchone()
        self.assertIsNone(row["message_blacklist"])
        import json as _json
        meta = _json.loads(row["metadata"] or "{}")
        self.assertNotIn("message_blacklist", meta)

    def test_v1_row_reads_cleanly_forward_compat(self):
        """A v1 row (legacy columns populated) must deserialize via
        _row_to_client without crashing."""
        db = make_db()
        db.conn.execute(
            "INSERT INTO clients (client_id, api_key, skill_blacklist, "
            "intent_blacklist, message_blacklist, allowed_types, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (5, "k5", '["old.skill"]', '[]', '["drop.me"]',
             '["recognizer_loop:utterance"]', "{}"),
        )
        db.conn.commit()
        found = db.search_by_value("api_key", "k5")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].api_key, "k5")
        self.assertEqual(found[0].allowed_types, ["recognizer_loop:utterance"])

    def test_refresh_returns_v2_fields(self):
        db = make_db()
        import unittest.mock as mock
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("hivemind_sqlite_database.xdg_data_home",
                            return_value=tmp):
                filedb = SQLiteDB(name="clients", subfolder="hivemind-core")
            allowed = ["recognizer_loop:utterance"]
            meta = {"skill_blacklist": ["s:1"], "intent_blacklist": ["i:1"]}
            filedb.add_item(make_client(6, "k6", allowed_types=allowed, metadata=meta))
            got = filedb.refresh(6)
        self.assertIsNotNone(got)
        self.assertEqual(got.allowed_types, allowed)
        self.assertEqual(got.skill_blacklist, ["s:1"])
        self.assertEqual(got.intent_blacklist, ["i:1"])


if __name__ == "__main__":
    unittest.main()


class TestSQLiteDBThreadSafety(unittest.TestCase):
    """A real file-backed DB hammered from many threads at once.

    Reproduces the failure seen under the threaded (webrockets) network
    backend: concurrent reads and writes through ONE shared connection
    raise ``bad parameter or other API misuse`` and write rows with
    corrupted bindings (``NOT NULL constraint failed: clients.api_key``),
    because one thread's implicit COMMIT ends another thread's
    transaction.
    """

    def test_concurrent_read_write_is_clean(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            with patch("hivemind_sqlite_database.xdg_data_home", return_value=tmp):
                db = SQLiteDB()
                n = 60
                for i in range(n):
                    self.assertTrue(db.add_item(make_client(i, f"key-{i}")))

                errors = []
                misses = []
                barrier = threading.Barrier(24)

                def reader(i):
                    barrier.wait()
                    try:
                        for _ in range(40):
                            got = db.search_by_value("api_key", f"key-{i % n}")
                            if len(got) != 1:
                                misses.append((i, len(got)))
                    except Exception as e:  # noqa: BLE001
                        errors.append(repr(e))

                def writer(i):
                    barrier.wait()
                    try:
                        for k in range(40):
                            if not db.add_item(
                                make_client(i % n, f"key-{i % n}",
                                            name=f"w{k}")):
                                errors.append(f"add_item returned False ({i},{k})")
                    except Exception as e:  # noqa: BLE001
                        errors.append(repr(e))

                threads = [threading.Thread(target=reader, args=(i,))
                           for i in range(16)]
                threads += [threading.Thread(target=writer, args=(i,))
                            for i in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=120)

                self.assertEqual(errors, [])
                self.assertEqual(misses, [])
                # every api_key still resolves to exactly one live row
                for i in range(n):
                    self.assertEqual(len(db.search_by_value("api_key", f"key-{i}")), 1)
