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
            message_blacklist=["e:f"],
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
        self.assertEqual(r.metadata, {"owner_id": "owner-123"})


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


if __name__ == "__main__":
    unittest.main()
