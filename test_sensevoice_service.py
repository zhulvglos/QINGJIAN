import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import sensevoice_worker
from sensevoice_service import SenseVoiceLiveSession, SenseVoiceTranscriber
from voice_service import VoiceServiceError


class SenseVoiceServiceTests(unittest.TestCase):
    def _runtime(self, root):
        for relative in (
            "runtime/sensevoice_env/Scripts/python.exe",
            "sensevoice_worker.py",
            "models/SenseVoiceSmall/model.pt",
            "models/fsmn-vad/model.pt",
            "models/campplus-speaker/campplus_cn_common.bin",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_tracks_are_copied_to_dedicated_runtime_and_result_is_returned(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._runtime(root)
            source = root / "source.wav"
            source.write_bytes(b"RIFFtest")

            def fake_run(command, **kwargs):
                request_path = Path(command[command.index("--request") + 1])
                response_path = Path(command[command.index("--response") + 1])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                self.assertEqual(request["tracks"][0]["label"], "会议方")
                self.assertTrue(request["tracks"][0]["diarize"])
                self.assertTrue(Path(request["tracks"][0]["path"]).exists())
                response_path.write_text(json.dumps({
                    "ok": True,
                    "segments": [{"start": 1, "end": 2,
                                  "speaker": "会议方1", "text": "你好"}],
                }, ensure_ascii=False), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("sensevoice_service.subprocess.run", side_effect=fake_run):
                result = SenseVoiceTranscriber(root).transcribe(source, "会议方", True)
            self.assertEqual(result[0]["speaker"], "会议方1")
            self.assertEqual(result[0]["text"], "你好")

    def test_dual_track_assigns_me_and_enables_meeting_diarization(self):
        transcriber = SenseVoiceTranscriber(Path("D:/unused"))
        with patch.object(transcriber, "transcribe_tracks", return_value=[]) as mocked:
            transcriber.transcribe_dual(Path("mic.wav"), Path("meeting.wav"))
        tracks = mocked.call_args.args[0]
        self.assertEqual(tracks[0], (Path("mic.wav"), "我", False))
        self.assertEqual(tracks[1], (Path("meeting.wav"), "会议方", True))

    def test_live_reader_ignores_logs_and_returns_ready_event(self):
        session = SenseVoiceLiveSession(Path("D:/unused"))
        session.process = object()
        session._output_queue.put("loading model\n")
        session._output_queue.put('{"event": "ready"}\n')
        self.assertEqual(
            session._read_json_response(0.1, "模型启动")["event"], "ready")

    def test_live_reader_applies_startup_timeout(self):
        session = SenseVoiceLiveSession(Path("D:/unused"))
        session.process = object()
        with self.assertRaisesRegex(VoiceServiceError, "模型启动超过"):
            session._read_json_response(0.01, "模型启动")

    def test_live_worker_only_loads_sensevoice_model(self):
        calls = []

        def fake_auto_model(**kwargs):
            calls.append(kwargs)
            return object()

        fake_funasr = types.SimpleNamespace(AutoModel=fake_auto_model)
        with patch.dict("sys.modules", {"funasr": fake_funasr}):
            sensevoice_worker._build_model(live=True)
            sensevoice_worker._build_model(live=False)
        self.assertNotIn("vad_model", calls[0])
        self.assertNotIn("spk_model", calls[0])
        self.assertTrue(calls[0]["disable_pbar"])
        self.assertIn("vad_model", calls[1])
        self.assertIn("spk_model", calls[1])


if __name__ == "__main__":
    unittest.main()
