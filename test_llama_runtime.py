import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from llama_runtime import (LlamaRuntimeError, LlamaRuntimeManager,
                           discover_managed_runtime, health_url)


class LlamaRuntimeTests(unittest.TestCase):
    @staticmethod
    def temp_parent():
        parent = Path(__file__).resolve().parent / "cache"
        parent.mkdir(exist_ok=True)
        return parent

    def test_health_url_uses_server_root(self):
        self.assertEqual(
            health_url("http://127.0.0.1:8080/v1"),
            "http://127.0.0.1:8080/health")

    def test_discovery_returns_none_outside_managed_layout(self):
        with tempfile.TemporaryDirectory(dir=self.temp_parent()) as folder:
            root = Path(folder)
            self.assertIsNone(discover_managed_runtime(
                folder, runtime_root=root / "runtime", model_root=root / "models"))

    def test_missing_runtime_path_has_specific_error(self):
        with tempfile.TemporaryDirectory(dir=self.temp_parent()) as folder:
            manager = LlamaRuntimeManager(Path(folder) / "logs")
            with self.assertRaisesRegex(LlamaRuntimeError, "找不到有效文件"):
                manager.ensure_ready(
                    executable=Path(folder) / "llama-server.exe",
                    model_path=Path(folder) / "model.gguf",
                    base_url="http://127.0.0.1:65530/v1",
                    model_alias="local", timeout=0.1)

    def test_remote_address_is_not_auto_started(self):
        with tempfile.TemporaryDirectory(dir=self.temp_parent()) as folder:
            root = Path(folder)
            exe, model = root / "server.exe", root / "model.gguf"
            exe.write_bytes(b"x")
            model.write_bytes(b"x")
            manager = LlamaRuntimeManager(root / "logs")
            with self.assertRaisesRegex(LlamaRuntimeError, "只支持本机"):
                manager.ensure_ready(
                    executable=exe, model_path=model,
                    base_url="http://192.168.1.2:8080/v1",
                    model_alias="local", timeout=0.1)

    def test_starts_one_hidden_server_and_waits_until_ready(self):
        with tempfile.TemporaryDirectory(dir=self.temp_parent()) as folder:
            root = Path(folder)
            exe, model = root / "llama-server.exe", root / "model.gguf"
            exe.write_bytes(b"x")
            model.write_bytes(b"x")
            manager = LlamaRuntimeManager(root / "logs")
            process = Mock()
            process.poll.return_value = None
            with patch.object(manager, "is_ready", side_effect=[False, False, True]), \
                    patch("llama_runtime.subprocess.Popen", return_value=process) as popen, \
                    patch("llama_runtime.time.sleep"):
                result = manager.ensure_ready(
                    executable=exe, model_path=model,
                    base_url="http://127.0.0.1:8080/v1",
                    model_alias="qwen-local", timeout=1)
            self.assertIn("已启动", result)
            self.assertEqual(popen.call_count, 1)
            command = popen.call_args.args[0]
            self.assertIn(str(model), command)
            self.assertIn("qwen-local", command)
            manager.stop_owned()


if __name__ == "__main__":
    unittest.main()
