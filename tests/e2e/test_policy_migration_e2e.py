"""End-to-end: a real SQLiteDB backend, driven through a live hivemind-core
policy chain in a hivescope topology, proving that a blacklist folded into
``Client.metadata`` by the v1→v2 schema migration is injected into the OVOS
session by ``OVOSAgentPolicy``.

This is the cross-repo seam the unit tests cannot cover on their own:

    legacy skill_blacklist column  --(plugin migrate)-->  Client.metadata
        --(OVOSAgentPolicy)-->  session.blacklisted_skills

Requires the policy stack (hivemind-core policy chain + OVOSAgentPolicy);
skipped when it is not installed.
"""
import importlib.util
import json
import tempfile
import time
from unittest import mock

import pytest

# Cross-repo deps absent from the DB plugin's own CI — skip the whole module
# there; it runs in the integration env that pins the policy stack + hivescope.
pytest.importorskip("hivemind_core.policy")
pytest.importorskip("hivemind_ovos_agent_plugin")
pytest.importorskip("hivescope")

def _hivescope_supports_db_injection() -> bool:
    """The master-side real-DB injection needs hivescope's MasterNode.create
    to accept a ``db=`` argument (added in hivescope > 0.3.0a1)."""
    if importlib.util.find_spec("hivescope") is None:
        return False
    import inspect
    from hivescope.node import MasterNode
    return "db" in inspect.signature(MasterNode.create).parameters


_HAS_POLICY = (
    importlib.util.find_spec("hivemind_core.policy") is not None
    and importlib.util.find_spec("hivemind_ovos_agent_plugin") is not None
)
pytestmark = [
    pytest.mark.skipif(
        not _HAS_POLICY, reason="needs hivemind-core policy chain + OVOSAgentPolicy"
    ),
    pytest.mark.skipif(
        not _hivescope_supports_db_injection(),
        reason="needs hivescope MasterNode.create(db=...) (> 0.3.0a1)",
    ),
]

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivemind_core.database import ClientDatabase  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402
from hivescope.assertions import assert_session_blacklists_injected  # noqa: E402

_SQLITE_PLUGIN = "hivemind-sqlite-db-plugin"


class _HivescopeDBAdapter:
    """Bridges hivescope's ``register_satellite`` (which passes
    ``can_escalate``/``can_propagate``/``can_broadcast`` to ``add_client``)
    to the real ``ClientDatabase`` whose ``add_client`` does not take them.
    Everything else delegates straight to the backing ClientDatabase, so the
    policy chain resolves real clients from the real sqlite plugin.
    """

    def __init__(self, cdb):
        object.__setattr__(self, "_cdb", cdb)

    def add_client(self, name, key, password=None, admin=False,
                   crypto_key=None, allowed_types=None, metadata=None,
                   intent_blacklist=None, skill_blacklist=None,
                   message_blacklist=None, can_escalate=True,
                   can_propagate=True, can_broadcast=True):
        # hivescope's MasterNode.register_satellite still passes
        # crypto_key through (v3-Noise-only removal, later phase); this
        # adapter accepts and drops it since the real ClientDatabase no
        # longer takes it.
        return self._cdb.add_client(
            name=name, key=key, admin=admin, allowed_types=allowed_types,
            password=password, metadata=metadata,
            intent_blacklist=intent_blacklist, skill_blacklist=skill_blacklist,
            message_blacklist=message_blacklist,
        )

    def __getattr__(self, item):
        return getattr(object.__getattribute__(self, "_cdb"), item)

    def __iter__(self):
        return iter(self._cdb)

    def __len__(self):
        return len(self._cdb)

    def __enter__(self):
        return self._cdb.__enter__()

    def __exit__(self, *a):
        return self._cdb.__exit__(*a)


def _reset_resolution_cache(hm_protocol):
    """Invalidate any cached pre-migration user resolution on every live
    connection so the policy re-reads the freshly-migrated metadata."""
    for attr in ("clients", "connections", "_clients", "_connections"):
        reg = getattr(hm_protocol, attr, None)
        if isinstance(reg, dict):
            for conn in reg.values():
                if hasattr(conn, "invalidate_user"):
                    conn.invalidate_user()


def _seed_legacy_blacklist(db, api_key: str, skills):
    """Rewrite a connected client's row into the legacy v1 shape: the
    blacklist lives in the top-level ``skill_blacklist`` column and the
    on-disk schema version is rolled back to v1, exactly what an operator's
    DB looks like before the plugin upgrade runs.
    """
    with db._write_lock:
        db.conn.execute(
            "UPDATE clients SET skill_blacklist = ? WHERE api_key = ?",
            (json.dumps(skills), api_key),
        )
        db.conn.execute("PRAGMA user_version = 1")
        db.conn.commit()


def test_migrated_skill_blacklist_reaches_session():
    tmp = tempfile.mkdtemp()
    with mock.patch("hivemind_sqlite_database.xdg_data_home", return_value=tmp):
        cdb = ClientDatabase(config={
            "module": _SQLITE_PLUGIN,
            _SQLITE_PLUGIN: {"name": "clients", "subfolder": "hivemind-core"},
        })

    b = TopologyBuilder()
    m = b.add_master("M0", db=_HivescopeDBAdapter(cdb), require_crypto=False)
    s = b.add_satellite(
        "S0", upstream=m, is_admin=False,
        allowed_types=["recognizer_loop:utterance"],
    )
    b.start_all()
    try:
        key = s.identity.access_key

        # Operator's DB carried a legacy top-level blacklist; the plugin
        # migration folds it into metadata on the next open/upgrade.
        _seed_legacy_blacklist(cdb.db, key, ["skill-weather"])
        cdb.db.migrate(from_version=1)
        _reset_resolution_cache(m.hm_protocol)

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
        s.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance",
                            {"utterances": ["what is the weather"]}),
        ))

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            time.sleep(0.02)
        assert seen, "utterance never reached the agent bus"

        assert_session_blacklists_injected(
            m, s,
            msg_type="recognizer_loop:utterance",
            expected_skills=["skill-weather"],
        )
    finally:
        b.stop_all()
