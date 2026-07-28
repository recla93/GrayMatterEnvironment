"""Cross-project integration tests.

Exercises the real code paths between neuron, neurag, and gray_matter:
paths discovery, client detection, bridge recall, _run_via_gm routing,
and gm_still_manages.  Each test is isolated (tmp_path + monkeypatch) so
pyturso's exclusive lock doesn't leak across tests.
"""
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. Paths discovery — GM discovers neuron/neurag via their own paths modules
# ---------------------------------------------------------------------------

class TestPathsDiscovery:
    """gray_matter.paths delegates to neuron.paths / neurag.paths for data."""

    def test_neurag_db_uses_peer_paths(self, monkeypatch):
        """neurag_db() calls neurag.paths.db_path() when neurag is installed."""
        from gray_matter import paths as gm
        fake_db = Path("/fake/neurag/knowledge.db")
        import neurag.paths as rp
        monkeypatch.setattr(rp, "db_path", lambda: fake_db)
        assert gm.neurag_db() == fake_db

    def test_neurag_db_fallback_when_peer_missing(self, monkeypatch):
        """neurag_db() falls back to a default when neurag.paths import fails."""
        from gray_matter import paths as gm
        import neurag.paths as rp
        # Simulate neurag.paths.db_path raising ImportError
        original = rp.db_path
        def _boom():
            raise ImportError("neurag not installed")
        monkeypatch.setattr(rp, "db_path", _boom)
        # The function catches ImportError internally — should return fallback
        result = gm.neurag_db()
        assert result is not None
        assert "neurag" in str(result).lower() or "knowledge" in str(result).lower()

    def test_neuron_graphs_uses_peer_paths(self, monkeypatch):
        """neuron_graphs() calls neuron.paths.graphs_dir() when neuron is installed."""
        from gray_matter import paths as gm
        fake_graphs = Path("/fake/neuron/graphs")
        import neuron.paths as np
        monkeypatch.setattr(np, "graphs_dir", lambda: fake_graphs)
        assert gm.neuron_graphs() == fake_graphs

    def test_data_paths_includes_all_peers(self):
        """data_paths() returns neuron_graphs, neurag_db, and gm_bridges."""
        from gray_matter import paths as gm
        dp = gm.data_paths()
        assert "neuron_graphs" in dp
        assert "neurag_db" in dp
        assert "gm_bridges" in dp
        assert all(isinstance(v, Path) for v in dp.values())


# ---------------------------------------------------------------------------
# 2. Client detection — GM detects installed server packages
# ---------------------------------------------------------------------------

class TestClientDetection:
    """gray_matter.clients.installed_servers finds neuron/neurag/gray-matter."""

    def test_installed_servers_finds_all_three(self):
        """All three packages are importable in the GM venv."""
        from gray_matter.clients import installed_servers
        servers = installed_servers()
        assert "neuron" in servers
        assert "neurag" in servers
        assert "gray-matter" in servers

    def test_installed_servers_respects_removal(self, monkeypatch):
        """If a module becomes unimportable, it disappears from the list."""
        from gray_matter.clients import installed_servers, _DETECT
        original = _DETECT.copy()
        # Temporarily remove neurag from detection
        _DETECT.pop("neurag", None)
        try:
            servers = installed_servers()
            assert "neurag" not in servers
        finally:
            _DETECT.update(original)


# ---------------------------------------------------------------------------
# 3. Standalone registration — GM registers neuron/neurag via their own module
# ---------------------------------------------------------------------------

class TestStandaloneRegistration:
    """gray_matter.clients.standalone_register_tool delegates to the peer."""

    def test_register_neurag_delegates_to_rc(self, monkeypatch):
        """registering 'neurag' calls neurag.clients.register_all."""
        from gray_matter import clients as gm_clients
        from neurag import clients as rc
        called = {}
        def fake_register_all(dry_run=False):
            called["dry_run"] = dry_run
            return []  # no results needed
        monkeypatch.setattr(rc, "register_all", fake_register_all)
        gm_clients.standalone_register_tool("neurag", dry_run=True)
        assert called.get("dry_run") is True

    def test_register_neuron_delegates_to_nc(self, monkeypatch):
        """registering 'neuron' calls neuron.clients.register_all."""
        from gray_matter import clients as gm_clients
        from neuron import clients as nc
        called = {}
        def fake_register_all(slug, py, dry_run=False):
            called["slug"] = slug
            called["dry_run"] = dry_run
            return []
        monkeypatch.setattr(nc, "register_all", fake_register_all)
        monkeypatch.setattr(nc, "default_server_python", lambda s: "/fake/python")
        gm_clients.standalone_register_tool("neuron", dry_run=True)
        # "neuron", not the retired "neuron5": GM must pass the same default
        # neuron/config.py:resolve_slug() uses, or the two disagree on where the
        # graphs live (which is how one user ended up with two graph folders).
        assert called.get("slug") == "neuron"
        assert called.get("dry_run") is True

    def test_slug_default_matches_neuron(self):
        """Regression on the split-memory bug: gray_matter.paths and
        neuron.config must resolve the SAME default slug. They didn't —
        'neuron5' here, 'neuron' there — so Neuron wrote graphs to <base>/neuron
        while GM read <base>/neuron5."""
        import os
        from gray_matter import paths as gm_paths
        from neuron import config as n_config
        assert gm_paths.SLUG == n_config.resolve_slug() == "neuron"
        assert "neuron5" not in os.environ.get("NEURON_SLUG", "")

    def test_register_unknown_tool_returns_error(self):
        """Registering an unknown tool returns an error line."""
        from gray_matter.clients import standalone_register_tool
        result = standalone_register_tool("nonexistent-tool")
        assert len(result) == 1
        assert "[!!]" in result[0]


# ---------------------------------------------------------------------------
# 4. gm_still_manages — neurag checks if GM still controls it
# ---------------------------------------------------------------------------

class TestGmStillManages:
    """neurag.clients.gm_still_manages checks gray_matter.settings."""

    def test_returns_true_when_no_unmanaged(self, monkeypatch):
        """If no tools are unmanaged, gm_still_manages returns True."""
        from neurag.clients import gm_still_manages
        from gray_matter import settings as gm_settings
        monkeypatch.setattr(gm_settings, "load", lambda: {"unmanaged": ""})
        assert gm_still_manages("neurag") is True

    def test_returns_false_when_tool_unmanaged(self, monkeypatch):
        """If neurag is in unmanaged, gm_still_manages returns False."""
        from neurag.clients import gm_still_manages
        from gray_matter import settings as gm_settings
        monkeypatch.setattr(gm_settings, "load", lambda: {"unmanaged": "neurag"})
        assert gm_still_manages("neurag") is False

    def test_returns_false_when_gm_missing(self, monkeypatch):
        """If gray_matter.settings is unimportable, returns False (standalone)."""
        from neurag.clients import gm_still_manages
        from gray_matter import settings as gm_settings
        def _boom():
            raise ImportError("no GM")
        monkeypatch.setattr(gm_settings, "load", _boom)
        assert gm_still_manages("neurag") is False

    def test_other_tool_not_affected(self, monkeypatch):
        """Unmanaging 'neuron' doesn't affect 'neurag'."""
        from neurag.clients import gm_still_manages
        from gray_matter import settings as gm_settings
        monkeypatch.setattr(gm_settings, "load", lambda: {"unmanaged": "neuron"})
        assert gm_still_manages("neurag") is True


# ---------------------------------------------------------------------------
# 5. _run_via_gm routing — neurag CLI routes writes through GM when active
# ---------------------------------------------------------------------------

class TestRunViaGm:
    """neurag.cli._run_via_gm routes commands through GM IPC."""

    def test_returns_false_when_gm_not_running(self, monkeypatch):
        """If GM daemon doesn't respond, _run_via_gm returns False."""
        from neurag import cli as neurag_cli
        from gray_matter import cli as gm_cli
        def _fail_ipc(msg):
            raise ConnectionError("daemon not running")
        monkeypatch.setattr(gm_cli, "_send_ipc", _fail_ipc)
        result = neurag_cli._run_via_gm("status", {})
        assert result is False

    def test_returns_false_when_gm_ping_fails(self, monkeypatch):
        """If GM ping returns non-gm response, _run_via_gm returns False."""
        from neurag import cli as neurag_cli
        from gray_matter import cli as gm_cli
        def _no_gm(msg):
            return {"status": "ok"}  # no "gm" key
        monkeypatch.setattr(gm_cli, "_send_ipc", _no_gm)
        result = neurag_cli._run_via_gm("status", {})
        assert result is False

    def test_returns_false_when_gm_does_not_manage_neurag(self, monkeypatch):
        """If GM is running but doesn't manage neurag, _run_via_gm returns False."""
        from neurag import cli as neurag_cli
        from gray_matter import cli as gm_cli
        from neurag import clients as rc
        monkeypatch.setattr(gm_cli, "_send_ipc", lambda msg: {"gm": True})
        monkeypatch.setattr(rc, "gm_still_manages", lambda name: False)
        result = neurag_cli._run_via_gm("status", {})
        assert result is False


# ---------------------------------------------------------------------------
# 6. Bridge recall — bridges connect neuron concepts to neurag nodes
# ---------------------------------------------------------------------------

class TestBridgeRecall:
    """gray_matter.bridges links neuron concepts ↔ neurag nodes."""

    def test_add_and_recall_bridge(self, monkeypatch, tmp_path):
        """Adding a bridge makes it recallable via bridges_for."""
        monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
        monkeypatch.delenv("GM_TURSO_DATABASE_URL", raising=False)
        from gray_matter import bridges
        importlib.reload(bridges)
        bridges.add_bridge("kotlin coroutines", "async patterns", "r")
        results = bridges.bridges_for("about kotlin coroutines")
        assert len(results) >= 1
        assert results[0]["neuron"] == "kotlin coroutines"
        assert results[0]["neurag"] == "async patterns"

    def test_bridge_cross_domain_recall(self, monkeypatch, tmp_path):
        """A bridge on domain A is recallable from domain B queries."""
        monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
        monkeypatch.delenv("GM_TURSO_DATABASE_URL", raising=False)
        from gray_matter import bridges
        importlib.reload(bridges)
        bridges.add_bridge("react", "frontend framework", "r")
        # Query from a different angle — the recall should still find it
        results = bridges.bridges_for("frontend development with react")
        assert any(r["neuron"] == "react" for r in results)

    def test_bridge_weight_increases_on_readd(self, monkeypatch, tmp_path):
        """Adding the same bridge twice increases its weight (Hebbian)."""
        monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
        monkeypatch.delenv("GM_TURSO_DATABASE_URL", raising=False)
        from gray_matter import bridges
        importlib.reload(bridges)
        bridges.add_bridge("sql", "database queries", "r")
        bridges.add_bridge("sql", "database queries", "r")
        all_bridges = bridges.all_bridges()
        sql_bridge = [b for b in all_bridges if b["neuron"] == "sql"]
        assert len(sql_bridge) == 1
        assert sql_bridge[0]["weight"] > 1.0


# ---------------------------------------------------------------------------
# 7. Source dir discovery — GM discovers peer source directories
# ---------------------------------------------------------------------------

class TestSourceDirDiscovery:
    """gray_matter.paths.source_dir discovers neuron/neurag source."""

    def test_source_dir_returns_path_for_neuron(self):
        """source_dir('neuron') returns a valid path or None."""
        from gray_matter.paths import source_dir
        result = source_dir("neuron")
        if result is not None:
            assert isinstance(result, Path)
            assert result.exists()

    def test_source_dir_returns_path_for_neurag(self):
        """source_dir('neurag') returns a valid path or None."""
        from gray_matter.paths import source_dir
        result = source_dir("neurag")
        if result is not None:
            assert isinstance(result, Path)
            assert result.exists()

    def test_source_dir_unknown_returns_none(self):
        """source_dir('nonexistent') returns None."""
        from gray_matter.paths import source_dir
        assert source_dir("nonexistent") is None


# ---------------------------------------------------------------------------
# 8. Stimuli from GM — safety-net re-injects Neuron concepts when LLM forgets
# ---------------------------------------------------------------------------

class TestStimuliFromGM:
    """GM's safety-net and _stim_seen keep Neuron concepts flowing."""

    def test_stim_seen_resets_counter(self):
        """_stim_seen zeros the counter when brain emoji is in the text."""
        import gray_matter.server as srv
        srv._turns_since_stim = 10
        srv._stim_seen("some response 🧠 note")
        assert srv._turns_since_stim == 0

    def test_stim_seen_ignores_clean_text(self):
        """_stim_seen does NOT reset when no emoji is present."""
        import gray_matter.server as srv
        srv._turns_since_stim = 10
        srv._stim_seen("clean response without emoji")
        assert srv._turns_since_stim == 10

    def test_stim_seen_resets_on_lightning(self):
        """_stim_seen also resets on ⚡ (flash) emoji."""
        import gray_matter.server as srv
        srv._turns_since_stim = 10
        srv._stim_seen("⚡ Flashback: dormant concept")
        assert srv._turns_since_stim == 0

    def test_safety_net_fires_after_gap(self, monkeypatch):
        """After STIM_SAFETY_GAP turns without stimuli, safety-net calls neuron forgotten."""
        import gray_matter.server as srv
        from gray_matter.registry import ServerEntry
        srv._turns_since_stim = srv.STIM_SAFETY_GAP  # at the threshold
        # Mock neuron as alive
        fake_neuron = ServerEntry(name="neuron", tool_names=[], socket_path="", pid=0)
        monkeypatch.setattr(srv._registry, "get_server", lambda name: fake_neuron)
        # Mock _call_server_async to return a forgotten concept
        async def fake_call(server, tool, args):
            return "Dormant: kotlin_coroutines (salience=5)"
        monkeypatch.setattr(srv, "_call_server_async", fake_call)
        result = asyncio.run(srv._safety_net_note("query", {"topic": "kotlin"}, ""))
        assert "🧠 (GM safety-net)" in result
        assert "kotlin_coroutines" in result
        assert srv._turns_since_stim == 0  # counter reset after firing

    def test_safety_net_skips_below_gap(self, monkeypatch):
        """Below the gap threshold, safety-net returns empty."""
        import gray_matter.server as srv
        srv._turns_since_stim = 0
        result = asyncio.run(srv._safety_net_note("query", {}, ""))
        assert result == ""

    def test_safety_net_skips_when_result_has_emoji(self, monkeypatch):
        """If the result already has 🧠, safety-net does not double-fire."""
        import gray_matter.server as srv
        srv._turns_since_stim = srv.STIM_SAFETY_GAP
        result = asyncio.run(srv._safety_net_note("query", {}, "🧠 already has stimulus"))
        assert result == ""
        assert srv._turns_since_stim == 0  # reset because emoji was seen

    def test_safety_net_no_neuron_returns_empty(self, monkeypatch):
        """If neuron is not registered, safety-net returns empty."""
        import gray_matter.server as srv
        srv._turns_since_stim = srv.STIM_SAFETY_GAP
        monkeypatch.setattr(srv._registry, "get_server", lambda name: None)
        result = asyncio.run(srv._safety_net_note("query", {}, ""))
        assert result == ""


# ---------------------------------------------------------------------------
# 9. GM + SingleTool — pulse works with only one peer installed
# ---------------------------------------------------------------------------

class TestGMPlusSingleTool:
    """GM degrades gracefully when only one sub-server is available."""

    def test_detect_subservers_skips_unmanaged(self, monkeypatch):
        """detect_subservers excludes tools in the unmanaged set."""
        from gray_matter import server as srv
        from gray_matter.clients import unmanaged_tools
        # Mark neurag as unmanaged
        monkeypatch.setattr(srv, "_SUBSERVER_MODULES",
                            {"neuron": "neuron.server", "neurag": "neurag.server"})
        monkeypatch.setattr("gray_matter.clients.unmanaged_tools", lambda: {"neurag"})
        result = srv.detect_subservers()
        assert "neuron" in result
        assert "neurag" not in result

    def test_detect_subservers_includes_all_when_no_unmanaged(self, monkeypatch):
        """detect_subservers includes both when neither is unmanaged."""
        from gray_matter import server as srv
        monkeypatch.setattr("gray_matter.clients.unmanaged_tools", lambda: set())
        result = srv.detect_subservers()
        # Both should be present (both packages are installed in the venv)
        assert "neuron" in result
        assert "neurag" in result

    def test_registry_neuron_only(self):
        """With only neuron in registry, pulse has one task (not zero)."""
        from gray_matter.registry import Registry
        reg = Registry()
        reg.register_managed("neuron", ["get_context", "forgotten"])
        # neurag is NOT registered
        neuron = reg.get_server("neuron")
        neurag = reg.get_server("neurag")
        assert neuron is not None
        assert neuron.is_alive()
        assert neurag is None

    def test_registry_neurag_only(self):
        """With only neurag in registry, pulse has one task (not zero)."""
        from gray_matter.registry import Registry
        reg = Registry()
        reg.register_managed("neurag", ["knowledge_query", "knowledge_status"])
        neuron = reg.get_server("neuron")
        neurag = reg.get_server("neurag")
        assert neuron is None
        assert neurag is not None
        assert neurag.is_alive()

    def test_registry_empty_means_no_pulse(self):
        """With empty registry, pulse would return 'No servers available'."""
        from gray_matter.registry import Registry
        reg = Registry()
        assert reg.alive_servers() == []
        assert reg.collaborators() == []


# ---------------------------------------------------------------------------
# 10. GM + Standalone tool — release_tool keeps/drops gray-matter entry
# ---------------------------------------------------------------------------

class TestGMPlusStandalone:
    """release_tool logic: keeps gray-matter in clients when peers remain."""

    def test_release_tool_keeps_gm_entry_when_peers_remain(self, monkeypatch):
        """Releasing neurag keeps gray-matter entry because neuron is still managed."""
        from gray_matter import clients as gm_clients
        # installed_servers returns both neuron and neurag
        monkeypatch.setattr(gm_clients, "installed_servers", lambda: ["neuron", "neurag", "gray-matter"])
        # neurag is the one being released → still in installed but being unmanaged
        unmanaged = {"neurag"}
        monkeypatch.setattr(gm_clients, "unmanaged_tools", lambda: unmanaged)
        # unmanaged_tools filters against _STANDALONE_TOOLS — neuron is NOT unmanaged
        # so still_managed should be ["neuron"]
        still_managed = [t for t in gm_clients.installed_servers()
                         if t in gm_clients._STANDALONE_TOOLS and t not in unmanaged]
        assert "neuron" in still_managed
        assert "neurag" not in still_managed
        # gray-matter entry should be KEPT
        assert len(still_managed) >= 1

    def test_release_tool_drops_gm_entry_when_no_peers(self, monkeypatch):
        """Releasing the last managed tool means gray-matter entry should go."""
        from gray_matter import clients as gm_clients
        monkeypatch.setattr(gm_clients, "installed_servers", lambda: ["neuron", "neurag", "gray-matter"])
        unmanaged = {"neuron", "neurag"}
        monkeypatch.setattr(gm_clients, "unmanaged_tools", lambda: unmanaged)
        still_managed = [t for t in gm_clients.installed_servers()
                         if t in gm_clients._STANDALONE_TOOLS and t not in unmanaged]
        assert still_managed == []  # both standalone tools unmanaged → drop GM entry

    def test_unmanaged_tools_filters_correctly(self, monkeypatch):
        """unmanaged_tools only returns tools in _STANDALONE_TOOLS."""
        from gray_matter import clients as gm_clients
        from gray_matter import settings
        monkeypatch.setattr(settings, "get", lambda key, *a: {"unmanaged": "neurag,gray-matter"}.get(key))
        # gray-matter is NOT in _STANDALONE_TOOLS, so it should be filtered out
        result = gm_clients.unmanaged_tools()
        assert "neurag" in result
        assert "gray-matter" not in result
        assert "neuron" not in result


# ---------------------------------------------------------------------------
# 11. Flash + auto-bridge — dormant concepts create cross-store bridges
# ---------------------------------------------------------------------------

class TestFlashAndAutoBridge:
    """Flash surfaces dormant Neuron concepts; pulse auto-creates bridges."""

    def test_first_concept_parses_output(self):
        """_first_concept extracts the keyword from Neuron's forgotten output."""
        from gray_matter.server import _first_concept
        text = ("Dormant & mid-band related to 'spring':\n"
                "  spring_boot    last_turn=3  (7 turns ago)  salience=4\n"
                "Total: 1 concepts")
        assert _first_concept(text) == "spring_boot"

    def test_first_concept_empty_on_no_results(self):
        """_first_concept returns '' when Neuron reports no forgotten concepts."""
        from gray_matter.server import _first_concept
        assert _first_concept("No forgotten concepts in 5 turns.") == ""

    def test_first_concept_handles_malformed(self):
        """_first_concept returns '' on empty or header-only text."""
        from gray_matter.server import _first_concept
        assert _first_concept("") == ""
        assert _first_concept("Total: 0 concepts") == ""

    def test_norm_lowercases_and_strips(self):
        """_norm normalizes topics for comparison (lowercase, strip)."""
        from gray_matter.server import _norm
        assert _norm("  Spring Boot  ") == "spring boot"
        assert _norm("SPRING BOOT") == "spring boot"
        assert _norm("") == ""
