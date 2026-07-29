import json
import math
import re
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
from xml.etree import ElementTree as ET


SUPPORTED_SUFFIXES = {".md", ".txt", ".docx", ".xlsx"}
CACHE_VERSION = 1


@dataclass
class KnowledgeResult:
    context: str
    sources: List[str]
    passages: List[Dict]


def tokenize(text: str) -> List[str]:
    text = str(text or "").lower()
    words = re.findall(r"[a-z0-9][a-z0-9_+.#/-]*", text)
    chinese_runs = re.findall(r"[\u3400-\u9fff]+", text)
    tokens = list(words)
    for run in chinese_runs:
        tokens.extend(run)
        tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(node.text or "" for node in paragraph.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def _read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append("".join(node.text or "" for node in item.iter()
                                      if node.tag.endswith("}t")))
        rows = []
        sheets = sorted(name for name in archive.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        for sheet in sheets:
            root = ET.fromstring(archive.read(sheet))
            for row in (node for node in root.iter() if node.tag.endswith("}row")):
                values = []
                for cell in (node for node in row if node.tag.endswith("}c")):
                    value_node = next((node for node in cell.iter()
                                       if node.tag.endswith("}v")), None)
                    inline = "".join(node.text or "" for node in cell.iter()
                                     if node.tag.endswith("}t"))
                    value = inline
                    if value_node is not None and value_node.text is not None:
                        value = value_node.text
                        if cell.attrib.get("t") == "s":
                            try:
                                value = shared[int(value)]
                            except (ValueError, IndexError):
                                pass
                    if str(value).strip():
                        values.append(str(value).strip())
                if values:
                    rows.append(" | ".join(values))
    return "\n".join(rows)


def read_document(path: Path) -> str:
    if path.suffix.lower() in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".docx":
        return _read_docx(path)
    if path.suffix.lower() == ".xlsx":
        return _read_xlsx(path)
    return ""


def chunk_document(text: str, max_chars: int = 1000) -> Iterable[Dict]:
    heading = ""
    current = ""
    for block in re.split(r"\n\s*\n|(?=^#{1,6}\s+)", text, flags=re.M):
        block = block.strip()
        if not block:
            continue
        match = re.match(r"^#{1,6}\s+(.+)", block)
        if match:
            if current:
                yield {"heading": heading, "text": current.strip()}
                current = ""
            heading = match.group(1).strip()
        decorated = f"{heading}\n{block}" if heading and not block.startswith("#") else block
        if current and len(current) + len(decorated) + 2 > max_chars:
            yield {"heading": heading, "text": current.strip()}
            current = ""
        if len(decorated) > max_chars:
            if current:
                yield {"heading": heading, "text": current.strip()}
                current = ""
            for index in range(0, len(decorated), max_chars):
                yield {"heading": heading, "text": decorated[index:index + max_chars]}
        else:
            current = f"{current}\n\n{decorated}".strip()
    if current:
        yield {"heading": heading, "text": current.strip()}


class InterviewKnowledgeBase:
    def __init__(self, root: Path, cache_path: Path):
        self.root = Path(root)
        self.cache_path = Path(cache_path)
        self.passages: List[Dict] = []
        self.signature = []
        self._lock = threading.RLock()

    def _files(self) -> List[Path]:
        if not self.root.exists():
            return []
        return sorted(path for path in self.root.rglob("*")
                      if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)

    def _signature(self, files: List[Path]) -> List[Dict]:
        return [{"path": str(path.relative_to(self.root)).replace("\\", "/"),
                 "size": path.stat().st_size,
                 "mtime_ns": path.stat().st_mtime_ns} for path in files]

    def ensure_index(self) -> None:
        files = self._files()
        signature = self._signature(files)
        if self.passages and signature == self.signature:
            return
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if (cached.get("version") == CACHE_VERSION and
                    cached.get("signature") == signature and
                    isinstance(cached.get("passages"), list)):
                self.signature = signature
                self.passages = cached["passages"]
                return
        except (OSError, ValueError, TypeError):
            pass
        passages = []
        for path in files:
            try:
                content = read_document(path)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
                continue
            relative = str(path.relative_to(self.root)).replace("\\", "/")
            for chunk in chunk_document(content):
                text = chunk["text"]
                tokens = tokenize(f"{path.stem} {chunk['heading']} {text}")
                if tokens:
                    passages.append({"source": relative, "heading": chunk["heading"],
                                     "text": text, "tokens": tokens})
        self.signature = signature
        self.passages = passages
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CACHE_VERSION, "signature": signature,
                   "passages": passages}
        try:
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def search(self, query: str, limit: int = 4) -> KnowledgeResult:
        with self._lock:
            self.ensure_index()
            query_tokens = tokenize(query)
            if not query_tokens or not self.passages:
                return KnowledgeResult("", [], [])
            documents = [Counter(item["tokens"]) for item in self.passages]
            lengths = [sum(document.values()) for document in documents]
            average = sum(lengths) / max(1, len(lengths))
            frequencies = Counter()
            for document in documents:
                frequencies.update(document.keys())
            # 单个汉字在长文档中极易偶然重合；检索准入至少需要中文二元词或英文关键词。
            significant_tokens = {token for token in query_tokens if len(token) >= 2}
            scored = []
            for index, document in enumerate(documents):
                if not any(document.get(token, 0) for token in significant_tokens):
                    continue
                score = 0.0
                for token in set(query_tokens):
                    count = document.get(token, 0)
                    if not count:
                        continue
                    inverse = math.log(1 + (len(documents) - frequencies[token] + 0.5) /
                                       (frequencies[token] + 0.5))
                    score += inverse * count * 2.2 / (count + 1.2 *
                        (0.25 + 0.75 * lengths[index] / max(1, average)))
                if score > 0:
                    scored.append((score, index))
            selected = [self.passages[index] for _, index in sorted(scored, reverse=True)[:limit]]
            sources = list(dict.fromkeys(item["source"] for item in selected))
            context = "\n\n".join(
                f"【资料：{item['source']}｜{item['heading'] or '正文'}】\n{item['text']}"
                for item in selected)
            return KnowledgeResult(context, sources, selected)
