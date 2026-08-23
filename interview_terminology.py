"""面试语音专业术语纠错与风险分析。词条来自可编辑 Markdown 文件。"""

import re
from pathlib import Path
from typing import Dict, List


TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+")
ALIAS_SPLIT_RE = re.compile(r"\s*[;；、，]\s*")


def load_terminology(path: Path) -> List[Dict]:
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    terms = []
    for line in lines:
        if "|" not in line or TABLE_SEPARATOR_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("标准术语", "---"):
            continue
        canonical, full_name, aliases, definition, spoken = cells[:5]
        if not canonical or not definition:
            continue
        alias_values = [canonical]
        alias_values.extend(item for item in ALIAS_SPLIT_RE.split(aliases) if item)
        terms.append({
            "canonical": canonical,
            "full_name": full_name,
            "aliases": list(dict.fromkeys(alias_values)),
            "definition": definition,
            "spoken": spoken,
        })
    return terms


def _alias_pattern(alias: str):
    escaped = re.escape(alias)
    if re.fullmatch(r"[A-Za-z0-9 .+#_-]+", alias):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)
    return re.compile(escaped)


class InterviewTerminology:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.terms = load_terminology(self.path)

    def refresh(self):
        self.terms = load_terminology(self.path)

    def correct(self, text: str) -> Dict:
        raw = str(text or "")
        # 长别名优先，避免短别名抢先替换。
        entries = []
        for term in self.terms:
            for alias in term["aliases"]:
                if alias and alias.casefold() != term["canonical"].casefold():
                    entries.append((alias, term["canonical"]))
        matches = []
        for alias, canonical in entries:
            for match in _alias_pattern(alias).finditer(raw):
                matches.append((match.start(), match.end(), canonical, match.group(0)))
        selected = []
        for item in sorted(matches, key=lambda value: (value[0], -(value[1] - value[0]))):
            if selected and item[0] < selected[-1][1]:
                continue
            selected.append(item)
        pieces = []
        changes = []
        offset = 0
        for start, end, canonical, original in selected:
            pieces.extend((raw[offset:start], canonical))
            changes.append({"original": original, "replacement": canonical})
            offset = end
        pieces.append(raw[offset:])
        corrected = "".join(pieces)
        risk = self.analyze(corrected)
        risk["correction_applied"] = bool(changes)
        return {"raw": raw, "corrected": corrected, "changes": changes, "risk": risk}

    def analyze(self, text: str) -> Dict:
        value = str(text or "")
        matched = []
        known_acronyms = set()
        for term in self.terms:
            names = [term["canonical"], term["full_name"], *term["aliases"]]
            if any(name and _alias_pattern(name).search(value) for name in names):
                matched.append(term["canonical"])
            for name in names:
                known_acronyms.update(item.upper() for item in re.findall(
                    r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.+#-]{1,}(?![A-Za-z0-9])",
                    name or ""))
        acronyms = list(dict.fromkeys(re.findall(
            r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.+#-]{1,}(?![A-Za-z0-9])", value)))
        unknown = [item for item in acronyms if item.upper() not in known_acronyms]
        return {
            "matched_terms": list(dict.fromkeys(matched)),
            "acronyms": acronyms,
            "unknown_acronyms": unknown,
            "correction_applied": False,
        }
