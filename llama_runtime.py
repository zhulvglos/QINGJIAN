"""本地 llama.cpp 服务的启动、健康检查与生命周期管理。"""

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class LlamaRuntimeError(RuntimeError):
    pass


def discover_managed_runtime(project_dir, runtime_root=None, model_root=None):
    """发现轻笺既有的非C盘标准部署位置，不做全盘扫描。"""
    root = Path(project_dir).resolve().anchor
    if not root or root.upper().startswith("C:"):
        return None
    executable = ((Path(runtime_root) if runtime_root else Path(root) / "QingjianRuntime") /
                  "llama.cpp" / "llama-server.exe")
    model_dir = (Path(model_root) if model_root else
                 Path(root) / "QingjianData" / "models" / "llm")
    models = sorted(model_dir.glob("*.gguf"), key=lambda path: path.stat().st_size,
                    reverse=True) if model_dir.is_dir() else []
    if executable.is_file() and models:
        return {"executable": str(executable), "model_path": str(models[0])}
    return None


def _non_c_file(value, suffix):
    path = Path(str(value or "").strip()).expanduser()
    if not str(path):
        raise LlamaRuntimeError("尚未配置本地文件路径")
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise LlamaRuntimeError(f"本地文件路径无效：{exc}") from exc
    if resolved.drive.upper() == "C:":
        raise LlamaRuntimeError("本地大模型程序和模型文件不能放在C盘")
    if not resolved.is_file() or resolved.suffix.lower() not in suffix:
        raise LlamaRuntimeError(f"找不到有效文件：{resolved}")
    return resolved


def health_url(base_url):
    parsed = urlsplit(str(base_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LlamaRuntimeError("llama.cpp 接口地址无效")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}/health"


class LlamaRuntimeManager:
    def __init__(self, log_dir):
        self.log_dir = Path(log_dir)
        self._process = None
        self._log_file = None
        self._lock = threading.Lock()

    @property
    def owns_process(self):
        return self._process is not None and self._process.poll() is None

    def is_ready(self, base_url, timeout=1.5):
        try:
            request = urllib.request.Request(health_url(base_url), method="GET")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            return response.status == 200 and payload.get("status") in (None, "ok")
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def ensure_ready(self, *, executable, model_path, base_url, model_alias,
                     timeout=180, progress=None):
        if self.is_ready(base_url):
            return "本地 llama.cpp 已就绪"
        exe = _non_c_file(executable, {".exe"})
        model = _non_c_file(model_path, {".gguf"})
        parsed = urlsplit(str(base_url))
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise LlamaRuntimeError("自动启动只支持本机 llama.cpp 地址")
        port = parsed.port or 80
        with self._lock:
            if self.is_ready(base_url):
                return "本地 llama.cpp 已就绪"
            if not self.owns_process:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                if self.log_dir.resolve().drive.upper() == "C:":
                    raise LlamaRuntimeError("llama.cpp 日志目录不能位于C盘")
                log_path = self.log_dir / "llama-server.log"
                self._log_file = log_path.open("a", encoding="utf-8")
                command = [str(exe), "-m", str(model), "--host", "127.0.0.1",
                           "--port", str(port), "--alias", model_alias or model.stem,
                           "--device", "Vulkan0", "-ngl", "all"]
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                try:
                    self._process = subprocess.Popen(
                        command, cwd=str(exe.parent), stdout=self._log_file,
                        stderr=subprocess.STDOUT, creationflags=flags)
                except OSError as exc:
                    self._close_log()
                    raise LlamaRuntimeError(f"无法启动 llama.cpp：{exc}") from exc
        if progress:
            progress("正在加载本地大模型，请稍候……")
        deadline = time.monotonic() + max(5, float(timeout))
        while time.monotonic() < deadline:
            if self.is_ready(base_url):
                return "本地 llama.cpp 已启动并就绪"
            if self._process is not None and self._process.poll() is not None:
                code = self._process.returncode
                self._close_log()
                raise LlamaRuntimeError(
                    f"llama.cpp 启动后退出（代码 {code}），请查看 logs/llama-server.log")
            time.sleep(0.5)
        raise LlamaRuntimeError("本地模型加载超时，请查看 logs/llama-server.log")

    def _close_log(self):
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    def stop_owned(self):
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        self._close_log()
