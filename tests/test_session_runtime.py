from __future__ import annotations

import json
import os
import tempfile
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from orchestrator_mcp import session_runtime


class SessionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_MCP_DATA": self.tmp.name,
                "ORCHESTRATOR_MCP_TRANSPORT": "stdio",
                "ORCHESTRATOR_MCP_SESSION_ID": "thread-a",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        session_runtime.unregister_current_process()
        self.env.stop()
        self.tmp.cleanup()

    def test_registers_current_stdio_process(self) -> None:
        record = session_runtime.register_current_process()

        self.assertEqual(record["session_id"], "thread-a")
        self.assertEqual(record["pid"], os.getpid())
        self.assertTrue(session_runtime.current_session_status()["registered"])
        self.assertTrue(session_runtime.registered_session_health("thread-a")["ok"])

    def test_old_cleanup_does_not_remove_replacement_record(self) -> None:
        first = session_runtime.register_current_process()
        path = Path(self.tmp.name) / "sessions" / "thread-a.json"
        replacement = session_runtime.register_current_process()

        session_runtime._unregister_session_record(path, first["instance_id"])

        current = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(current["instance_id"], replacement["instance_id"])

    def test_different_sessions_coexist(self) -> None:
        session_runtime.register_current_process()
        os.environ["ORCHESTRATOR_MCP_SESSION_ID"] = "thread-b"
        session_runtime.register_current_process()

        self.assertIsNotNone(session_runtime.read_session_record("thread-a"))
        self.assertIsNotNone(session_runtime.read_session_record("thread-b"))

    def test_non_stdio_transport_does_not_register(self) -> None:
        os.environ["ORCHESTRATOR_MCP_TRANSPORT"] = "streamable-http"

        self.assertIsNone(session_runtime.register_current_process())

    def test_invalid_session_id_is_rejected(self) -> None:
        os.environ["ORCHESTRATOR_MCP_SESSION_ID"] = "../escape"

        with self.assertRaisesRegex(ValueError, "missing or invalid"):
            session_runtime.register_current_process()

    def test_same_session_process_replaces_only_previous_owner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        wrapper = root / "codex-stdio-wrapper.sh"
        processes: list[subprocess.Popen[bytes]] = []

        def start(session_id: str) -> subprocess.Popen[bytes]:
            env = os.environ.copy()
            env.update(CODEX_THREAD_ID=session_id, ORCHESTRATOR_MCP_DATA=self.tmp.name)
            process = subprocess.Popen(
                [str(wrapper)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            processes.append(process)
            return process

        def wait_for_owner(session_id: str, pid: int) -> None:
            path = Path(self.tmp.name) / "sessions" / f"{session_id}.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    if json.loads(path.read_text(encoding="utf-8")).get("pid") == pid:
                        return
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                time.sleep(0.05)
            self.fail(f"session {session_id} did not register pid {pid}")

        try:
            old_a = start("process-a")
            process_b = start("process-b")
            wait_for_owner("process-a", old_a.pid)
            wait_for_owner("process-b", process_b.pid)
            replacement_a = start("process-a")
            wait_for_owner("process-a", replacement_a.pid)

            deadline = time.monotonic() + 5
            while old_a.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(old_a.poll(), 0)
            self.assertIsNone(process_b.poll())
            self.assertIsNone(replacement_a.poll())
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
