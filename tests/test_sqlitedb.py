"""
Tests for SQLiteDB using an in-memory database.
No external services required.
"""
import sqlite3
import tempfile
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

    def test_full_client_fields_preserved(self):
        db = make_db()
        c = Client(
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


if __name__ == "__main__":
    unittest.main()
