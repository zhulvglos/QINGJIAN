import audioop
import base64
import json
import tempfile
import wave
from pathlib import Path
from typing import Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from voice_service import VoiceServiceError, to_simplified_chinese


def step_asr_url(base_url: str) -> str:
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        raise VoiceServiceError("请先填写Step Plan接口地址")
    if url.endswith("/audio/asr/sse"):
        return url
    return url + "/audio/asr/sse"


def wav_to_pcm16_mono(audio_path: Path, target_rate: int = 16000) -> bytes:
    try:
        with wave.open(str(audio_path), "rb") as audio:
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            rate = audio.getframerate()
            raw = audio.readframes(audio.getnframes())
    except (OSError, EOFError, wave.Error) as exc:
        raise VoiceServiceError("StepAudio只能处理有效的WAV音频片段") from exc
    if width != 2:
        raw = audioop.lin2lin(raw, width, 2)
        width = 2
    if channels > 1:
        raw = audioop.tomono(raw, width, 0.5, 0.5)
    if rate != target_rate:
        raw, _state = audioop.ratecv(raw, width, 1, rate, target_rate, None)
    return raw


def parse_step_asr_sse(lines) -> str:
    final_text = ""
    deltas = []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        value = line[5:].strip()
        if not value or value == "[DONE]":
            continue
        try:
            event = json.loads(value)
        except ValueError:
            continue
        event_type = event.get("type")
        if event_type == "transcript.text.delta" and event.get("delta"):
            deltas.append(str(event["delta"]))
        elif event_type == "transcript.text.done":
            final_text = str(event.get("text") or "")
        elif event_type == "error":
            raise VoiceServiceError("StepAudio识别失败：" + str(event.get("message") or "未知错误"))
    return to_simplified_chinese(final_text or "".join(deltas)).strip()


class StepAudioASR:
    def __init__(self, config: Dict):
        self.config = dict(config or {})

    def transcribe_wav(self, audio_path: Path) -> str:
        token = str(self.config.get("api_key") or "").strip()
        if not token:
            raise VoiceServiceError("请先在设置中保存Step Plan API Key")
        pcm = wav_to_pcm16_mono(Path(audio_path))
        if not pcm:
            return ""
        payload = {
            "audio": {
                "data": base64.b64encode(pcm).decode("ascii"),
                "input": {
                    "transcription": {
                        "model": "stepaudio-2.5-asr",
                        "language": "zh",
                        "enable_itn": True,
                    },
                    "format": {
                        "type": "pcm", "codec": "pcm_s16le",
                        "rate": 16000, "bits": 16, "channel": 1,
                    },
                },
            }
        }
        request = Request(
            step_asr_url(self.config.get("base_url", "")),
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            with urlopen(request, timeout=int(self.config.get("timeout", 90))) as response:
                text = parse_step_asr_sse(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code in (401, 403):
                raise VoiceServiceError("StepAudio鉴权失败，请检查API Key") from exc
            if exc.code == 429:
                raise VoiceServiceError("StepAudio额度不足或请求过于频繁") from exc
            raise VoiceServiceError(f"StepAudio返回HTTP {exc.code}：{detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise VoiceServiceError("StepAudio网络连接失败或请求超时") from exc
        return text

    def test_connection(self) -> str:
        """用短静音片段验证鉴权、额度及ASR端点，不评价识别准确率。"""
        with tempfile.TemporaryDirectory(prefix="lightnote-stepaudio-") as folder:
            path = Path(folder) / "connection-test.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 16000)
            self.transcribe_wav(path)
        return "StepAudio连接成功"
