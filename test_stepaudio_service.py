import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from stepaudio_service import (StepAudioASR, parse_step_asr_sse, step_asr_url,
                               wav_to_pcm16_mono)


class StepAudioServiceTests(unittest.TestCase):
    def test_step_plan_asr_url(self):
        self.assertEqual(
            step_asr_url("https://api.stepfun.com/step_plan/v1"),
            "https://api.stepfun.com/step_plan/v1/audio/asr/sse")

    def test_sse_prefers_done_text(self):
        lines = [
            b'data: {"type":"transcript.text.delta","delta":"ni"}\n',
            ('data: ' + json.dumps({
                "type": "transcript.text.done", "text": "会议问题"
            }, ensure_ascii=False) + '\n').encode(),
        ]
        self.assertEqual(parse_step_asr_sse(lines), "会议问题")

    def test_wav_is_converted_to_mono_16k(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stereo.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\x01\x00\x01\x00" * 4800)
            pcm = wav_to_pcm16_mono(path)
            self.assertGreater(len(pcm), 0)
            self.assertEqual(len(pcm) % 2, 0)

    def test_request_uses_stepaudio_model_and_pcm(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                event = json.dumps({"type": "transcript.text.done", "text": "为什么"},
                                   ensure_ascii=False)
                return iter([f"data: {event}\n".encode()])

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 160)
            captured = {}

            def fake_urlopen(request, timeout):
                captured.update(json.loads(request.data.decode()))
                return FakeResponse()

            with patch("stepaudio_service.urlopen", side_effect=fake_urlopen):
                result = StepAudioASR({
                    "base_url": "https://api.stepfun.com/step_plan/v1",
                    "api_key": "test-key",
                }).transcribe_wav(path)
            self.assertEqual(result, "为什么")
            transcription = captured["audio"]["input"]["transcription"]
            self.assertEqual(transcription["model"], "stepaudio-2.5-asr")

    def test_silence_without_text_is_not_a_service_failure(self):
        class EmptyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter([b'data: {"type":"transcript.text.done","text":""}\n'])

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "silence.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 160)
            with patch("stepaudio_service.urlopen", return_value=EmptyResponse()):
                result = StepAudioASR({
                    "base_url": "https://api.stepfun.com/step_plan/v1",
                    "api_key": "test-key",
                }).transcribe_wav(path)
        self.assertEqual(result, "")

    def test_connection_uses_generated_wav(self):
        service = StepAudioASR({"base_url": "https://example.test", "api_key": "key"})
        with patch.object(service, "transcribe_wav", return_value="") as transcribe:
            result = service.test_connection()
            generated_path = transcribe.call_args.args[0]
            self.assertEqual(generated_path.suffix, ".wav")
        self.assertEqual(result, "StepAudio连接成功")


if __name__ == "__main__":
    unittest.main()
