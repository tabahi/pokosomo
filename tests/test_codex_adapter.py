import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.chat_manager import CodexAdapter, ChatManager, load_settings, save_settings


class CodexAdapterTests(unittest.TestCase):
    def test_settings_and_commands_use_codex_model_and_resume_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            project = Path(tmp) / "project"
            project.mkdir()
            with patch("server.chat_manager.SETTINGS_FILE", settings_file):
                save_settings({"engine": "codex", "codex_model": "test-model"})
                self.assertEqual(load_settings()["engine"], "codex")
                chat = ChatManager().create(project)

            self.assertEqual((chat["engine"], chat["model"]), ("codex", "test-model"))
            with patch("server.chat_manager.IN_CONTAINER", False):
                command = ChatManager()._command(chat, project, "Do the work")
            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertEqual(command[-1], "Do the work")
            self.assertIn('sandbox_mode="workspace-write"', command)
            self.assertIn('approval_policy="never"', command)
            # Flags that `codex exec resume` rejects must not be used.
            for flag in ("--ask-for-approval", "--sandbox", "--cd", "--add-dir"):
                self.assertNotIn(flag, command)

            with patch("server.chat_manager.IN_CONTAINER", True):
                in_container = ChatManager()._command(chat, project, "Do the work")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", in_container)
            self.assertNotIn('sandbox_mode="workspace-write"', in_container)

            chat["agent_session"] = "thread-123"
            resumed = ChatManager()._command(chat, project, "Continue")
            self.assertEqual(resumed[2:4], ["resume", "thread-123"])

    def test_jsonl_events_update_chat_text_file_changes_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            chat = {"agent_session": None, "model": "test-model"}
            message = {"parts": [], "thinking": False, "status": "running"}
            adapter = CodexAdapter(message, chat, project)

            adapter.handle({"type": "thread.started", "thread_id": "thread-456"})
            adapter.handle({"type": "item.started", "item": {
                "id": "command-1", "type": "command_execution",
                "command": "python analyze.py", "status": "in_progress",
            }})
            adapter.handle({"type": "item.completed", "item": {
                "id": "change-1", "type": "file_change", "status": "completed",
                "changes": [{"path": "results.md", "kind": "add"}],
            }})
            adapter.handle({"type": "item.completed", "item": {
                "id": "answer-1", "type": "agent_message", "text": "Finished.",
            }})
            adapter.handle({"type": "turn.completed"})

            self.assertEqual(chat["agent_session"], "thread-456")
            self.assertEqual(message["status"], "done")
            self.assertEqual(message["parts"][-1], {"type": "text", "text": "Finished."})
            self.assertTrue(any(part.get("file") == "results.md" for part in message["parts"]))
            self.assertTrue(adapter.files_touched)

    def test_failed_turn_surfaces_error(self):
        message = {"parts": [], "thinking": True, "status": "running"}
        adapter = CodexAdapter(message, {"agent_session": None, "model": ""}, Path("/project"))
        adapter.handle({"type": "turn.failed", "error": {"message": "Sign in required"}})
        self.assertEqual(message["status"], "error")
        self.assertEqual(message["error"], "Sign in required")
        self.assertFalse(message["thinking"])


if __name__ == "__main__":
    unittest.main()
