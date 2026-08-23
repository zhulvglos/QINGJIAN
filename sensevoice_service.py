import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from voice_service import VoiceServiceError


DEFAULT_RUNTIME_ROOT = Path(r"D:\LightNoteSenseVoice")


class SenseVoiceTranscriber:
    """在隔离环境中运行 SenseVoice，避免模型依赖影响轻笺主进程。"""

    def __init__(self, runtime_root: Path = DEFAULT_RUNTIME_ROOT,
                 timeout_seconds: int = 1800):
        self.runtime_root = Path(runtime_root)
        self.timeout_seconds = timeout_seconds

    @property
    def python_path(self) -> Path:
        return self.runtime_root / "runtime" / "sensevoice_env" / "Scripts" / "python.exe"

    @property
    def worker_path(self) -> Path:
        return self.runtime_root / "sensevoice_worker.py"

    def model_status(self) -> Dict:
        required = {
            "独立环境": self.python_path,
            "转写程序": self.worker_path,
            "SenseVoice-Small": self.runtime_root / "models" / "SenseVoiceSmall" / "model.pt",
            "FSMN-VAD": self.runtime_root / "models" / "fsmn-vad" / "model.pt",
            "CAM++": self.runtime_root / "models" / "campplus-speaker" / "campplus_cn_common.bin",
        }
        missing = [name for name, path in required.items() if not path.exists()]
        return {"ready": not missing, "missing": missing, "paths": required}

    def _validate(self):
        status = self.model_status()
        if not status["ready"]:
            raise VoiceServiceError(
                "SenseVoice 运行文件不完整：" + "、".join(status["missing"]))

    def transcribe_tracks(self, tracks: Sequence[Tuple[Path, str, bool]]) -> List[Dict]:
        self._validate()
        temp_root = self.runtime_root / "runtime" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lightnote_sv_", dir=str(temp_root)) as folder:
            folder_path = Path(folder)
            worker_tracks = []
            for index, (source, label, diarize) in enumerate(tracks):
                source = Path(source)
                if not source.exists():
                    raise VoiceServiceError(f"待转写音频不存在：{source}")
                target = folder_path / f"track_{index}{source.suffix or '.wav'}"
                shutil.copy2(str(source), str(target))
                worker_tracks.append({"path": str(target), "label": label,
                                      "diarize": bool(diarize)})
            request_path = folder_path / "request.json"
            response_path = folder_path / "response.json"
            request_path.write_text(
                json.dumps({"tracks": worker_tracks}, ensure_ascii=False), encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "TEMP": str(temp_root), "TMP": str(temp_root),
                "MODELSCOPE_CACHE": str(self.runtime_root / "cache" / "modelscope"),
                "MODELSCOPE_HOME": str(self.runtime_root / "cache" / "modelscope"),
                "HF_HOME": str(self.runtime_root / "cache" / "huggingface"),
                "TORCH_HOME": str(self.runtime_root / "cache" / "torch"),
                "MODELSCOPE_OFFLINE": "1", "HF_HUB_OFFLINE": "1",
                "PYTHONIOENCODING": "utf-8",
            })
            process = subprocess.run(
                [str(self.python_path), str(self.worker_path),
                 "--request", str(request_path), "--response", str(response_path)],
                cwd=str(self.runtime_root), env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if not response_path.exists():
                detail = (process.stderr or process.stdout or "无子进程输出").strip()[-1200:]
                raise VoiceServiceError(f"SenseVoice 转写进程异常退出：{detail}")
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if process.returncode or not response.get("ok"):
                raise VoiceServiceError(response.get("error") or "SenseVoice 转写失败")
            return list(response.get("segments") or [])

    def transcribe(self, audio_path: Path, label: str,
                   diarize: bool = False) -> List[Dict]:
        return self.transcribe_tracks([(Path(audio_path), label, diarize)])

    def transcribe_dual(self, microphone_path: Path, system_path: Path) -> List[Dict]:
        return self.transcribe_tracks([
            (Path(microphone_path), "我", False),
            (Path(system_path), "会议方", True),
        ])


class SenseVoiceLiveSession:
    """常驻SenseVoice子进程；一次只处理一个短音频块。"""

    def __init__(self, runtime_root: Path = DEFAULT_RUNTIME_ROOT,
                 startup_timeout: int = 90, response_timeout: int = 120):
        self.transcriber = SenseVoiceTranscriber(runtime_root)
        self.startup_timeout = startup_timeout
        self.response_timeout = response_timeout
        self.process = None
        self._lock = threading.Lock()
        self._output_queue = queue.Queue()
        self._output_thread = None

    def _pump_output(self):
        stream = self.process.stdout if self.process else None
        try:
            if stream:
                for line in stream:
                    self._output_queue.put(line)
        finally:
            self._output_queue.put(None)

    def _read_json_response(self, timeout_seconds=None, stage="响应") -> Dict:
        logs = []
        deadline = (time.monotonic() + timeout_seconds
                    if timeout_seconds is not None else None)
        while self.process:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                detail = "；".join(logs[-4:])
                raise VoiceServiceError(
                    f"SenseVoice实时{stage}超过{timeout_seconds}秒"
                    + (f"：{detail}" if detail else ""))
            try:
                line = self._output_queue.get(timeout=remaining)
            except queue.Empty as exc:
                detail = "；".join(logs[-4:])
                raise VoiceServiceError(
                    f"SenseVoice实时{stage}超过{timeout_seconds}秒"
                    + (f"：{detail}" if detail else "")) from exc
            if line is None:
                break
            value = line.strip()
            try:
                payload = json.loads(value)
            except ValueError:
                if value:
                    logs.append(value)
                continue
            if isinstance(payload, dict) and (
                    "event" in payload or "ok" in payload or "error" in payload):
                return payload
        detail = "；".join(logs[-4:])
        raise VoiceServiceError("SenseVoice实时进程没有返回有效结果：" + detail)

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.transcriber._validate()
        runtime_root = self.transcriber.runtime_root
        temp_root = runtime_root / "runtime" / "temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "TEMP": str(temp_root), "TMP": str(temp_root),
            "MODELSCOPE_CACHE": str(runtime_root / "cache" / "modelscope"),
            "MODELSCOPE_HOME": str(runtime_root / "cache" / "modelscope"),
            "HF_HOME": str(runtime_root / "cache" / "huggingface"),
            "TORCH_HOME": str(runtime_root / "cache" / "torch"),
            "MODELSCOPE_OFFLINE": "1", "HF_HUB_OFFLINE": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        self.process = subprocess.Popen(
            [str(self.transcriber.python_path), str(self.transcriber.worker_path), "--server"],
            cwd=str(runtime_root), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._output_queue = queue.Queue()
        self._output_thread = threading.Thread(
            target=self._pump_output, name="sensevoice-output-reader", daemon=True)
        self._output_thread.start()
        try:
            payload = self._read_json_response(self.startup_timeout, "模型启动")
        except Exception:
            self.close()
            raise
        if payload.get("event") != "ready":
            self.close()
            raise VoiceServiceError("SenseVoice实时进程未就绪")

    def transcribe(self, audio_path: Path, label: str = "会议方") -> List[Dict]:
        self.start()
        request = {"tracks": [{"path": str(Path(audio_path)), "label": label,
                                "diarize": False}]}
        with self._lock:
            if not self.process or self.process.poll() is not None:
                raise VoiceServiceError("SenseVoice实时进程已经退出")
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            response = self._read_json_response(self.response_timeout, "识别")
        if not response.get("ok"):
            raise VoiceServiceError(response.get("error") or "SenseVoice实时转写失败")
        return list(response.get("segments") or [])

    def close(self):
        process, self.process = self.process, None
        if not process:
            return
        try:
            if process.poll() is None and process.stdin:
                process.stdin.write('{"command":"close"}\n')
                process.stdin.flush()
                process.wait(timeout=5)
        except Exception:
            process.terminate()
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError:
                    pass
