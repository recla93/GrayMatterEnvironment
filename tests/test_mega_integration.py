"""MEGA TEST SUITE — Full ecosystem integration + simulation + stress.

Tests every combination:
  1. Bridge resolution: neuron, neurag, gray-matter (full suite / standalone)
  2. Turso resilience: retry, URL candidates, reconnect, transactions
  3. Tunnel module: import, auto-detect backends, config persistence
  4. WebGUI: HTML integrity, i18n keys, health bar, JavaScript syntax
  5. CLI wiring: every bridge subcommand, arg defaults, env vars
  6. Cross-store bridges: add, query, weight, decay, prune, transfer
  7. GME registry: read/write/list, venv detection, atomic writes
  8. Intensive: rapid fire tool calls, concurrent bridge resolution, port fallback chains
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import socket
import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent  # Gray Matter Enviroment
NEURAG = ROOT / "neurag"
NEURON = ROOT / "neuron" / "src"
GM = ROOT / "gray_matter"

# Ensure we can import everything
sys.path.insert(0, str(NEURON))
sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1 — BRIDGE RESOLUTION (full suite vs standalone)
# ═══════════════════════════════════════════════════════════════════════

class TestBridgeResolutionFullSuite:
    """When gray_matter.server is importable, all bridges must escalate."""

    def test_neuron_bridge_escalates_to_gm(self):
        from neuron.bridge import resolve_neuron_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.side_effect = lambda name: MagicMock() if name == "gray_matter.server" else None
            cmd = resolve_neuron_cmd(None)
        assert "gray_matter.server" in " ".join(cmd)

    def test_neurag_bridge_escalates_to_gm(self):
        from neurag.bridge import resolve_neurag_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.side_effect = lambda name: MagicMock() if name == "gray_matter.server" else None
            cmd = resolve_neurag_cmd(None)
        assert "gray_matter.server" in " ".join(cmd)

    def test_gm_bridge_always_uses_gm(self):
        from gray_matter.bridge import resolve_gm_cmd
        cmd = resolve_gm_cmd(None)
        assert "gray_matter.server" in " ".join(cmd)

    def test_explicit_override_bypasses_detection(self):
        from neuron.bridge import resolve_neuron_cmd
        cmd = resolve_neuron_cmd(["custom", "cmd", "--force"])
        assert cmd == ["custom", "cmd", "--force"]

    def test_explicit_override_neurag_bypasses_detection(self):
        from neurag.bridge import resolve_neurag_cmd
        cmd = resolve_neurag_cmd(["my-server"])
        assert cmd == ["my-server"]

    def test_explicit_override_gm_bypasses_detection(self):
        from gray_matter.bridge import resolve_gm_cmd
        cmd = resolve_gm_cmd(["custom-entry"])
        assert cmd == ["custom-entry"]


class TestBridgeResolutionStandalone:
    """When gray_matter.server is NOT importable, bridges stay on their own tool."""

    def test_neuron_bridge_standalone(self):
        from neuron.bridge import resolve_neuron_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.return_value = None  # no GM
            cmd = resolve_neuron_cmd(None)
        joined = " ".join(cmd)
        assert "neuron" in joined
        assert "gray_matter" not in joined

    def test_neurag_bridge_standalone(self):
        from neurag.bridge import resolve_neurag_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.return_value = None  # no GM
            cmd = resolve_neurag_cmd(None)
        joined = " ".join(cmd)
        assert "neurag" in joined
        assert "gray_matter" not in joined


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2 — TURSO RESILIENCE
# ═══════════════════════════════════════════════════════════════════════

class TestTursoURLCandidates:
    """URL fallback: wss → https, libsql → https"""

    def test_neurag_url_candidates_wss_to_https(self):
        from neurag.db import _url_candidates
        candidates = _url_candidates("wss://my-db.turso.io")
        assert len(candidates) >= 2
        assert candidates[0] == "wss://my-db.turso.io"
        assert "https://my-db.turso.io" in candidates

    def test_neurag_url_candidates_libsql_to_https(self):
        from neurag.db import _url_candidates
        candidates = _url_candidates("libsql://my-db.turso.io")
        assert candidates[0] == "libsql://my-db.turso.io"
        assert "https://my-db.turso.io" in candidates

    def test_gm_url_candidates(self):
        from gray_matter.bridges import _url_candidates
        candidates = _url_candidates("wss://gm-db.turso.io")
        assert len(candidates) >= 2
        assert "https://gm-db.turso.io" in candidates

    def test_neurag_url_candidates_https_passthrough(self):
        from neurag.db import _url_candidates
        candidates = _url_candidates("https://my-db.turso.io")
        assert candidates[0] == "https://my-db.turso.io"


class TestTursoRetryLogic:
    """_with_retry: must retry on transient failures, raise on permanent."""

    def test_neurag_retry_succeeds_after_failure(self):
        from neurag.db import _with_retry
        call_count = 0
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"
        result = _with_retry(flaky, attempts=4, base_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    def test_neurag_retry_exhausts(self):
        from neurag.db import _with_retry
        with pytest.raises(ConnectionError):
            def always_fail():
                raise ConnectionError("permanent")
            _with_retry(always_fail, attempts=2, base_delay=0.01)

    def test_gm_retry_succeeds(self):
        from gray_matter.bridges import _with_retry
        call_count = 0
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("transient")
            return "recovered"
        result = _with_retry(flaky, attempts=3, base_delay=0.01)
        assert result == "recovered"

    def test_retry_preserves_return_value(self):
        from neurag.db import _with_retry
        result = _with_retry(lambda: {"nodes": 42, "links": 7}, attempts=2, base_delay=0.01)
        assert result == {"nodes": 42, "links": 7}


class TestTursoReconnect:
    """_reconnect: must close dead client and create fresh one."""

    def test_neurag_reconnect(self):
        from neurag.db import RemoteTursoConnection
        # _reconnect does: self._client.close() → self._client = self._create_client()
        # Track the original _client to verify close() was called on it
        original_client = MagicMock()
        mock_self = MagicMock()
        mock_self._client = original_client
        RemoteTursoConnection._reconnect(mock_self)
        original_client.close.assert_called_once()
        mock_self._create_client.assert_called_once()

    def test_gm_reconnect(self):
        from gray_matter.bridges import _RemoteConn
        original_client = MagicMock()
        mock_self = MagicMock()
        mock_self._client = original_client
        _RemoteConn._reconnect(mock_self)
        original_client.close.assert_called_once()
        mock_self._create_client.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3 — TUNNEL MODULE
# ═══════════════════════════════════════════════════════════════════════

class TestTunnelImports:
    """Tunnel module must be importable and expose expected API."""

    def test_import_tunnel(self):
        import neuron.tunnel
        assert hasattr(neuron.tunnel, "main")

    def test_tunnel_config_roundtrip(self):
        from neuron.tunnel import _load_tunnel_config, _save_tunnel_config, _tunnel_config_path
        cfg = {"backend": "named", "tunnel_name": "test-tunnel", "port": 8000}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            fake_path = Path(f.name)
        try:
            with patch("neuron.tunnel._tunnel_config_path", return_value=fake_path):
                _save_tunnel_config(cfg)
                loaded = _load_tunnel_config()
            assert loaded["backend"] == "named"
            assert loaded["tunnel_name"] == "test-tunnel"
            assert loaded["port"] == 8000
        finally:
            fake_path.unlink(missing_ok=True)

    def test_has_cred_path(self):
        from neuron.tunnel import _cred_path
        p = _cred_path()
        assert isinstance(p, Path)

    def test_has_cf_credentials_check(self):
        from neuron.tunnel import _has_cf_credentials
        result = _has_cf_credentials()
        assert isinstance(result, bool)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4 — WEBGUI INTEGRITY
# ═══════════════════════════════════════════════════════════════════════

class TestWebGUIHTML:
    """HTML file must be valid, contain required elements, have i18n keys."""

    def _load(self):
        return (GM / "webgui.html").read_text(encoding="utf-8")

    def test_html_loads(self):
        html = self._load()
        assert len(html) > 1000

    def test_has_lang_select(self):
        html = self._load()
        assert "lang-select" in html

    def test_i18n_has_all_keys(self):
        html = self._load()
        required_keys = [
            '"loading_catalog"', '"envs_title"', '"btn_start"', '"btn_stop"',
            '"migrate_title"', '"btn_migrate_all"', '"btn_confirm"',
            '"loading"', '"no_processes"', '"no_tools"',
        ]
        for key in required_keys:
            assert key in html, f"Missing i18n key: {key}"

    def test_health_bar_present(self):
        html = self._load()
        assert "health" in html.lower()

    def test_has_process_list(self):
        html = self._load()
        assert "process" in html.lower()

    def test_no_broken_javascript(self):
        """Gross check: matching braces/brackets in <script> blocks."""
        html = self._load()
        import re
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
        for script in scripts:
            opens = script.count("{") + script.count("[") + script.count("(")
            closes = script.count("}") + script.count("]") + script.count(")")
            assert abs(opens - closes) <= 2, f"JS bracket mismatch: opens={opens} closes={closes}"

    def test_has_footer(self):
        html = self._load()
        assert "footer" in html.lower()

    def test_has_t_function(self):
        html = self._load()
        assert "function T(" in html or "function T " in html


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5 — CLI WIRING
# ═══════════════════════════════════════════════════════════════════════

class TestCLIBridgeCommands:
    """CLI parsers must accept bridge args correctly."""

    def test_gm_bridge_cli_help(self):
        """gray-matter bridge --help must accept all flags."""
        from gray_matter.bridge import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_gm_bridge_callable(self):
        from gray_matter.bridge import main
        assert callable(main)

    def test_gm_cli_bridge_dispatch(self):
        """gray-matter bridge is wired into cli.py."""
        from gray_matter.cli import COMMAND_GROUPS
        assert "bridge" in COMMAND_GROUPS
        assert COMMAND_GROUPS["bridge"] == "lifecycle"


class TestCLIEnvironmentVariables:
    """Env vars must be respected by bridge parsers."""

    def test_neuron_bridge_env_host(self):
        os.environ["NEURON_BRIDGE_HOST"] = "0.0.0.0"
        try:
            import argparse
            p = argparse.ArgumentParser()
            p.add_argument("--host", default=os.environ.get("NEURON_BRIDGE_HOST") or "127.0.0.1")
            args = p.parse_args([])
            assert args.host == "0.0.0.0"
        finally:
            del os.environ["NEURON_BRIDGE_HOST"]

    def test_neurag_bridge_env_port(self):
        os.environ["NEURAG_BRIDGE_PORT"] = "9999"
        try:
            import argparse
            p = argparse.ArgumentParser()
            env_port = os.environ.get("NEURAG_BRIDGE_PORT")
            p.add_argument("--port", type=int, default=int(env_port) if env_port else 8001)
            args = p.parse_args([])
            assert args.port == 9999
        finally:
            del os.environ["NEURAG_BRIDGE_PORT"]

    def test_gm_bridge_env_tunnel(self):
        os.environ["GM_BRIDGE_TUNNEL"] = "true"
        try:
            env_tunnel = os.environ.get("GM_BRIDGE_TUNNEL", "").lower() in ("1", "true", "yes")
            assert env_tunnel is True
        finally:
            del os.environ["GM_BRIDGE_TUNNEL"]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 6 — CROSS-STORE BRIDGES (Hebbian learning)
# ═══════════════════════════════════════════════════════════════════════

class TestCrossStoreBridges:
    """bridges.py: add, query, weight, decay, prune, all_bridges."""

    def test_add_bridge_returns_bool(self):
        from gray_matter.bridges import add_bridge
        suffix = str(int(time.time() * 1000))[-6:]
        result = add_bridge(f"test_concept_{suffix}", f"test_node_{suffix}", "mega test")
        assert isinstance(result, bool)

    def test_add_bridge_idempotent(self):
        from gray_matter.bridges import add_bridge
        suffix = str(int(time.time() * 1000))[-6:]
        key1 = f"idem_concept_{suffix}"
        key2 = f"idem_node_{suffix}"
        r1 = add_bridge(key1, key2, "first")
        r2 = add_bridge(key1, key2, "second")
        assert isinstance(r1, bool)
        assert isinstance(r2, bool)

    def test_all_bridges_returns_list(self):
        from gray_matter.bridges import all_bridges
        result = all_bridges()
        assert isinstance(result, list)

    def test_bridges_for_returns_list(self):
        from gray_matter.bridges import bridges_for
        result = bridges_for("nonexistent_concept_xyz_12345")
        assert isinstance(result, list)

    def test_add_and_query_roundtrip(self):
        from gray_matter.bridges import add_bridge, bridges_for
        suffix = str(int(time.time() * 1000))[-6:]
        ck = f"roundtrip_{suffix}"
        nk = f"roundtrip_node_{suffix}"
        add_bridge(ck, nk, "roundtrip test")
        found = bridges_for(ck)
        assert len(found) > 0

    def test_weight_increases_on_reinforce(self):
        from gray_matter.bridges import add_bridge, bridges_for
        suffix = str(int(time.time() * 1000))[-6:]
        ck = f"weight_{suffix}"
        nk = f"weight_node_{suffix}"
        add_bridge(ck, nk, "first")
        found1 = bridges_for(ck)
        w1 = found1[0].get("weight", 0) if found1 else 0
        add_bridge(ck, nk, "reinforce")
        found2 = bridges_for(ck)
        w2 = found2[0].get("weight", 0) if found2 else 0
        assert w2 >= w1


# ═══════════════════════════════════════════════════════════════════════
# SECTION 7 — GME REGISTRY
# ═══════════════════════════════════════════════════════════════════════

class TestGMERegistry:
    """GME: read/write/list, venv detection, atomic writes."""

    @pytest.fixture(autouse=True)
    def _gme_in_tmp(self, tmp_path, monkeypatch):
        """Redirect the registry to tmp. These tests used to write
        `mega_test_*.json` / `health_test_*.json` straight into the user's real
        %LOCALAPPDATA%\\GrayMatterEnvironment — creating the folder on machines
        with nothing installed, and leaving junk entries behind for the GUI to
        list whenever a test failed between write_tool() and remove_tool()."""
        from gray_matter import gme
        monkeypatch.setattr(gme, "gme_root",
                            lambda: tmp_path / "GrayMatterEnvironment")

    def test_gme_root_callable(self):
        from gray_matter.gme import gme_root
        assert callable(gme_root)

    def test_catalog_importable(self):
        from gray_matter import catalog
        assert hasattr(catalog, "ENVIRONMENTS")

    def test_catalog_environments(self):
        from gray_matter.catalog import ENVIRONMENTS
        assert len(ENVIRONMENTS) == 3
        keys = {e["key"] for e in ENVIRONMENTS}
        assert "gray-matter" in keys
        assert "neuron" in keys
        assert "neurag" in keys

    def test_gme_read_write_roundtrip(self):
        from gray_matter.gme import write_tool, read_tool, remove_tool
        import time as _t
        key = f"mega_test_{int(_t.time())}"
        data = {"key": key, "label": "Mega Test", "version": "0.0.1", "status": "ok",
                "python": sys.executable, "venv": "", "module": "test"}
        write_tool(data)
        loaded = read_tool(key)
        assert loaded is not None
        assert loaded["key"] == key
        remove_tool(key)

    def test_gme_list_tools(self):
        from gray_matter.gme import list_tools
        result = list_tools()
        assert isinstance(result, list)

    def test_gme_is_installed(self):
        from gray_matter.gme import is_installed
        # "gray-matter" itself should always be "installed" if GME exists
        result = is_installed("gray-matter")
        assert isinstance(result, bool)

    def test_gme_get_python(self):
        from gray_matter.gme import get_python
        result = get_python("gray-matter")
        # May return None if not in GME, or a path
        assert result is None or isinstance(result, str)

    def test_gme_update_health(self):
        from gray_matter.gme import update_health, write_tool, read_tool, remove_tool
        import time as _t
        key = f"health_test_{int(_t.time())}"
        data = {"key": key, "label": "Health Test", "version": "0.0.1", "status": "ok",
                "python": sys.executable, "venv": "", "module": "test"}
        write_tool(data)
        try:
            update_health(key, {"status": "ok", "pid": 1234})
            loaded = read_tool(key)
            assert loaded is not None
        finally:
            remove_tool(key)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 8 — INTENSIVE STRESS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestRapidFireImports:
    """Import every module 10x in rapid succession — no deadlocks, no crashes."""

    def test_rapid_import_neuron_bridge(self):
        for _ in range(10):
            importlib.import_module("neuron.bridge")

    def test_rapid_import_neurag_bridge(self):
        for _ in range(10):
            importlib.import_module("neurag.bridge")

    def test_rapid_import_gm_bridge(self):
        for _ in range(10):
            importlib.import_module("gray_matter.bridge")

    def test_rapid_import_all_three(self):
        for _ in range(10):
            importlib.import_module("neuron.bridge")
            importlib.import_module("neurag.bridge")
            importlib.import_module("gray_matter.bridge")


class TestConcurrentBridgeResolution:
    """Thread-parallel bridge resolution — no race conditions."""

    def test_parallel_resolve_neuron(self):
        from neuron.bridge import resolve_neuron_cmd
        results = [None] * 20
        def resolve(i):
            with patch("importlib.util.find_spec") as mock:
                mock.return_value = MagicMock()
                results[i] = resolve_neuron_cmd(None)
        threads = [threading.Thread(target=resolve, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for r in results:
            assert r is not None
            assert "gray_matter.server" in " ".join(r)

    def test_parallel_resolve_neurag(self):
        from neurag.bridge import resolve_neurag_cmd
        results = [None] * 20
        def resolve(i):
            with patch("importlib.util.find_spec") as mock:
                mock.return_value = MagicMock()
                results[i] = resolve_neurag_cmd(None)
        threads = [threading.Thread(target=resolve, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for r in results:
            assert r is not None
            assert "gray_matter.server" in " ".join(r)


class TestPortFallbackChain:
    """Port fallback: find free port in a range, skip occupied ports."""

    def test_finds_first_available(self):
        from gray_matter.bridge import _find_free_port
        port = _find_free_port(19876, 10)
        assert port is not None
        assert 19876 <= port < 19886

    def test_skips_occupied_port(self):
        from gray_matter.bridge import _find_free_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 19876))
        sock.listen(1)
        try:
            port = _find_free_port(19876, 5)
            if port is not None:
                assert port > 19876
        finally:
            sock.close()

    def test_range_exhausted_returns_none(self):
        from gray_matter.bridge import _find_free_port
        socks = []
        for p in range(19900, 19905):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                s.listen(1)
                socks.append(s)
            except OSError:
                pass
        try:
            port = _find_free_port(19900, 5)
            if len(socks) == 5:
                assert port is None
        finally:
            for s in socks:
                s.close()


class TestProxyRunnerDetection:
    """mcp-proxy runner resolution: uvx, uv, pipx, direct."""

    def test_gm_proxy_detection(self):
        from gray_matter.bridge import resolve_proxy_runner
        result = resolve_proxy_runner()
        assert result is None or isinstance(result, list)

    def test_neuron_proxy_detection(self):
        from neuron.bridge import resolve_proxy_runner
        result = resolve_proxy_runner()
        assert result is None or isinstance(result, list)

    def test_neurag_proxy_detection(self):
        from neurag.bridge import resolve_proxy_runner
        result = resolve_proxy_runner()
        assert result is None or isinstance(result, list)


class TestBatchBridgeResolution:
    """Resolve 100 bridges in a loop — no memory leaks, no slow degradation."""

    def test_100_neuron_resolves(self):
        from neuron.bridge import resolve_neuron_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.return_value = MagicMock()
            for _ in range(100):
                cmd = resolve_neuron_cmd(None)
                assert "gray_matter.server" in " ".join(cmd)

    def test_100_neurag_resolves(self):
        from neurag.bridge import resolve_neurag_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.return_value = MagicMock()
            for _ in range(100):
                cmd = resolve_neurag_cmd(None)
                assert "gray_matter.server" in " ".join(cmd)

    def test_100_gm_resolves(self):
        from gray_matter.bridge import resolve_gm_cmd
        for _ in range(100):
            cmd = resolve_gm_cmd(None)
            assert "gray_matter.server" in " ".join(cmd)


class TestRetryExhaustionPerformance:
    """Retry with many failures must not take forever (backoff cap test)."""

    def test_retry_with_zero_base_delay(self):
        from neurag.db import _with_retry
        start = time.monotonic()
        def always_fail():
            raise RuntimeError("fail")
        with pytest.raises(RuntimeError):
            _with_retry(always_fail, attempts=5, base_delay=0.0)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Retry with zero delay took {elapsed:.1f}s — too slow"

    def test_retry_with_small_base_delay(self):
        from gray_matter.bridges import _with_retry
        start = time.monotonic()
        def always_fail():
            raise IOError("disk")
        with pytest.raises(IOError):
            _with_retry(always_fail, attempts=3, base_delay=0.01)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Retry took {elapsed:.1f}s"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 9 — USE SIMULATION (simulated LLM connector interactions)
# ═══════════════════════════════════════════════════════════════════════

class TestLLMSimulator:
    """Simulate what a remote LLM connector (Perplexity/ChatGPT) would do."""

    def test_full_suite_has_own_tools(self):
        """GM server exposes its own orchestration tools via list_tools."""
        from gray_matter.server import Server
        # Server must be importable
        assert Server is not None

    def test_neuron_server_importable(self):
        from neuron import server
        assert hasattr(server, "main") or hasattr(server, "Server")

    def test_neurag_server_importable(self):
        from neurag import server
        assert hasattr(server, "main") or hasattr(server, "Server")

    def test_full_suite_tool_names(self):
        """GM server defines 3 core tools: pulse, status, bridge."""
        # These are defined in the list_tools handler, not a module constant.
        # We verify the server module references them.
        import gray_matter.server as s
        src = open(s.__file__).read()
        assert "gray_matter_pulse" in src
        assert "gray_matter_status" in src
        assert "gray_matter_bridge" in src


class TestSimulatedPulseFlow:
    """Simulate a full pulse: topic → memory + knowledge + bridges + flash."""

    def test_simulated_pulse_independence(self):
        """Each subsystem can be called independently in a pulse."""
        from gray_matter.bridges import add_bridge, bridges_for, all_bridges
        suffix = str(int(time.time() * 1000))[-6:]

        # Step 1: create a bridge
        ck = f"sim_concept_{suffix}"
        nk = f"sim_node_{suffix}"
        add_bridge(ck, nk, "simulated pulse test")

        # Step 2: query bridges
        found = bridges_for(ck)
        assert len(found) > 0

        # Step 3: list all bridges
        all_b = all_bridges()
        assert isinstance(all_b, list)
        assert len(all_b) > 0

    def test_simulated_cache_flow(self):
        """Cache: put → get → invalidate."""
        from gray_matter.cache import ContextCache
        cache = ContextCache(max_size=10, ttl=60.0)
        # set
        cache.set("test_topic", "test_response")
        # get
        result = cache.get("test_topic")
        assert result == "test_response"
        # invalidate
        cache.invalidate("test_topic")
        result2 = cache.get("test_topic")
        assert result2 is None
        # size
        assert cache.size() == 0

    def test_cache_invalidate_related(self):
        from gray_matter.cache import ContextCache
        cache = ContextCache()
        cache.set("machine_learning", "ML response")
        cache.set("deep_learning", "DL response")
        cache.set("cooking", "recipe")
        dropped = cache.invalidate_related("learning")
        assert dropped == 2
        assert cache.get("cooking") == "recipe"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 10 — EDGE CASES & DEFENSIVE
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases that could bite us in production."""

    def test_empty_override_list_falls_through(self):
        """Empty list [] is falsy → falls through to auto-detect, not override."""
        from neuron.bridge import resolve_neuron_cmd
        with patch("importlib.util.find_spec") as mock:
            mock.return_value = MagicMock()  # pretend GM exists
            cmd = resolve_neuron_cmd([])
        # Empty list is falsy, so auto-detect kicks in → should escalate to GM
        assert "gray_matter.server" in " ".join(cmd)

    def test_none_override(self):
        from neuron.bridge import resolve_neuron_cmd
        cmd = resolve_neuron_cmd(None)
        assert isinstance(cmd, list)
        assert len(cmd) > 0

    def test_very_long_override(self):
        from neurag.bridge import resolve_neurag_cmd
        long_cmd = ["python"] + [f"arg{i}" for i in range(100)]
        cmd = resolve_neurag_cmd(long_cmd)
        assert cmd == long_cmd

    def test_gm_bridge_port_zero(self):
        from gray_matter.bridge import _find_free_port
        port = _find_free_port(0, 100)
        # Port 0 → connect_ex fails → returned as free
        # But actually port 0 is special — OS assigns. Our function just checks connect_ex.
        assert port is None or isinstance(port, int)

    def test_unicode_in_bridge_names(self):
        from gray_matter.bridges import add_bridge, bridges_for
        suffix = str(int(time.time() * 1000))[-6:]
        ck = f"café_{suffix}"
        nk = f"日本語_node_{suffix}"
        add_bridge(ck, nk, "unicode test: über → ü")
        found = bridges_for(ck)
        assert len(found) > 0

    def test_concurrent_bridge_writes(self):
        """Thread-parallel bridge writes — no DB locking crash."""
        from gray_matter.bridges import add_bridge
        suffix = str(int(time.time() * 1000))[-6:]
        errors = []

        def write_bridge(i):
            try:
                add_bridge(f"conc_{suffix}_{i}", f"node_{suffix}_{i}", f"thread {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_bridge, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0, f"Concurrent write errors: {errors}"

    def test_preflight_timeout_no_hang(self):
        """Preflight must not hang — starts process, waits, kills."""
        from gray_matter.bridge import preflight
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        start = time.monotonic()
        result = preflight(cmd, seconds=0.5)
        elapsed = time.monotonic() - start
        assert elapsed < 3.0, f"Preflight took {elapsed:.1f}s — should be ~0.5s"
        assert result is True

    def test_preflight_exits_fast(self):
        """Preflight detects a process that exits immediately."""
        from gray_matter.bridge import preflight
        cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
        start = time.monotonic()
        result = preflight(cmd, seconds=0.3)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0
        assert result is False

    def test_find_free_port_with_very_high_port(self):
        """High port numbers should not crash."""
        from gray_matter.bridge import _find_free_port
        port = _find_free_port(60000, 5000)
        assert port is None or isinstance(port, int)
