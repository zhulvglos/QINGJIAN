import tempfile
import unittest
from pathlib import Path

from voice_service import (_wav_has_frames, format_transcript,
                           MeetingUtteranceSegmenter, preferred_device_label,
                           to_simplified_chinese)


class VoiceServiceTests(unittest.TestCase):
    def test_meeting_vad_emits_after_speech_and_pause(self):
        segmenter = MeetingUtteranceSegmenter(
            16000, 1, silence_seconds=0.8, max_seconds=15, overlap_seconds=4)
        silence = b"\x00\x00" * int(16000 * 0.4)
        speech = b"\xe8\x03" * int(16000 * 0.6)
        trailing = b"\x00\x00" * int(16000 * 0.8)
        completed = segmenter.feed(silence + speech + trailing)
        self.assertEqual(len(completed), 1)
        self.assertGreater(len(completed[0]), len(speech))

    def test_meeting_vad_ignores_silence(self):
        segmenter = MeetingUtteranceSegmenter(16000, 1)
        self.assertEqual(segmenter.feed(b"\x00\x00" * 16000), [])

    def test_meeting_vad_caps_long_utterance(self):
        segmenter = MeetingUtteranceSegmenter(
            16000, 1, silence_seconds=0.8, max_seconds=15, overlap_seconds=4)
        speech = b"\xe8\x03" * int(16000 * 16)
        completed = segmenter.feed(speech)
        self.assertEqual(len(completed), 1)
        self.assertGreaterEqual(len(completed[0]), 16000 * 2 * 15)

    def test_meeting_vad_marks_forced_and_natural_endings(self):
        segmenter = MeetingUtteranceSegmenter(
            16000, 1, silence_seconds=0.8, max_seconds=2.0,
            overlap_seconds=0.3)
        speech = b"\xe8\x03" * int(16000 * 2.1)
        forced = segmenter.feed_events(speech)
        self.assertEqual(forced[0].reason, "max_duration")
        self.assertFalse(forced[0].is_final)
        trailing = b"\x00\x00" * int(16000 * 0.8)
        natural = segmenter.feed_events(trailing)
        self.assertEqual(natural[-1].reason, "silence")
        self.assertTrue(natural[-1].is_final)

    def test_interview_window_keeps_question_across_normal_two_second_pause(self):
        segmenter = MeetingUtteranceSegmenter(
            16000, 1, silence_seconds=3.5, max_seconds=15.0,
            overlap_seconds=1.0)
        speech = b"\xe8\x03" * int(16000 * 1.0)
        normal_pause = b"\x00\x00" * int(16000 * 2.0)
        self.assertEqual(segmenter.feed_events(speech + normal_pause), [])

        resumed_speech = b"\xe8\x03" * int(16000 * 1.0)
        ending_pause = b"\x00\x00" * int(16000 * 3.5)
        completed = segmenter.feed_events(resumed_speech + ending_pause)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].reason, "silence")
        self.assertTrue(completed[0].is_final)
        self.assertGreater(len(completed[0].audio), len(speech + resumed_speech))

    def test_transcript_is_normalized_to_simplified_chinese(self):
        self.assertEqual(
            to_simplified_chinese("會議聲音與數據轉寫"),
            "会议声音与数据转写")

    def test_preferred_device_uses_saved_name_despite_index_change(self):
        mapping = {
            "[9] 麦克风阵列 (Realtek(R) Audio)": {
                "index": 9, "name": "麦克风阵列 (Realtek(R) Audio)"},
            "[11] USB Mic": {"index": 11, "name": "USB Mic"},
        }
        selected = preferred_device_label(
            mapping, "麦克风阵列 (Realtek(R) Audio)", ("麦克风阵列", "realtek"))
        self.assertEqual(selected, "[9] 麦克风阵列 (Realtek(R) Audio)")

    def test_preferred_device_falls_back_to_realtek_loopback(self):
        mapping = {
            "[17] ToDesk [Loopback]": {"index": 17, "name": "ToDesk [Loopback]"},
            "[16] 扬声器 (Realtek(R) Audio) [Loopback]": {
                "index": 16, "name": "扬声器 (Realtek(R) Audio) [Loopback]"},
        }
        selected = preferred_device_label(
            mapping, "不存在的设备", ("扬声器", "realtek", "loopback"))
        self.assertEqual(selected, "[16] 扬声器 (Realtek(R) Audio) [Loopback]")

    def test_wav_validation_rejects_header_only_file(self):
        import wave

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
            self.assertFalse(_wav_has_frames(path))

    def test_wav_validation_accepts_audio_frames(self):
        import wave

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audio.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\x00\x00" * 160)
            self.assertTrue(_wav_has_frames(path))

    def test_live_meeting_snapshot_creates_readable_wav(self):
        import wave
        from voice_service import DualTrackRecorder

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "meeting.wav"
            raw = b"\x01\x00" * 1600
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(raw)
            recorder = DualTrackRecorder(Path(folder))
            recorder.system_path = source
            recorder.system_rate = 16000
            recorder.system_channels = 1
            recorder._system_bytes.value = len(raw)
            snapshot = recorder.snapshot_meeting_chunk(0, min_seconds=0.05)
            self.assertIsNotNone(snapshot)
            with wave.open(str(snapshot[0]), "rb") as audio:
                self.assertGreater(audio.getnframes(), 0)

    def test_live_meeting_chunk_is_normalized_for_asr(self):
        import wave
        from voice_service import DualTrackRecorder

        with tempfile.TemporaryDirectory() as folder:
            recorder = DualTrackRecorder(Path(folder))
            recorder.system_path = Path(folder) / "meeting.wav"
            recorder.system_rate = 48000
            recorder.system_channels = 2
            stereo = b"\xe8\x03\xe8\x03" * 4800
            chunk = recorder.write_live_meeting_chunk(stereo, 1)
            with wave.open(str(chunk), "rb") as audio:
                self.assertEqual(audio.getframerate(), 16000)
                self.assertEqual(audio.getnchannels(), 1)
                self.assertGreater(audio.getnframes(), 0)

    def test_format_transcript_with_speaker_and_timestamp(self):
        text = format_transcript([
            {"start": 65, "speaker": "我", "text": " 你好 "},
            {"start": 3661, "speaker": "会议方", "text": "请介绍项目"},
        ])
        self.assertEqual(text, "[00:01:05] 我：你好\n[01:01:01] 会议方：请介绍项目")

if __name__ == "__main__":
    unittest.main()
