import multiprocessing
import queue
import time
import traceback
import wave
import audioop
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


class VoiceServiceError(RuntimeError):
    pass


_OPENCC_CONVERTER = None


def to_simplified_chinese(text: str) -> str:
    """统一转为简体中文；转换器仅在首次转写时加载。"""
    global _OPENCC_CONVERTER
    if _OPENCC_CONVERTER is None:
        try:
            from opencc import OpenCC
        except ImportError as exc:
            raise VoiceServiceError(
                "缺少OpenCC简繁转换组件，请重新运行 install_voice.bat。") from exc
        _OPENCC_CONVERTER = OpenCC("t2s")
    return _OPENCC_CONVERTER.convert(text or "")


def _audio_module():
    try:
        import pyaudiowpatch as pyaudio
        return pyaudio
    except ImportError as exc:
        raise VoiceServiceError(
            "缺少PyAudioWPatch。请运行 install_voice.bat 安装语音组件。") from exc


def list_audio_devices() -> Dict[str, List[Dict]]:
    """枚举麦克风与WASAPI回环端点，回环可捕获耳机或扬声器输出。"""
    pyaudio = _audio_module()
    microphones, outputs = [], []
    audio = pyaudio.PyAudio()
    try:
        loopback_indexes = set()
        if hasattr(audio, "get_loopback_device_info_generator"):
            for info in audio.get_loopback_device_info_generator():
                item = dict(info)
                loopback_indexes.add(int(item["index"]))
                outputs.append({
                    "index": int(item["index"]), "name": str(item.get("name", "输出设备")),
                    "rate": int(item.get("defaultSampleRate", 48000)),
                    "channels": max(1, int(item.get("maxInputChannels", 2))),
                })
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) <= 0 or index in loopback_indexes:
                continue
            if info.get("isLoopbackDevice"):
                continue
            microphones.append({
                "index": index, "name": str(info.get("name", "麦克风")),
                "rate": int(info.get("defaultSampleRate", 16000)),
                "channels": max(1, int(info.get("maxInputChannels", 1))),
            })
    finally:
        audio.terminate()
    return {"microphones": microphones, "outputs": outputs}


def preferred_device_label(mapping: Dict[str, Dict], saved_name: str,
                           preferred_terms) -> str:
    """按稳定设备名恢复选择；设备编号变化时使用名称关键词回退。"""
    saved = (saved_name or "").strip().casefold()
    if saved:
        for label, device in mapping.items():
            if str(device.get("name", "")).strip().casefold() == saved:
                return label
    terms = tuple(str(term).casefold() for term in preferred_terms if term)
    for label, device in mapping.items():
        name = str(device.get("name", "")).casefold()
        if terms and all(term in name for term in terms):
            return label
    return next(iter(mapping), "")


@dataclass
class RecordingResult:
    microphone_path: Optional[Path]
    system_path: Optional[Path]
    duration_seconds: float
    warnings: List[str]


def _append_recording_log(log_path, message):
    try:
        with open(str(log_path), "a", encoding="utf-8") as log:
            log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def _record_track_worker(device, path, force_mono, frames_per_buffer,
                         stop_event, pause_event, status_queue, byte_counter, log_path):
    """在独立进程持有一条音频流，隔离Windows音频驱动的原生崩溃。"""
    audio = stream = wav = None
    track = "microphone" if force_mono else "meeting"
    try:
        pyaudio = _audio_module()
        channels = 1 if force_mono else min(2, max(1, int(device.get("channels", 2))))
        rate = int(device.get("rate", 16000))
        audio = pyaudio.PyAudio()
        callback_error = []

        def capture_callback(in_data, _frame_count, _time_info, _status_flags):
            try:
                if in_data and not pause_event.is_set():
                    wav.writeframesraw(in_data)
                    with byte_counter.get_lock():
                        byte_counter.value += len(in_data)
                return None, pyaudio.paContinue
            except BaseException as exc:
                callback_error.append(f"{type(exc).__name__}: {exc}")
                return None, pyaudio.paAbort

        stream = audio.open(
            format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
            input_device_index=int(device["index"]),
            frames_per_buffer=frames_per_buffer,
            stream_callback=capture_callback,
            start=False,
        )
        wav = wave.open(str(path), "wb")
        wav.setnchannels(channels)
        wav.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
        wav.setframerate(rate)
        stream.start_stream()
        status_queue.put(("ready", track, ""))
        while not stop_event.wait(0.05):
            if not stream.is_active():
                detail = callback_error[0] if callback_error else "音频回调意外停止"
                raise VoiceServiceError(detail)
    except BaseException as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _append_recording_log(log_path, f"{track} error: {detail}\n{traceback.format_exc()}")
        try:
            status_queue.put(("error", track, detail))
        except Exception:
            pass
    finally:
        # 资源始终在创建它的进程和线程中关闭，避免跨线程关闭AUDIOSES流。
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception as exc:
                _append_recording_log(log_path, f"{track} stream close error: {exc}")
        if wav is not None:
            try:
                wav.close()
            except Exception as exc:
                _append_recording_log(log_path, f"{track} wav close error: {exc}")
        if audio is not None:
            try:
                audio.terminate()
            except Exception as exc:
                _append_recording_log(log_path, f"{track} audio terminate error: {exc}")


def _wav_has_frames(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() > 0 and audio.getnchannels() > 0
    except (OSError, EOFError, wave.Error):
        return False


@dataclass(frozen=True)
class MeetingUtteranceChunk:
    audio: bytes
    is_final: bool
    reason: str


class MeetingUtteranceSegmenter:
    """低延迟本地端点检测：说话后遇到停顿即输出完整PCM语句。"""

    def __init__(self, rate: int, channels: int, silence_seconds: float = 0.8,
                 max_seconds: float = 15.0, overlap_seconds: float = 4.0,
                 frame_ms: int = 100):
        self.rate = int(rate)
        self.channels = max(1, int(channels))
        self.frame_bytes = max(
            self.channels * 2,
            int(self.rate * self.channels * 2 * frame_ms / 1000))
        self.silence_frames = max(1, round(silence_seconds * 1000 / frame_ms))
        self.max_bytes = int(self.rate * self.channels * 2 * max_seconds)
        self.overlap_bytes = int(self.rate * self.channels * 2 * overlap_seconds)
        self.pre_roll_bytes = int(self.rate * self.channels * 2 * 0.4)
        self._pending = b""
        self._pre_roll = b""
        self._utterance = bytearray()
        self._active = False
        self._silent_run = 0
        self._voiced_frames = 0
        self._noise_floor = 60.0

    def _is_voice(self, frame: bytes) -> bool:
        level = audioop.rms(frame, 2)
        threshold = max(160.0, self._noise_floor * 3.0)
        voiced = level >= threshold
        if not self._active and not voiced:
            self._noise_floor = self._noise_floor * 0.95 + level * 0.05
        return voiced

    def feed_events(self, raw: bytes) -> List[MeetingUtteranceChunk]:
        self._pending += raw or b""
        completed = []
        while len(self._pending) >= self.frame_bytes:
            frame = self._pending[:self.frame_bytes]
            self._pending = self._pending[self.frame_bytes:]
            voiced = self._is_voice(frame)
            if not self._active:
                self._pre_roll = (self._pre_roll + frame)[-self.pre_roll_bytes:]
                if not voiced:
                    continue
                self._active = True
                self._utterance = bytearray(self._pre_roll)
                self._pre_roll = b""
                self._silent_run = 0
                self._voiced_frames = 1
                continue
            self._utterance.extend(frame)
            if voiced:
                self._silent_run = 0
                self._voiced_frames += 1
            else:
                self._silent_run += 1
            if self._silent_run >= self.silence_frames:
                if self._voiced_frames >= 3:
                    completed.append(MeetingUtteranceChunk(
                        bytes(self._utterance), True, "silence"))
                self._active = False
                self._utterance.clear()
                self._silent_run = 0
                self._voiced_frames = 0
                continue
            if len(self._utterance) >= self.max_bytes:
                completed.append(MeetingUtteranceChunk(
                    bytes(self._utterance), False, "max_duration"))
                overlap = bytes(self._utterance[-self.overlap_bytes:])
                self._utterance = bytearray(overlap)
                self._silent_run = 0
                self._voiced_frames = max(1, len(overlap) // self.frame_bytes)
        return completed

    def feed(self, raw: bytes) -> List[bytes]:
        """兼容旧调用；新实时链路使用 feed_events 获取结束原因。"""
        return [chunk.audio for chunk in self.feed_events(raw)]


class DualTrackRecorder:
    """同时录制麦克风和Windows WASAPI回环，保存为两条独立WAV。"""

    def __init__(self, output_dir: Path, frames_per_buffer: int = 1024):
        self.output_dir = Path(output_dir)
        self.frames_per_buffer = frames_per_buffer
        self._context = multiprocessing.get_context("spawn")
        self._stop = self._context.Event()
        self._paused = self._context.Event()
        self._processes = []
        self._status_queue = None
        self._microphone_bytes = self._context.Value("Q", 0)
        self._system_bytes = self._context.Value("Q", 0)
        self._started_at = 0.0
        self._pause_started = 0.0
        self._paused_seconds = 0.0
        self._error = None
        self.microphone_path = None
        self.system_path = None
        self.system_rate = 0
        self.system_channels = 0
        self.log_path = None

    @property
    def is_recording(self):
        return bool(self._processes) and not self._stop.is_set()

    @property
    def is_paused(self):
        return self._paused.is_set()

    @property
    def elapsed_seconds(self):
        if not self._started_at:
            return 0.0
        paused = self._paused_seconds
        if self._paused.is_set():
            paused += time.monotonic() - self._pause_started
        return max(0.0, time.monotonic() - self._started_at - paused)

    @property
    def track_bytes(self):
        return {"microphone": int(self._microphone_bytes.value),
                "meeting": int(self._system_bytes.value)}

    def snapshot_meeting_chunk(self, start_byte: int, min_seconds: float = 6.0):
        """从仍在写入的会议音轨中复制一个完整WAV片段，返回(path, 新偏移)。"""
        if not self.system_path or not self.system_rate or not self.system_channels:
            return None
        frame_bytes = self.system_channels * 2
        end_byte = int(self._system_bytes.value)
        start_byte = max(0, int(start_byte))
        minimum = int(self.system_rate * frame_bytes * min_seconds)
        if end_byte - start_byte < minimum:
            return None
        end_byte -= (end_byte - start_byte) % frame_bytes
        size = end_byte - start_byte
        try:
            with open(self.system_path, "rb") as source:
                source.seek(44 + start_byte)
                raw = source.read(size)
        except OSError:
            return None
        raw = raw[:len(raw) - (len(raw) % frame_bytes)]
        if len(raw) < minimum:
            return None
        chunk_dir = self.system_path.parent / "live_chunks"
        chunk_dir.mkdir(exist_ok=True)
        chunk_path = chunk_dir / f"meeting_{start_byte:012d}.wav"
        with wave.open(str(chunk_path), "wb") as audio:
            audio.setnchannels(self.system_channels)
            audio.setsampwidth(2)
            audio.setframerate(self.system_rate)
            audio.writeframes(raw)
        return chunk_path, start_byte + len(raw)

    def read_meeting_audio(self, start_byte: int):
        """读取录音过程中新增的会议方PCM数据，返回(raw, 新偏移)。"""
        if not self.system_path or not self.system_rate or not self.system_channels:
            return b"", int(start_byte)
        frame_bytes = self.system_channels * 2
        end_byte = int(self._system_bytes.value)
        start_byte = max(0, int(start_byte))
        end_byte -= (end_byte - start_byte) % frame_bytes
        if end_byte <= start_byte:
            return b"", start_byte
        try:
            with open(self.system_path, "rb") as source:
                source.seek(44 + start_byte)
                raw = source.read(end_byte - start_byte)
        except OSError:
            return b"", start_byte
        raw = raw[:len(raw) - (len(raw) % frame_bytes)]
        return raw, start_byte + len(raw)

    def write_live_meeting_chunk(self, raw: bytes, sequence: int) -> Path:
        """把会议PCM统一为16kHz单声道WAV，供在线或本地ASR识别。"""
        if not raw or not self.system_path:
            raise VoiceServiceError("没有可识别的会议方音频")
        pcm = raw
        if self.system_channels > 1:
            pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
        if self.system_rate != 16000:
            pcm, _state = audioop.ratecv(
                pcm, 2, 1, self.system_rate, 16000, None)
        chunk_dir = self.system_path.parent / "live_chunks"
        chunk_dir.mkdir(exist_ok=True)
        chunk_path = chunk_dir / f"utterance_{sequence:06d}.wav"
        with wave.open(str(chunk_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(pcm)
        return chunk_path

    def start(self, microphone: Dict, output: Dict) -> None:
        if self.is_recording:
            raise VoiceServiceError("录音已经开始")
        pyaudio = _audio_module()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        session_dir = self.output_dir / stamp
        session_dir.mkdir(parents=True, exist_ok=True)
        self.microphone_path = session_dir / "microphone.wav"
        self.system_path = session_dir / "meeting.wav"
        self.system_rate = int(output.get("rate", 48000))
        self.system_channels = min(2, max(1, int(output.get("channels", 2))))
        self.log_path = session_dir / "recording.log"
        self._stop.clear()
        self._paused.clear()
        self._paused_seconds = 0.0
        self._error = None
        self._microphone_bytes.value = 0
        self._system_bytes.value = 0
        self._status_queue = self._context.Queue()
        try:
            jobs = ((microphone, self.microphone_path, True, self._microphone_bytes),
                    (output, self.system_path, False, self._system_bytes))
            self._processes = [self._context.Process(
                target=_record_track_worker,
                args=(device, path, force_mono, self.frames_per_buffer,
                      self._stop, self._paused, self._status_queue, byte_counter,
                      self.log_path),
                name=f"lightnote-{'microphone' if force_mono else 'meeting'}",
                daemon=True)
                for device, path, force_mono, byte_counter in jobs]
            for process in self._processes:
                process.start()
            ready = set()
            deadline = time.monotonic() + 10
            while len(ready) < 2 and time.monotonic() < deadline:
                try:
                    event, track, detail = self._status_queue.get(timeout=0.2)
                except queue.Empty:
                    if any(process.exitcode is not None for process in self._processes):
                        break
                    continue
                if event == "ready":
                    ready.add(track)
                else:
                    raise VoiceServiceError(f"{track}录音设备启动失败：{detail}")
            if len(ready) != 2:
                raise VoiceServiceError("录音设备启动超时，请重新选择麦克风或会议声音设备")
            self._started_at = time.monotonic()
        except Exception:
            failures = self._stop_processes()
            if failures:
                _append_recording_log(self.log_path, "; ".join(failures))
            raise

    def pause(self):
        if self.is_recording and not self._paused.is_set():
            self._pause_started = time.monotonic()
            self._paused.set()

    def resume(self):
        if self.is_recording and self._paused.is_set():
            self._paused_seconds += time.monotonic() - self._pause_started
            self._paused.clear()

    def stop(self) -> RecordingResult:
        if not self._processes:
            raise VoiceServiceError("当前没有正在进行的录音")
        if self._paused.is_set():
            self.resume()
        duration = self.elapsed_seconds
        self._stop.set()
        failures = self._stop_processes()
        if failures:
            _append_recording_log(self.log_path, "; ".join(failures))
            raise VoiceServiceError("录音设备异常退出，轻笺已保护主程序。详情见：" + str(self.log_path))
        microphone_path = self.microphone_path if _wav_has_frames(self.microphone_path) else None
        system_path = self.system_path if _wav_has_frames(self.system_path) else None
        if not microphone_path and not system_path:
            raise VoiceServiceError("麦克风和会议声音均未捕获到有效音频，请检查设备选择")
        warnings = []
        if not microphone_path:
            warnings.append("麦克风未捕获到音频，本次仅转写会议声音")
        if not system_path:
            warnings.append("会议声音未捕获到音频，本次仅转写麦克风")
        return RecordingResult(microphone_path, system_path, duration, warnings)

    def _stop_processes(self):
        self._stop.set()
        failures = []
        for process in self._processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                failures.append(f"{process.name}停止超时")
            elif process.exitcode not in (0, None):
                failures.append(f"{process.name}异常退出（代码{process.exitcode}）")
        if self._status_queue is not None:
            while True:
                try:
                    event, track, detail = self._status_queue.get_nowait()
                except queue.Empty:
                    break
                if event == "error":
                    failures.append(f"{track}：{detail}")
            try:
                self._status_queue.close()
            except Exception:
                pass
        self._processes = []
        self._status_queue = None
        return failures


def format_transcript(segments: List[Dict]) -> str:
    lines = []
    for segment in segments:
        seconds = max(0, int(segment.get("start", 0)))
        timestamp = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        lines.append(f"[{timestamp}] {segment.get('speaker', '说话人')}：{segment.get('text', '').strip()}")
    return "\n".join(lines)
