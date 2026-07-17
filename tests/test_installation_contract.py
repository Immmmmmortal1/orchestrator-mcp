from __future__ import annotations

import plistlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.install_local import (
    MCP_LABEL,
    WEBUI_LABEL,
    _bootstrap_after_unload,
    _wait_for_listener,
    build_codex_block,
    build_launchd_plist,
    replace_codex_block,
)


class InstallationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("/Users/xiaomao11/project/orchestrator-mcp")

    def test_codex_block_uses_canonical_stdio_wrapper(self) -> None:
        block = build_codex_block(self.root)

        self.assertIn(str(self.root / "codex-stdio-wrapper.sh"), block)
        self.assertIn('ORCHESTRATOR_MCP_TRANSPORT = "stdio"', block)
        self.assertNotIn("/Users/xiaomao11/orchestrator-mcp", block)

    def test_replace_codex_block_preserves_neighboring_servers(self) -> None:
        original = """[mcp_servers.before]\ncommand = \"before\"\n\n[mcp_servers.orchestrator_mcp]\ncommand = \"old\"\n\n[mcp_servers.orchestrator_mcp.env]\nPYTHONPATH = \"old\"\n\n[mcp_servers.after]\ncommand = \"after\"\n"""

        updated = replace_codex_block(original, build_codex_block(self.root))

        self.assertEqual(updated.count("[mcp_servers.orchestrator_mcp]"), 1)
        self.assertIn('[mcp_servers.before]', updated)
        self.assertIn('[mcp_servers.after]', updated)
        self.assertIn(str(self.root), updated)

    def test_launchd_plists_use_canonical_root_and_separate_ports(self) -> None:
        mcp = build_launchd_plist(self.root, MCP_LABEL, webui=False)
        webui = build_launchd_plist(self.root, WEBUI_LABEL, webui=True)

        self.assertEqual(mcp["WorkingDirectory"], str(self.root))
        self.assertEqual(webui["WorkingDirectory"], str(self.root))
        self.assertEqual(mcp["EnvironmentVariables"]["ORCHESTRATOR_MCP_PORT"], "18067")
        self.assertEqual(webui["EnvironmentVariables"]["ORCHESTRATOR_WEBUI_PORT"], "18068")
        self.assertEqual(mcp["EnvironmentVariables"]["ORCHESTRATOR_MCP_TRANSPORT"], "streamable-http")

    def test_plists_are_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "service.plist"
            with path.open("wb") as handle:
                plistlib.dump(build_launchd_plist(self.root, MCP_LABEL, webui=False), handle)
            self.assertEqual(plistlib.loads(path.read_bytes())["Label"], MCP_LABEL)

    def test_bootstrap_waits_until_launchd_job_is_unloaded(self) -> None:
        from unittest import mock

        results = [
            mock.Mock(returncode=0, stdout="still loaded", stderr=""),
            mock.Mock(returncode=113, stdout="", stderr="not found"),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ]
        with mock.patch("scripts.install_local._run", side_effect=results) as run:
            _bootstrap_after_unload("501", MCP_LABEL, Path("/tmp/service.plist"), timeout=0.2)

        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[-1].args[:2], ("launchctl", "bootstrap"))

    def test_legacy_migration_does_not_overwrite_canonical_provider_config(self) -> None:
        from unittest import mock
        from scripts.install_local import _migrate_legacy_data

        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as legacy_tmp:
            root = Path(root_tmp)
            legacy = Path(legacy_tmp)
            (root / "data").mkdir()
            (legacy / "data").mkdir()
            target = root / "data/providers.local.json"
            source = legacy / "data/providers.local.json"
            target.write_text(json.dumps({"source": "canonical"}), encoding="utf-8")
            source.write_text(json.dumps({"source": "legacy"}), encoding="utf-8")

            with mock.patch("scripts.install_local.LEGACY_ROOT", legacy):
                migrated = _migrate_legacy_data(root, "test")

            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["source"], "canonical")
            self.assertNotIn("providers.local.json", migrated)

    def test_wait_for_listener_polls_until_port_is_ready(self) -> None:
        from unittest import mock

        with mock.patch(
            "scripts.install_local._port_listener_pids", side_effect=[[], [1234]]
        ) as listeners:
            _wait_for_listener(18067, timeout=0.2)

        self.assertEqual(listeners.call_count, 2)


if __name__ == "__main__":
    unittest.main()
