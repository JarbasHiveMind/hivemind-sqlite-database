"""E2E tests for HiveMind SQLite database plugin."""

from hivescope import TopologyBuilder
from hivescope.assertions import assert_client_registered, assert_handshake_complete


def test_sqlite_db_registers_satellite():
    """SQLite database stores and retrieves satellite credentials."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("test-key", password="test-password")
    s = b.add_satellite("S0", upstream=m)

    b.start_all()
    try:
        s.connect(m)
        s.wait_for_handshake(timeout=5)
        assert_handshake_complete(m, s)
        assert_client_registered(m, s.peer)
    finally:
        b.stop_all()
