import json
import os.path
import sqlite3
from typing import List, Union, Iterable

from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home

from hivemind_plugin_manager.database import Client, AbstractDB


class SQLiteDB(AbstractDB):
    """Database implementation using SQLite."""

    def __init__(self, name="clients", subfolder="hivemind-core"):
        """
        Initialize the SQLiteDB connection.
        """
        db_path = os.path.join(xdg_data_home(), subfolder, name + ".db")
        LOG.debug(f"sqlite database path: {db_path}")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._initialize_database()

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
                    can_propagate BOOLEAN DEFAULT TRUE
                )
            """)

    def add_item(self, client: Client) -> bool:
        """
        Add a client to the SQLite database.

        Args:
            client: The client to be added.

        Returns:
            True if the addition was successful, False otherwise.
        """
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO clients (
                        client_id, api_key, name, description, is_admin,
                        last_seen, intent_blacklist, skill_blacklist,
                        message_blacklist, allowed_types, crypto_key, password,
                        can_broadcast, can_escalate, can_propagate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    client.client_id, client.api_key, client.name, client.description,
                    client.is_admin, client.last_seen,
                    json.dumps(client.intent_blacklist),
                    json.dumps(client.skill_blacklist),
                    json.dumps(client.message_blacklist),
                    json.dumps(client.allowed_types),
                    client.crypto_key, client.password,
                    client.can_broadcast, client.can_escalate, client.can_propagate
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
        try:
            with self.conn:
                cur = self.conn.execute(f"SELECT * FROM clients WHERE {key} = ?", (val,))
                rows = cur.fetchall()
                return [self._row_to_client(row) for row in rows]
        except sqlite3.Error as e:
            LOG.error(f"Failed to search clients in SQLite: {e}")
            return []

    def __len__(self) -> int:
        """Get the number of clients in the database."""
        cur = self.conn.execute("SELECT COUNT(*) FROM clients")
        return cur.fetchone()[0]

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
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            LOG.error(f"Failed to commit SQLite database: {e}")
            return False

    @staticmethod
    def _row_to_client(row: sqlite3.Row) -> Client:
        """Convert a database row to a Client instance."""
        return Client(
            client_id=int(row["client_id"]),
            api_key=row["api_key"],
            name=row["name"],
            description=row["description"],
            is_admin=row["is_admin"] or False,
            last_seen=row["last_seen"],
            intent_blacklist=json.loads(row["intent_blacklist"] or "[]"),
            skill_blacklist=json.loads(row["skill_blacklist"] or "[]"),
            message_blacklist=json.loads(row["message_blacklist"] or "[]"),
            allowed_types=json.loads(row["allowed_types"] or "[]"),
            crypto_key=row["crypto_key"],
            password=row["password"],
            can_broadcast=row["can_broadcast"],
            can_escalate=row["can_escalate"],
            can_propagate=row["can_propagate"]
        )
