import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sensevoice_service import SenseVoiceTranscriber


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


if __name__ == "__main__":
    unittest.main()
