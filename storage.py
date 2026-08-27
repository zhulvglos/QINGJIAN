import json
import os
import tempfile
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


STEP_PLAN_BASE_URL = "https://api.stepfun.com/step_plan/v1"
STEP_PLAN_MODEL = "step-3.5-flash"
LEGACY_MODELSCOPE_HOST = ".api-inference.modelscope.cn/"
LEGACY_MODELSCOPE_MODEL = "unsloth/DeepSeek-R1-Distill-Qwen-7B-unsloth-bnb-4bit"


DEFAULT_SETTINGS = {
    "alpha": 0.78,
    "topmost": True,
    "edge_hide": True,
    "theme": "黄色",
    "hover_readability": True,
    "geometry": "420x620+80+80",
    "window_bounds": None,
    "window_dpi": None,
    "voice_dialog_bounds": None,
    "voice_dialog_dpi": None,
    "ui_font_size": "标准",
    "background_blur": 0,
    "background_darken": 0,
    "ai_base_url": STEP_PLAN_BASE_URL,
    "ai_model": STEP_PLAN_MODEL,
    "ai_reasoning_effort": "low",
    "ai_provider_mode": "step_plan",
    "ai_step_plan_base_url": STEP_PLAN_BASE_URL,
    "ai_step_plan_model": STEP_PLAN_MODEL,
    "ai_step_plan_reasoning_effort": "low",
    "ai_llama_cpp_base_url": "http://127.0.0.1:8080/v1",
    "ai_llama_cpp_model": "qwen3-8b-local",
    "ai_llama_cpp_reasoning_effort": "low",
    "llama_cpp_executable": "",
    "llama_cpp_model_path": "",
    "llama_cpp_autostart": False,
    "ai_custom_base_url": "",
    "ai_custom_model": "",
    "ai_custom_reasoning_effort": "low",
    "ai_timeout": 180,
    "question_asr_mode": "auto",
    "interview_answer_mode": "hybrid",
    "voice_microphone_name": "麦克风阵列 (Realtek(R) Audio)",
    "voice_output_name": "扬声器 (Realtek(R) Audio) [Loopback]",
}


class NoteStore:
    def __init__(self, path: Optional[Path] = None):
        base = Path(os.getenv("APPDATA", Path.home())) / "轻笺"
        self.path = Path(path) if path else base / "data.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"notes": [], "reminders": [], "completed_tasks": [], "categories": [], "quick_slots": [],
                     "settings": dict(DEFAULT_SETTINGS)}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("notes"), list):
                self.data["notes"] = loaded["notes"]
            if isinstance(loaded.get("reminders"), list):
                self.data["reminders"] = loaded["reminders"]
            if isinstance(loaded.get("completed_tasks"), list):
                self.data["completed_tasks"] = loaded["completed_tasks"]
            if isinstance(loaded.get("categories"), list):
                self.data["categories"] = loaded["categories"]
            if isinstance(loaded.get("quick_slots"), list):
                self.data["quick_slots"] = loaded["quick_slots"]
            if isinstance(loaded.get("settings"), dict):
                self.data["settings"].update(loaded["settings"])
            changed = self._migrate()
            if self.sync_categories():
                changed = True
            if changed:
                self.save()
        except (OSError, ValueError, TypeError):
            broken = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(broken)
            except OSError:
                pass

    def save(self) -> None:
        self.sync_categories()
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(payload)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @property
    def notes(self) -> List[Dict]:
        return self.data["notes"]

    @property
    def settings(self) -> Dict:
        return self.data["settings"]

    @property
    def reminders(self) -> List[Dict]:
        return self.data["reminders"]

    @property
    def quick_slots(self) -> List[Dict]:
        return self.data["quick_slots"]

    @property
    def completed_tasks(self) -> List[Dict]:
        return self.data["completed_tasks"]

    @staticmethod
    def _id() -> str:
        return str(int(datetime.now().timestamp() * 1_000_000))

    def _migrate(self) -> bool:
        changed = False
        if LEGACY_MODELSCOPE_HOST in str(self.settings.get("ai_base_url") or ""):
            self.settings["ai_base_url"] = STEP_PLAN_BASE_URL
            changed = True
        if self.settings.get("ai_model") == LEGACY_MODELSCOPE_MODEL:
            self.settings["ai_model"] = STEP_PLAN_MODEL
            changed = True
        if "ai_reasoning_effort" not in self.settings:
            self.settings["ai_reasoning_effort"] = "low"
            changed = True
        provider_mode = self.settings.get("ai_provider_mode")
        if (self.settings.get("schema_version", 1) < 6 or
                provider_mode not in ("step_plan", "llama_cpp", "custom")):
            active_url = str(self.settings.get("ai_base_url") or "").lower()
            if active_url.startswith("https://api.stepfun.com/step_plan"):
                provider_mode = "step_plan"
            elif active_url.startswith(("http://127.0.0.1:", "http://localhost:",
                                        "http://[::1]:")):
                provider_mode = "llama_cpp"
            else:
                provider_mode = "custom"
            self.settings["ai_provider_mode"] = provider_mode
            prefix = f"ai_{provider_mode}_"
            self.settings[prefix + "base_url"] = self.settings.get("ai_base_url", "")
            self.settings[prefix + "model"] = self.settings.get("ai_model", "")
            self.settings[prefix + "reasoning_effort"] = self.settings.get(
                "ai_reasoning_effort", "low")
            changed = True
        prefix = f"ai_{provider_mode}_"
        profile_defaults = {
            prefix + "base_url": self.settings.get("ai_base_url", ""),
            prefix + "model": self.settings.get("ai_model", ""),
            prefix + "reasoning_effort": self.settings.get("ai_reasoning_effort", "low"),
        }
        for key, value in profile_defaults.items():
            if key not in self.settings:
                self.settings[key] = value
                changed = True
        if self.settings.get("question_asr_mode") not in ("auto", "stepaudio", "sensevoice"):
            self.settings["question_asr_mode"] = "auto"
            changed = True
        if self.settings.get("interview_answer_mode") not in (
                "local_fast", "hybrid", "cloud_quality"):
            self.settings["interview_answer_mode"] = "hybrid"
            changed = True
        if self.settings.get("ui_font_size") not in ("紧凑", "标准", "较大"):
            self.settings["ui_font_size"] = "标准"
            changed = True
        source_ids = {r.get("source_id") for r in self.reminders if r.get("source_id")}
        for note in self.notes:
            defaults = {"kind": "sticky", "status": "active", "formats": [],
                        "category": "", "tags": [], "learning_log": []}
            for key, value in defaults.items():
                if key not in note:
                    note[key] = value
                    changed = True
            old_time = note.get("reminder", "")
            if old_time and note.get("id") not in source_ids:
                self.reminders.append(self._reminder_record(
                    title=note.get("title", "无标题"), remind_at=old_time,
                    source_type=note["kind"], source_id=note.get("id")
                ))
                changed = True
        for reminder in self.reminders:
            defaults = {"interval": 1, "weekdays": [], "end_date": "",
                        "advance_minutes": 0, "paused": False}
            for key, value in defaults.items():
                if key not in reminder:
                    reminder[key] = value
                    changed = True
            if reminder.get("source_type") == "journal":
                reminder["source_type"] = "independent"
                reminder["source_id"] = ""
                changed = True
        if self.settings.get("schema_version", 1) < 7:
            self.settings["schema_version"] = 7
            changed = True
        return changed

    def new_note(self, title: str = "新便签", content: str = "",
                 formats: Optional[List[Dict]] = None, kind: str = "sticky",
                 category: str = "", tags: Optional[List[str]] = None) -> Dict:
        now = datetime.now().isoformat(timespec="seconds")
        note = {
            "id": self._id(),
            "title": title.strip() or "无标题",
            "content": content,
            "formats": formats or [],
            "kind": kind if kind in ("sticky", "journal") else "sticky",
            "status": "active",
            "category": category.strip(),
            "tags": tags or [],
            "learning_log": [],
            "reminder": "",
            "reminded": False,
            "created_at": now,
            "updated_at": now,
        }
        self.notes.insert(0, note)
        self.save()
        return note

    def delete(self, note_id: str) -> None:
        self.data["notes"] = [n for n in self.notes if n.get("id") != note_id]
        self.data["reminders"] = [r for r in self.reminders if r.get("source_id") != note_id]
        self.data["quick_slots"] = [q for q in self.quick_slots if q.get("source_id") != note_id]
        self.save()

    def archive_completed_task(self, kind: str, source_id: str, source_title: str,
                               content: str) -> Dict:
        """保存已完成任务快照，不依赖原便签是否继续存在。"""
        record = {
            "id": self._id(),
            "kind": kind if kind in ("sticky", "journal") else "sticky",
            "source_id": source_id,
            "source_title": source_title.strip() or "无标题",
            "content": content.strip(),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.completed_tasks.insert(0, record)
        self.save()
        return record

    def recover_legacy_completed_tasks(self) -> Dict[str, int]:
        """将旧版误移出的任务安全回填到原便签，来源冲突记录留待人工确认。"""
        if self.settings.get("completed_task_recovery_v2"):
            return {"restored": 0, "pending_review": 0}
        grouped = {}
        for record in self.completed_tasks:
            key = (record.get("source_id", ""), record.get("content", "").strip())
            grouped.setdefault(key, record)
        content_sources = {}
        for (source_id, content), record in grouped.items():
            normalized = content[2:] if content.startswith(("☐ ", "☑ ")) else content
            content_sources.setdefault(normalized, set()).add(source_id)
        pending, restored = [], 0
        for (source_id, content), record in grouped.items():
            normalized = content[2:] if content.startswith(("☐ ", "☑ ")) else content
            if len(content_sources.get(normalized, set())) > 1:
                record["recovery_status"] = "pending_review"
                pending.append(record)
                continue
            note = next((item for item in self.notes if item.get("id") == source_id), None)
            if not note:
                record["recovery_status"] = "pending_review"
                pending.append(record)
                continue
            pending_variant = "☐ " + normalized
            completed_variant = "☑ " + normalized
            if completed_variant in note.get("content", ""):
                restored += 1
                continue
            if pending_variant in note.get("content", ""):
                note["content"] = note["content"].replace(pending_variant, completed_variant, 1)
            else:
                separator = "\n\n" if note.get("content", "").strip() else ""
                note["content"] = note.get("content", "").rstrip() + separator + completed_variant
            note["updated_at"] = datetime.now().isoformat(timespec="seconds")
            restored += 1
        self.data["completed_tasks"] = pending
        self.settings["completed_task_recovery_v2"] = True
        self.save()
        return {"restored": restored, "pending_review": len(pending)}

    def recover_mini_hermes_content(self) -> Dict[str, int]:
        """根据用户确认的截图内容，定向恢复被旧任务归档逻辑移走的 mini hermes 条目。"""
        if self.settings.get("mini_hermes_recovery_v3"):
            return {"restored": 0}
        note = next((item for item in self.notes if item.get("title") == "mini hermes"), None)
        if not note:
            return {"restored": 0}
        blocks = [
            "☐ min问答：\ncd D:/pythonProject1/mini-hermes\npython hermes_cli/main.py",
            "☐ 正则清洗（快）：\ncd D:/pythonProject1/mini-hermes\npython scripts/rag_ocr_demo.py\n\"D:\\QingjianData\\health\\testOCR\\20250806游离甲功组合.png\"",
            "☐ LLM 清洗（精准，需要网络）：\ncd D:/pythonProject1/mini-hermes\npython scripts/rag_ocr_demo.py\n\"D:\\QingjianData\\health\\testOCR\\20250813游离甲功组合.png\" --llm",
        ]
        existing = note.get("content", "")
        restored = 0
        for block in blocks:
            marker = block.split("\n", 1)[0][2:]
            if marker not in existing:
                existing = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
                restored += 1
        note["content"] = existing
        if restored:
            note["updated_at"] = datetime.now().isoformat(timespec="seconds")
        # “min问答”被错误同时标到两个标题；已按用户确认放回 mini hermes，移除旧冲突记录。
        self.data["completed_tasks"] = [
            record for record in self.completed_tasks
            if not (record.get("content", "").lstrip().startswith("☑ min问答："))
        ]
        self.settings["mini_hermes_recovery_v3"] = True
        self.save()
        return {"restored": restored}

    def add_quick_slot(self, source_type: str, source_id: str, label: str) -> None:
        if not any(q.get("source_type") == source_type and q.get("source_id") == source_id
                   for q in self.quick_slots):
            self.quick_slots.append({"source_type": source_type, "source_id": source_id,
                                     "label": label[:10], "order": len(self.quick_slots)})
            self.save()

    def remove_quick_slot(self, source_type: str, source_id: str) -> None:
        self.data["quick_slots"] = [q for q in self.quick_slots if not (
            q.get("source_type") == source_type and q.get("source_id") == source_id)]
        self.save()

    def notes_by_kind(self, kind: str) -> List[Dict]:
        return [n for n in self.notes if n.get("kind", "sticky") == kind]

    @property
    def categories(self) -> List[str]:
        return self.data["categories"]

    def remember_category(self, category: str) -> None:
        # 分类以现有笔记为唯一数据源；保留该方法兼容已有调用。
        self.sync_categories()

    def sync_categories(self) -> bool:
        """让分类索引与当前笔记实际使用的分类完全一致。"""
        actual = sorted({
            note.get("category", "").strip()
            for note in self.notes
            if note.get("kind") == "journal" and note.get("category", "").strip()
        }, key=str.casefold)
        if self.data.get("categories") == actual:
            return False
        self.data["categories"] = actual
        return True

    def tags_for_category(self, category: str) -> List[str]:
        """汇总同一笔记分类中使用过的标签。"""
        wanted = category.strip()
        tags = set()
        for note in self.notes:
            if note.get("kind") != "journal" or note.get("category", "").strip() != wanted:
                continue
            tags.update(tag.strip() for tag in note.get("tags", []) if tag.strip())
        return sorted(tags, key=str.casefold)

    def rename_tag(self, category: str, old_name: str, new_name: str) -> int:
        """仅在指定笔记分类内重命名标签，并合并可能产生的重复项。"""
        wanted = category.strip()
        old_name, new_name = old_name.strip(), new_name.strip()
        if not old_name or not new_name or old_name == new_name:
            return 0
        changed = 0
        for note in self.notes:
            if note.get("kind") != "journal" or note.get("category", "").strip() != wanted:
                continue
            if old_name not in note.get("tags", []):
                continue
            renamed = [new_name if tag == old_name else tag for tag in note.get("tags", [])]
            note["tags"] = list(dict.fromkeys(tag for tag in renamed if tag))
            note["updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed += 1
        if changed:
            self.save()
        return changed

    def _reminder_record(self, title: str, remind_at: str, source_type: str,
                         source_id: str = "", content: str = "",
                         repeat: str = "none", rule: Optional[Dict] = None) -> Dict:
        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "id": self._id(), "title": title.strip() or "未命名提醒",
            "content": content, "remind_at": remind_at, "repeat": repeat,
            "source_type": source_type, "source_id": source_id,
            "status": "pending", "created_at": now, "updated_at": now,
            "interval": 1, "weekdays": [], "end_date": "",
            "advance_minutes": 0, "paused": False,
        }
        if rule:
            record.update({key: rule[key] for key in (
                "interval", "weekdays", "end_date", "advance_minutes", "paused"
            ) if key in rule})
        return record

    def set_source_reminder(self, source: Dict, remind_at: str = "",
                            repeat: str = "none", rule: Optional[Dict] = None) -> Optional[Dict]:
        existing = next((r for r in self.reminders
                         if r.get("source_id") == source.get("id")), None)
        if not remind_at:
            if existing:
                self.reminders.remove(existing)
            self.save()
            return None
        if existing:
            schedule_changed = (existing.get("remind_at") != remind_at or
                                existing.get("repeat", "none") != repeat)
            existing.update({"title": source.get("title", "无标题"),
                             "content": source.get("content", ""),
                             "remind_at": remind_at, "repeat": repeat,
                             "source_type": source.get("kind", "sticky"),
                             "updated_at": datetime.now().isoformat(timespec="seconds")})
            if rule:
                existing.update(rule)
            if schedule_changed:
                existing["status"] = "pending"
            reminder = existing
        else:
            reminder = self._reminder_record(
                source.get("title", "无标题"), remind_at,
                source.get("kind", "sticky"), source.get("id", ""),
                source.get("content", ""), repeat, rule)
            self.reminders.insert(0, reminder)
        self.save()
        return reminder

    def new_independent_reminder(self, title: str, content: str,
                                 remind_at: str, repeat: str = "none",
                                 rule: Optional[Dict] = None) -> Dict:
        reminder = self._reminder_record(title, remind_at, "independent",
                                         content=content, repeat=repeat, rule=rule)
        self.reminders.insert(0, reminder)
        self.save()
        return reminder

    def due_reminders(self, now: Optional[datetime] = None) -> List[Dict]:
        now = now or datetime.now()
        due = []
        for reminder in self.reminders:
            if reminder.get("status") != "pending" or reminder.get("paused"):
                continue
            try:
                when = datetime.strptime(reminder.get("remind_at", ""), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            notify_at = when - timedelta(minutes=int(reminder.get("advance_minutes", 0)))
            if notify_at <= now:
                reminder["status"] = "notified"
                due.append(reminder)
        if due:
            self.save()
        return due

    def complete_reminder(self, reminder_id: str) -> None:
        reminder = next((r for r in self.reminders if r.get("id") == reminder_id), None)
        if not reminder:
            return
        repeat = reminder.get("repeat", "none")
        if repeat != "none":
            try:
                when = datetime.strptime(reminder["remind_at"], "%Y-%m-%d %H:%M")
            except ValueError:
                when = datetime.now()
            while when <= datetime.now():
                when = self._next_occurrence(when, reminder)
            end_date = reminder.get("end_date", "")
            if end_date and when.date() > date.fromisoformat(end_date):
                reminder["status"] = "completed"
                self.save()
                return
            reminder["remind_at"] = when.strftime("%Y-%m-%d %H:%M")
            reminder["status"] = "pending"
            reminder["last_completed_at"] = datetime.now().isoformat(timespec="seconds")
        else:
            reminder["status"] = "completed"
        self.save()

    @staticmethod
    def _next_occurrence(when: datetime, reminder: Dict) -> datetime:
        repeat = reminder.get("repeat", "none")
        interval = max(1, int(reminder.get("interval", 1)))
        if repeat == "daily":
            return when + timedelta(days=interval)
        if repeat == "workday":
            candidate = when + timedelta(days=1)
            while candidate.weekday() >= 5:
                candidate += timedelta(days=1)
            return candidate
        if repeat == "weekly":
            weekdays = sorted({int(x) for x in reminder.get("weekdays", []) if 0 <= int(x) <= 6})
            if weekdays:
                candidate = when + timedelta(days=1)
                for _ in range(14 * interval):
                    if candidate.weekday() in weekdays:
                        return candidate
                    candidate += timedelta(days=1)
            return when + timedelta(weeks=interval)
        if repeat == "monthly":
            total = when.year * 12 + when.month - 1 + interval
            year, month_index = divmod(total, 12)
            month = month_index + 1
            day = min(when.day, calendar.monthrange(year, month)[1])
            return when.replace(year=year, month=month, day=day)
        if repeat == "yearly":
            year = when.year + interval
            day = min(when.day, calendar.monthrange(year, when.month)[1])
            return when.replace(year=year, day=day)
        return when + timedelta(days=1)

    def toggle_reminder_paused(self, reminder_id: str) -> None:
        reminder = next((r for r in self.reminders if r.get("id") == reminder_id), None)
        if reminder:
            reminder["paused"] = not reminder.get("paused", False)
            reminder["status"] = "pending" if not reminder["paused"] else reminder.get("status", "pending")
            self.save()

    def log_learning(self, note_id: str, day: Optional[str] = None) -> None:
        note = next((n for n in self.notes if n.get("id") == note_id), None)
        if not note or note.get("kind") != "journal":
            return
        day = day or date.today().isoformat()
        log = note.setdefault("learning_log", [])
        if day not in log:
            log.append(day)
            log.sort()
            self.save()

    def unlog_learning(self, note_id: str, day: Optional[str] = None) -> None:
        note = next((n for n in self.notes if n.get("id") == note_id), None)
        day = day or date.today().isoformat()
        if note and day in note.get("learning_log", []):
            note["learning_log"].remove(day)
            self.save()

    @staticmethod
    def learning_stats(note: Dict) -> Dict[str, int]:
        days = sorted({date.fromisoformat(x) for x in note.get("learning_log", [])}, reverse=True)
        today = date.today()
        streak = 0
        cursor = today if today in days else today - timedelta(days=1)
        day_set = set(days)
        while cursor in day_set:
            streak += 1
            cursor -= timedelta(days=1)
        week_start = today - timedelta(days=today.weekday())
        return {"total": len(days), "streak": streak,
                "week": sum(d >= week_start for d in days),
                "month": sum(d.year == today.year and d.month == today.month for d in days)}

    def snooze_reminder(self, reminder_id: str, minutes: int = 30) -> None:
        reminder = next((r for r in self.reminders if r.get("id") == reminder_id), None)
        if reminder:
            reminder["remind_at"] = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
            reminder["status"] = "pending"
            self.save()

    def delete_reminder(self, reminder_id: str) -> None:
        self.data["reminders"] = [r for r in self.reminders if r.get("id") != reminder_id]
        self.save()
