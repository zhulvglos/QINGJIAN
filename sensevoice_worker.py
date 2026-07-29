"""SenseVoice 离线转写子进程。

该文件必须通过 D:\LightNoteSenseVoice 英文目录映射启动，避免 Windows
原生 SentencePiece 组件无法读取中文路径。
"""

import argparse
import json
import os
from pathlib import Path


RUNTIME_ROOT = Path(r"D:\LightNoteSenseVoice")


def _clean_text(text):
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    from opencc import OpenCC

    cleaned = rich_transcription_postprocess(text or "")
    return OpenCC("t2s").convert(cleaned).strip()


def _build_model():
    from funasr import AutoModel

    return AutoModel(
        model=str(RUNTIME_ROOT / "models" / "SenseVoiceSmall"),
        vad_model=str(RUNTIME_ROOT / "models" / "fsmn-vad"),
        spk_model=str(RUNTIME_ROOT / "models" / "campplus-speaker"),
        vad_kwargs={"max_single_segment_time": 15000},
        device="cpu",
        disable_update=True,
    )


def _segments_from_result(result, default_speaker, diarize):
    segments = []
    speaker_ids = {}
    next_speaker = 1
    for item in result:
        sentence_info = item.get("sentence_info") or []
        if sentence_info:
            for sentence in sentence_info:
                speaker = default_speaker
                if diarize:
                    raw_id = int(sentence.get("spk", 0))
                    if raw_id not in speaker_ids:
                        speaker_ids[raw_id] = next_speaker
                        next_speaker += 1
                    speaker = f"会议方{speaker_ids[raw_id]}"
                text = _clean_text(sentence.get("sentence", ""))
                if text:
                    segments.append({
                        "start": float(sentence.get("start", 0)) / 1000.0,
                        "end": float(sentence.get("end", 0)) / 1000.0,
                        "speaker": speaker,
                        "text": text,
                    })
            continue
        text = _clean_text(item.get("text", ""))
        if text:
            segments.append({"start": 0.0, "end": 0.0,
                             "speaker": default_speaker, "text": text})
    return segments


def transcribe(request, model=None):
    model = model or _build_model()
    all_segments = []
    for track in request.get("tracks", []):
        result = model.generate(
            input=str(track["path"]), cache={}, language="zh", use_itn=True,
            batch_size_s=60, merge_vad=False, return_spk_res=True,
        )
        all_segments.extend(_segments_from_result(
            result, track.get("label", "说话人"), bool(track.get("diarize"))))
    return sorted(all_segments, key=lambda item: (item["start"], item["speaker"]))


def serve():
    """JSON Lines 常驻模式，供准实时提问检测复用同一个模型实例。"""
    model = _build_model()
    print(json.dumps({"event": "ready"}, ensure_ascii=False), flush=True)
    for line in iter(input, ""):
        try:
            request = json.loads(line)
            if request.get("command") == "close":
                break
            response = {"ok": True, "segments": transcribe(request, model)}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request")
    parser.add_argument("--response")
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()
    if args.server:
        serve()
        return
    if not args.request or not args.response:
        parser.error("--request 和 --response 为必填参数")
    request_path = Path(args.request)
    response_path = Path(args.response)
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        response = {"ok": True, "segments": transcribe(request)}
    except Exception as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    response_path.write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    main()
