import ctypes
import json
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import date, datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, Optional
from calendar_picker import CalendarPicker
from dpi_scaler import WindowDpiScaler
from display_manager import (DisplayArea, EdgeHideController, detect_docked_edge,
                             display_for_bounds, enable_per_monitor_dpi_awareness,
                             ensure_visible_position, enumerate_displays,
                             set_window_position, window_bounds)
from ai_service import (AIServiceError, INTERVIEW_TASKS, MEETING_TASKS, TRANSCRIPT_TASKS,
                        REASONING_EFFORTS, STEP_PLAN_MODELS,
                        analyze_interview, analyze_meeting, analyze_transcript,
                        answer_interview_question,
                        choose_interview_answer_provider, stream_chat_completion)
from palette import ModernButton, ModernEntry, ModernToggle, apply_palette_to_all
from storage import NoteStore
from sensevoice_service import SenseVoiceLiveSession, SenseVoiceTranscriber
from stepaudio_service import StepAudioASR
from question_service import InterviewQuestionDetector
from voice_service import (DualTrackRecorder, MeetingUtteranceSegmenter, VoiceServiceError,
                           format_transcript, list_audio_devices,
                           preferred_device_label)
from tray import TrayManager
from single_instance import SingleInstance
from windows_integration import (autostart_enabled, load_ai_token, save_ai_token,
                                 send_windows_notification, set_autostart)
from news_service import (NewsServiceError, effective_daily_date, fetch_daily,
                          load_daily_cache, save_daily_cache)
from free_model_service import (effective_flash_date, fetch_free_model_digest)
from interview_knowledge_base import InterviewKnowledgeBase
from interview_terminology import InterviewTerminology
from llama_runtime import (LlamaRuntimeError, LlamaRuntimeManager,
                           discover_managed_runtime)


QUESTION_ASR_OPTIONS = {
    "自动（SenseVoice优先）": "auto",
    "仅SenseVoice本地": "sensevoice",
    "仅StepAudio在线": "stepaudio",
}

AI_PROVIDER_OPTIONS = {
    "Step Plan云端": "step_plan",
    "本地 llama.cpp": "llama_cpp",
    "其他OpenAI兼容接口": "custom",
}
AI_PROVIDER_LABELS = {value: label for label, value in AI_PROVIDER_OPTIONS.items()}
QUESTION_ASR_LABELS = {value: label for label, value in QUESTION_ASR_OPTIONS.items()}
INTERVIEW_ANSWER_OPTIONS = {
    "智能混合": "hybrid",
    "极速本地": "local_fast",
    "高质量云端": "cloud_quality",
}
INTERVIEW_ANSWER_LABELS = {
    value: label for label, value in INTERVIEW_ANSWER_OPTIONS.items()}
UI_FONT_SCALINGS = {"紧凑": 0.88, "标准": 1.0, "较大": 1.14}


THEMES = {
    "黄色": {"bg": "#f3e7a5", "panel": "#d9c978", "accent": "#c88b22",
             "text": "#2f2a20", "muted": "#665e4d", "input": "#fff8d5"},
    "蓝色": {"bg": "#2f5069", "panel": "#233f55", "accent": "#58a9dc",
             "text": "#f4f8fb", "muted": "#c1d4e1", "input": "#3b627d"},
    "无色": {"bg": "#dededb", "panel": "#c1c2c0", "accent": "#73777a",
             "text": "#242526", "muted": "#5f6263", "input": "#eeeeec"},
    "深色": {"bg": "#25272a", "panel": "#17191c", "accent": "#8b929a",
             "text": "#f1f2f3", "muted": "#aeb2b7", "input": "#32353a"},
    "莫兰迪": {"bg": "#e8e1d3", "panel": "#d4c8b0", "accent": "#a78b6a",
               "text": "#3a342b", "muted": "#8a7d6a", "input": "#f0ead9"},
    "赛博": {"bg": "#0d1117", "panel": "#161b22", "accent": "#58a6ff",
             "text": "#e6edf3", "muted": "#7d8590", "input": "#1c2128"},
    "水墨": {"bg": "#f5f3ee", "panel": "#e8e5dc", "accent": "#2c2c2c",
             "text": "#1a1a1a", "muted": "#888888", "input": "#faf8f2"},
    "糖果": {"bg": "#fff0f5", "panel": "#ffe4ec", "accent": "#ff6b9d",
             "text": "#5a2a3a", "muted": "#a07588", "input": "#fff5f9"},
    "薄荷": {"bg": "#e8f5f0", "panel": "#d0ebe0", "accent": "#3cb489",
             "text": "#1f3a32", "muted": "#6a8a7a", "input": "#f0faf4"},
}


def cyclic_index(length, current_index, step):
    """返回列表中的循环相邻索引。"""
    if length <= 0:
        return None
    if current_index is None or not 0 <= current_index < length:
        return 0 if step > 0 else length - 1
    return (current_index + step) % length


class SegmentedNav(tk.Canvas):
    """适合窄窗口的分段导航，使用轻量滑动高亮。"""
    SECTIONS = (("reminder", "提醒"), ("sticky", "便签"),
                ("journal", "笔记"), ("news", "新闻"), ("settings", "设置"))

    def __init__(self, parent, command):
        super().__init__(parent, height=42, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.command = command
        self.active_index = 1
        self.display_index = 1.0
        self.focus_index = 1
        self.counts = {}
        self.palette = THEMES["黄色"]
        self.visual_scale = 1.0
        self.animation_job = None
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Button-1>", self.on_click)
        self.bind("<MouseWheel>", self.on_wheel)
        self.bind("<FocusIn>", self.on_focus)
        self.bind("<FocusOut>", lambda _e: self.draw())
        self.bind("<Left>", lambda _e: self.move_focus(-1))
        self.bind("<Right>", lambda _e: self.move_focus(1))
        self.bind("<Return>", self.activate_focus)
        self.bind("<space>", self.activate_focus)

    def set_theme(self, palette):
        self.palette = palette
        self.configure(bg=palette["bg"])
        self.draw()

    def set_visual_scale(self, scale):
        self.visual_scale = max(0.75, float(scale))
        self.configure(height=round(42 * self.visual_scale))
        self.draw()

    def set_active(self, section, animate=True):
        index = next((i for i, item in enumerate(self.SECTIONS) if item[0] == section), 1)
        self.active_index = index
        self.focus_index = index
        if not animate or self.winfo_width() <= 1:
            self.display_index = float(index)
            self.draw()
            return
        if self.animation_job:
            self.after_cancel(self.animation_job)
        self._animate_step()

    def set_counts(self, counts):
        self.counts = counts
        self.draw()

    def _animate_step(self):
        distance = self.active_index - self.display_index
        if abs(distance) < 0.025:
            self.display_index = float(self.active_index)
            self.animation_job = None
            self.draw()
            return
        self.display_index += distance * 0.34
        self.draw()
        self.animation_job = self.after(16, self._animate_step)

    def draw(self):
        self.delete("all")
        width = max(self.winfo_width(), 3)
        scale = self.visual_scale
        segment = width / len(self.SECTIONS)
        center = segment * (self.display_index + 0.5)
        half = max(30 * scale, segment / 2 - 7 * scale)
        x1, x2, y1, y2 = center - half, center + half, 5 * scale, 35 * scale
        radius = 15 * scale
        c = self.palette
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=c["accent"], outline="")
        self.create_oval(x1, y1, x1 + radius * 2, y2, fill=c["accent"], outline="")
        self.create_oval(x2 - radius * 2, y1, x2, y2, fill=c["accent"], outline="")
        for index, (section, label) in enumerate(self.SECTIONS):
            count = self.counts.get(section, 0)
            text = f"{label} {count}" if section == "reminder" and count else label
            active = index == self.active_index
            self.create_text(segment * (index + 0.5), 20 * scale, text=text,
                             fill="white" if active else c["muted"],
                             font=("Microsoft YaHei UI", max(7, round(11 * scale)),
                                   "bold" if active else "normal"))
        if self.focus_get() is self:
            x1 = segment * self.focus_index + 4 * scale
            x2 = segment * (self.focus_index + 1) - 4 * scale
            self.create_rectangle(x1, 3 * scale, x2, 37 * scale,
                                  outline=c["text"], width=1, dash=(2, 2))

    def on_click(self, event):
        count = len(self.SECTIONS)
        index = min(count - 1, max(0, int(event.x / max(1, self.winfo_width() / count))))
        self.command(self.SECTIONS[index][0])

    def on_focus(self, _event=None):
        self.focus_index = self.active_index
        self.draw()

    def move_focus(self, step):
        self.focus_index = (self.focus_index + step) % len(self.SECTIONS)
        self.draw()
        self.command(self.SECTIONS[self.focus_index][0])
        return "break"

    def activate_focus(self, _event=None):
        self.command(self.SECTIONS[self.focus_index][0])
        return "break"

    def on_wheel(self, event):
        step = -1 if event.delta > 0 else 1
        index = (self.active_index + step) % len(self.SECTIONS)
        self.command(self.SECTIONS[index][0])
        return "break"


class StickyNotesApp:
    EDGE_GAP = 12
    HIDDEN_SIZE = 7
    TOKEN_MASK = "............."

    def __init__(self, root: tk.Tk, instance_guard=None):
        self.root = root
        self.instance_guard = instance_guard
        self.store = NoteStore()
        self.completed_task_recovery = self.store.recover_legacy_completed_tasks()
        self.mini_hermes_recovery = self.store.recover_mini_hermes_content()
        if (not self.store.settings.get("llama_cpp_executable") or
                not self.store.settings.get("llama_cpp_model_path")):
            discovered_runtime = discover_managed_runtime(Path(__file__).resolve().parent)
            if discovered_runtime:
                self.store.settings["llama_cpp_executable"] = discovered_runtime["executable"]
                self.store.settings["llama_cpp_model_path"] = discovered_runtime["model_path"]
                self.store.settings["llama_cpp_autostart"] = True
                self.store.save()
        self.current: Optional[Dict] = None
        self.current_reminder: Optional[Dict] = None
        self.current_news: Optional[Dict] = None
        self.news_cache: Optional[Dict] = None
        self.news_cache_path = self.store.path.parent / "news_cache.json"
        self.flash_cache: Optional[Dict] = None
        self.flash_cache_path = self.store.path.parent / "free_models_cache.json"
        self.news_mode = "daily"
        self.interview_knowledge_base = InterviewKnowledgeBase(
            Path(__file__).resolve().parent / "录音回答知识库",
            self.store.path.parent / "interview_kb_index.json")
        self.interview_terminology = InterviewTerminology(
            Path(__file__).resolve().parent / "录音回答知识库" / "AI技术术语词典.md")
        self.llama_runtime = LlamaRuntimeManager(
            Path(__file__).resolve().parent / "logs")
        self.news_items = []
        self.news_loading = False
        self.news_loading_modes = set()
        self.news_results = queue.Queue()
        self.news_poll_job = None
        self.ai_dialog = None
        self.ai_cancel_event = None
        self.voice_recorder = None
        self.voice_edge_controller = None
        self.main_dpi_scaler = None
        self.voice_dpi_scaler = None
        self.current_section = "sticky"
        self.task_view = "pending"
        self.section_selection_ids = {}
        self.save_job = None
        self.layout_job = None
        self.hidden_edge: Optional[str] = None
        self.dragging = False
        self.resizing = False
        self.compact_mode = False
        self.compact_sash_user_resized = False
        self.wide_sash_user_resized = False
        self.rounded_region_job = None
        self.rounded_region_applying = False
        self.drag_candidate = None
        self.drag_source = None
        self.resize_origin = None
        self.closing = False
        self.exiting = False
        self.minimized = False
        self.drag_offset = (0, 0)
        self.hovered = False
        self.theme_name = self.store.settings.get("theme", "黄色")
        if self.theme_name not in THEMES:
            self.theme_name = "黄色"
        self.colors = THEMES[self.theme_name]
        self.bg_widgets = []
        self.panel_widgets = []
        self.nav_widgets = []
        self.muted_labels = []

        self.root.title("轻笺")
        self.ui_font_size = self.store.settings.get("ui_font_size", "标准")
        self._enforce_ui_scaling()
        self.root.minsize(320, 420)
        saved_bounds = self.store.settings.get("window_bounds")
        if (isinstance(saved_bounds, list) and len(saved_bounds) == 4 and
                all(isinstance(value, int) for value in saved_bounds)):
            self.root.geometry(f"{max(320, saved_bounds[2])}x{max(420, saved_bounds[3])}")
        else:
            self.root.geometry(self.store.settings["geometry"])
        self.root.configure(bg=self.colors["bg"])
        self.root.attributes("-alpha", float(self.store.settings["alpha"]))
        self.root.attributes("-topmost", bool(self.store.settings["topmost"]))
        self.root.overrideredirect(True)
        self._set_app_id()
        self._build_ui()
        self._bind_events()
        self.apply_theme(save=False)
        self.root.after(50, self._show_in_taskbar)
        self.edge_controller = EdgeHideController(
            self.root, enabled=lambda: self.edge_var.get(),
            gap=self.EDGE_GAP, visible_size=self.HIDDEN_SIZE,
            blocked=lambda: self.resizing,
            on_hide=self._on_main_edge_hidden,
            on_reveal=self._on_main_edge_revealed,
            on_inside=self.update_readability_alpha,
            on_displays_changed=self._on_displays_changed,
            on_display_enter=self._on_main_display_enter)
        self.root.after(90, self._initialize_display_position)
        self.refresh_list()
        sticky_notes = self.store.notes_by_kind("sticky")
        if sticky_notes:
            self.select_note(sticky_notes[0]["id"])
        else:
            self.clear_editor()
        self.root.after(500, self.check_reminders)
        if self.store.settings.get("llama_cpp_autostart"):
            self.root.after(800, self.autostart_local_llama)
        self.tray = TrayManager()
        self.tray.start()
        self.root.after(250, self.poll_tray_events)
        self.root.after(300, self.poll_instance_requests)

    def _set_app_id(self):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LightNote.Desktop.1")
        except (AttributeError, OSError):
            pass

    @staticmethod
    def _apply_rounded_region(window, radius=16):
        """在 Windows 层为无标题栏窗口设置真正的四角圆角区域。"""
        try:
            width = window.winfo_width()
            height = window.winfo_height()
            if width <= 1 or height <= 1:
                return
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hwnd = ctypes.c_void_p(window.winfo_id())
            # Tk 的 winfo_id 可能指向内部窗口，GA_ROOT 才是实际顶层窗口。
            user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.GetAncestor.restype = ctypes.c_void_p
            hwnd = user32.GetAncestor(hwnd, 2) or hwnd
            gdi32.CreateRoundRectRgn.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int]
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            user32.SetWindowRgn.restype = ctypes.c_int
            gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
            gdi32.DeleteObject.restype = ctypes.c_bool
            region = gdi32.CreateRoundRectRgn(
                0, 0, width + 1, height + 1, radius * 2, radius * 2)
            if not region:
                return
            # SetWindowRgn 成功后由 Windows 接管 region，不再手动释放。
            if not user32.SetWindowRgn(hwnd, region, True):
                gdi32.DeleteObject(region)
        except (AttributeError, OSError, tk.TclError, TypeError):
            # 非 Windows 环境或窗口尚未完成映射时保留矩形窗口，不影响启动。
            pass

    def _schedule_rounded_region(self, window, radius):
        """延迟刷新窗口圆角，避免 SetWindowRgn 与 Configure 事件互相触发。"""
        if window is self.root:
            if self.rounded_region_applying:
                return
            if self.rounded_region_job:
                try:
                    self.root.after_cancel(self.rounded_region_job)
                except tk.TclError:
                    pass
            self.rounded_region_job = self.root.after(
                80, lambda: self._apply_rounded_region_safely(window, radius))

    def _apply_rounded_region_safely(self, window, radius):
        self.rounded_region_job = None
        self.rounded_region_applying = True
        try:
            self._apply_rounded_region(window, radius)
        finally:
            self.rounded_region_applying = False

    def _enforce_ui_scaling(self):
        value = 4 / 3
        try:
            current = float(self.root.tk.call("tk", "scaling"))
            if abs(current - value) > 0.01:
                self.root.tk.call("tk", "scaling", value)
        except (tk.TclError, TypeError, ValueError):
            pass

    def _show_in_taskbar(self):
        """让无系统标题栏窗口仍显示在 Windows 任务栏中。"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            style = (style & ~0x00000080) | 0x00040000
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
            self.root.after(80, lambda: self._apply_rounded_region(self.root, radius=18))
        except (AttributeError, OSError):
            pass

    def _initialize_display_position(self):
        if self.closing:
            return
        saved = self.store.settings.get("window_bounds")
        displays = enumerate_displays()
        if isinstance(saved, list) and len(saved) == 4:
            bounds = tuple(int(value) for value in saved)
            x, y = ensure_visible_position(bounds, displays)
            set_window_position(self.root, x, y)
        display = display_for_bounds(window_bounds(self.root), displays)
        self.main_dpi_scaler = WindowDpiScaler(
            self.root, user_factor=UI_FONT_SCALINGS.get(self.ui_font_size, 1.0),
            base_min_size=(320, 420))
        self.main_dpi_scaler.capture_tree(self.quick_rail)
        if display:
            previous_dpi = int(self.store.settings.get("window_dpi") or 96)
            self.main_dpi_scaler.apply(display.dpi, previous_dpi=previous_dpi)
            self.section_nav.set_visual_scale(display.dpi / 96)
            self.titlebar.configure(height=round(34 * display.dpi / 96))
            self.edge_controller.gap = round(self.EDGE_GAP * display.dpi / 96)
            self.edge_controller.visible_size = max(
                self.HIDDEN_SIZE, round(self.HIDDEN_SIZE * display.dpi / 96))
        self.edge_controller.start()
        self._apply_rounded_region(self.root)
        self.root.after_idle(self.position_quick_rail)

    def _on_main_edge_hidden(self, edge):
        self.hidden_edge = edge
        self.stop_all_quick_pulses()
        self.quick_rail.withdraw()

    def _on_main_edge_revealed(self):
        self.hidden_edge = None
        self.root.after(20, self.sync_quick_visibility)

    def _on_displays_changed(self, _displays):
        self.root.after_idle(lambda: self.update_compact_layout(self.root.winfo_width()))
        self.root.after_idle(self.adjust_responsive_sash)
        self.root.after_idle(self.position_quick_rail)

    def _on_main_display_enter(self, display):
        if not self.main_dpi_scaler:
            return
        self.main_dpi_scaler.apply(display.dpi)
        scale = display.dpi / 96
        self.section_nav.set_visual_scale(scale)
        self.titlebar.configure(height=round(34 * scale))
        self.edge_controller.gap = round(self.EDGE_GAP * scale)
        self.edge_controller.visible_size = max(
            self.HIDDEN_SIZE, round(self.HIDDEN_SIZE * scale))
        self.root.after_idle(self.refresh_quick_rail)
        self.root.after_idle(self.enforce_news_clean_layout)

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        self.style = style
        # ttk 下拉框展开后由内部 Listbox 绘制，单独设置其字体才能与输入框一致。
        self.root.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", 12))

        self.titlebar = tk.Frame(self.root, height=34, padx=8)
        self.titlebar.pack(fill="x")
        self.titlebar.pack_propagate(False)
        self.app_title = tk.Label(self.titlebar, text="✦ 轻笺",
                                  font=("Microsoft YaHei UI", 10), anchor="w")
        self.app_title.pack(side="left", fill="y")
        self.close_button = tk.Button(self.titlebar, text="×", command=self.on_close,
                                      relief="flat", bd=0, width=4, font=("Arial", 13))
        self.close_button.pack(side="right", fill="y")
        self.min_button = tk.Button(self.titlebar, text="—", command=self.minimize_window,
                                    relief="flat", bd=0, width=4, font=("Arial", 11))
        self.min_button.pack(side="right", fill="y")
        self.panel_widgets.extend([self.titlebar])

        self.section_nav = SegmentedNav(self.root, self.switch_section)
        self.section_nav.pack(fill="x", padx=8, pady=(5, 1))
        self.bg_widgets.append(self.section_nav)

        toolbar = tk.Frame(self.root, padx=8, pady=7)
        self.toolbar = toolbar
        toolbar.pack(fill="x")
        self.bg_widgets.append(toolbar)
        self.new_button_text = tk.StringVar(value="＋ 新建便签")
        # 工具栏按钮使用与顶部板块标签接近的字号，避免 Canvas 按钮因未继承
        # Tk 缩放而显得过小。
        toolbar_font = ("Microsoft YaHei UI", 14)
        self.new_button = ModernButton(toolbar, textvariable=None, command=self.add_note,
                                       width=90, height=34, radius=9, font=toolbar_font)
        # 兼容 update_toolbar_labels 中对新按钮文字的动态修改
        self._new_button_text_var = self.new_button_text
        self.new_button._text_var = self._new_button_text_var
        self.new_button.pack(side="left")
        self.pending_button = ModernButton(toolbar, text="待办",
                                           command=lambda: self.set_task_view("pending"),
                                           style="ghost", width=72, height=34, radius=9,
                                           font=toolbar_font)
        self.pending_button.pack(side="left", padx=4)
        self.task_button = ModernButton(
            toolbar, text="已完成", command=lambda: self.set_task_view("completed"),
            style="ghost", width=82, height=34, radius=9, font=toolbar_font)
        self.task_button.pack(side="left", padx=4)
        self.settings_button_text = tk.StringVar(value="⚙ 设置")
        self.settings_button = ttk.Button(toolbar, textvariable=self.settings_button_text,
                                          command=self.toggle_settings)
        self.calendar_button = ttk.Button(toolbar, text="📅 日历视图", command=self.open_calendar_view)
        self.news_refresh_button = ttk.Button(toolbar, text="刷新", command=lambda: self.load_news(True))
        self.news_home_button = ttk.Button(toolbar, text="打开 AI HOT", command=self.open_news_home)
        self.news_source_button = ttk.Button(toolbar, text="打开原文", command=self.open_news_source)
        self.record_button = ttk.Button(
            toolbar, text="🎙 录音", command=lambda: self.open_ai_interview("recording"))

        self.news_tabs_frame = tk.Frame(self.root, padx=8, pady=2)
        self.bg_widgets.append(self.news_tabs_frame)
        self.news_daily_tab = ttk.Button(
            self.news_tabs_frame, text="AI 日报", style="NewsTab.TButton",
            command=lambda: self.switch_news_mode("daily"))
        self.news_flash_tab = ttk.Button(
            self.news_tabs_frame, text="免费模型快讯", style="NewsTab.TButton",
            command=lambda: self.switch_news_mode("flash"))
        self.news_daily_tab.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.news_flash_tab.pack(side="left", fill="x", expand=True, padx=(2, 0))

        self.ai_interview_frame = tk.Frame(self.root, padx=8, pady=3)
        self.bg_widgets.append(self.ai_interview_frame)
        self.ai_interview_button = ttk.Button(
            self.ai_interview_frame, text="AI面试复盘", command=self.open_ai_interview)
        self.ai_interview_button.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.ai_meeting_button = ttk.Button(
            self.ai_interview_frame, text="AI会议总结",
            command=lambda: self.open_ai_interview("meeting"))
        self.ai_meeting_button.pack(side="left", fill="x", expand=True, padx=(2, 0))

        self.top_var = tk.BooleanVar(value=self.store.settings["topmost"])
        self.top_label_var = tk.StringVar()
        self.settings_frame = tk.Frame(self.root, padx=10, pady=7)
        self.bg_widgets.append(self.settings_frame)
        # 设置板块直接从顶部导航下方开始，不再重复显示”设置”标题。
        self.settings_contrast_labels = []
        checks_row = tk.Frame(self.settings_frame)
        checks_row.pack(fill="x", pady=(0, 5))
        self.bg_widgets.append(checks_row)
        self.top_check = tk.Checkbutton(checks_row, textvariable=self.top_label_var,
                                        variable=self.top_var, command=self.toggle_topmost,
                                        indicatoron=False, relief="flat", bd=0, padx=4,
                                        cursor="hand2")
        self.top_check.pack(side="left")
        self.edge_var = tk.BooleanVar(value=self.store.settings["edge_hide"])
        self.edge_label_var = tk.StringVar()
        self.edge_check = tk.Checkbutton(checks_row, textvariable=self.edge_label_var,
                                         variable=self.edge_var, command=self.toggle_edge,
                                         indicatoron=False, relief="flat", bd=0, padx=4,
                                         cursor="hand2")
        self.edge_check.pack(side="left", padx=7)
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self.autostart_check = tk.Checkbutton(checks_row, text="□ 开机启动",
                                              variable=self.autostart_var,
                                              command=self.toggle_autostart,
                                              indicatoron=False, relief="flat", bd=0, padx=4,
                                              cursor="hand2")
        self.autostart_check.pack(side="left")
        self.sync_check_labels()

        alpha_row = tk.Frame(self.settings_frame)
        alpha_row.pack(fill="x")
        self.bg_widgets.append(alpha_row)
        alpha_label = tk.Label(alpha_row, text="透明度")
        alpha_label.pack(side="left")
        self.muted_labels.append(alpha_label)
        self.alpha_var = tk.DoubleVar(value=float(self.store.settings["alpha"]))
        ttk.Scale(alpha_row, from_=0.45, to=1.0, variable=self.alpha_var,
                  command=self.change_alpha).pack(side="left", fill="x", expand=True, padx=8)

        color_label = tk.Label(alpha_row, text="皮肤更换")
        color_label.pack(side="left", padx=(4, 3))
        self.settings_contrast_labels.append(color_label)
        self.theme_var = tk.StringVar(value=self.theme_name)
        self.theme_box = ttk.Combobox(alpha_row, textvariable=self.theme_var,
                                      values=list(THEMES), state="readonly", width=8,
                                      font=("Microsoft YaHei UI", 12))
        self.theme_box.pack(side="left")

        font_row = tk.Frame(self.settings_frame)
        font_row.pack(fill="x", pady=(6, 0))
        self.bg_widgets.append(font_row)
        font_label = tk.Label(font_row, text="界面字号", anchor="w")
        font_label.pack(side="left")
        self.settings_contrast_labels.append(font_label)
        self.ui_font_var = tk.StringVar(value=self.ui_font_size)
        self.ui_font_box = ttk.Combobox(
            font_row, textvariable=self.ui_font_var,
            values=list(UI_FONT_SCALINGS), state="readonly", width=7)
        self.ui_font_box.pack(side="left", padx=8)
        font_hint = tk.Label(font_row, text="刷新轻笺后生效", anchor="w")
        font_hint.pack(side="left")
        self.muted_labels.append(font_hint)

        ai_settings = tk.Frame(self.settings_frame, pady=10)
        ai_settings.pack(fill="x")
        self.bg_widgets.append(ai_settings)
        ai_title = tk.Label(ai_settings, text="AI与语音模型",
                            font=("Microsoft YaHei UI", 11, "bold"), anchor="w")
        ai_title.pack(fill="x", pady=(3, 6))
        self.settings_contrast_labels.append(ai_title)
        provider_mode = self.store.settings.get("ai_provider_mode", "step_plan")
        if provider_mode not in AI_PROVIDER_LABELS:
            provider_mode = "step_plan"
        self._active_ai_provider_mode = provider_mode
        self.ai_provider_var = tk.StringVar(value=AI_PROVIDER_LABELS[provider_mode])
        self.ai_base_url_var = tk.StringVar(value=self.store.settings.get("ai_base_url", ""))
        self.ai_model_var = tk.StringVar(value=self.store.settings.get("ai_model", ""))
        self.ai_reasoning_var = tk.StringVar(
            value=self.store.settings.get("ai_reasoning_effort", "low"))
        question_asr_mode = self.store.settings.get("question_asr_mode", "auto")
        self.question_asr_var = tk.StringVar(
            value=QUESTION_ASR_LABELS.get(question_asr_mode, "自动（SenseVoice优先）"))
        self.ai_token_var = tk.StringVar(
            value=self.TOKEN_MASK if load_ai_token(provider_mode) else "")
        self.ai_setting_entries = []

        def setting_entry(label_text, variable, secret=False):
            row = tk.Frame(ai_settings)
            row.pack(fill="x", pady=2)
            self.bg_widgets.append(row)
            label = tk.Label(row, text=label_text, width=9, anchor="w")
            label.pack(side="left")
            self.settings_contrast_labels.append(label)
            entry = tk.Entry(row, textvariable=variable, relief="solid", bd=1,
                             show="•" if secret else "")
            entry.pack(side="left", fill="x", expand=True, ipady=3)
            self.ai_setting_entries.append(entry)
            return entry

        provider_row = tk.Frame(ai_settings)
        provider_row.pack(fill="x", pady=2)
        self.bg_widgets.append(provider_row)
        provider_label = tk.Label(provider_row, text="文本大模型", width=9, anchor="w")
        provider_label.pack(side="left")
        self.settings_contrast_labels.append(provider_label)
        self.ai_provider_box = ttk.Combobox(
            provider_row, textvariable=self.ai_provider_var,
            values=list(AI_PROVIDER_OPTIONS), state="readonly")
        self.ai_provider_box.pack(side="left", fill="x", expand=True)
        self.ai_provider_box.bind("<<ComboboxSelected>>", self.change_ai_provider)

        self.ai_base_url_entry = setting_entry("接口地址", self.ai_base_url_var)
        self.ai_base_url_entry.bind("<FocusOut>", self.refresh_ai_provider, add="+")

        model_row = tk.Frame(ai_settings)
        model_row.pack(fill="x", pady=2)
        self.bg_widgets.append(model_row)
        model_label = tk.Label(model_row, text="模型名称", width=9, anchor="w")
        model_label.pack(side="left")
        self.settings_contrast_labels.append(model_label)
        self.ai_model_entry = tk.Entry(
            model_row, textvariable=self.ai_model_var, relief="solid", bd=1)
        self.ai_setting_entries.append(self.ai_model_entry)
        self.ai_model_button = tk.Menubutton(
            model_row, textvariable=self.ai_model_var, anchor="w", relief="solid", bd=1,
            indicatoron=True, cursor="hand2", takefocus=1)
        self.ai_model_button.pack(side="left", fill="x", expand=True, ipady=3)
        self.ai_model_menu = tk.Menu(self.ai_model_button, tearoff=False)
        self.ai_model_button.configure(menu=self.ai_model_menu)
        self.ai_model_menu.bind("<<MenuSelect>>", self.on_ai_model_menu_hover)
        self.ai_model_menu.bind("<Unmap>", lambda _event: self.hide_ai_hint())
        self.ai_model_button.bind(
            "<Return>", lambda _event: self.open_ai_menu(
                self.ai_model_menu, self.ai_model_button))
        self.ai_model_button.bind(
            "<Down>", lambda _event: self.open_ai_menu(
                self.ai_model_menu, self.ai_model_button))
        self.ai_model_description_var = tk.StringVar()
        self.ai_model_description = tk.Label(
            ai_settings, textvariable=self.ai_model_description_var, anchor="w",
            justify="left", wraplength=220)
        self.ai_model_description.pack(fill="x", padx=(72, 0), pady=(0, 2))
        self.muted_labels.append(self.ai_model_description)

        reasoning_row = tk.Frame(ai_settings)
        reasoning_row.pack(fill="x", pady=2)
        self.bg_widgets.append(reasoning_row)
        reasoning_label = tk.Label(reasoning_row, text="推理强度", width=9, anchor="w")
        reasoning_label.pack(side="left")
        self.settings_contrast_labels.append(reasoning_label)
        self.ai_reasoning_button = tk.Menubutton(
            reasoning_row, textvariable=self.ai_reasoning_var, anchor="w", relief="solid",
            bd=1, indicatoron=True, cursor="hand2", takefocus=1)
        self.ai_reasoning_button.pack(side="left", fill="x", expand=True, ipady=3)
        self.ai_reasoning_menu = tk.Menu(self.ai_reasoning_button, tearoff=False)
        self.ai_reasoning_button.configure(menu=self.ai_reasoning_menu)
        for effort in REASONING_EFFORTS:
            self.ai_reasoning_menu.add_command(
                label=effort, command=lambda value=effort: self.select_ai_reasoning(value))
        self.ai_reasoning_menu.bind("<<MenuSelect>>", self.on_ai_reasoning_menu_hover)
        self.ai_reasoning_menu.bind("<Unmap>", lambda _event: self.hide_ai_hint())
        self.ai_reasoning_button.bind(
            "<Return>", lambda _event: self.open_ai_menu(
                self.ai_reasoning_menu, self.ai_reasoning_button))
        self.ai_reasoning_button.bind(
            "<Down>", lambda _event: self.open_ai_menu(
                self.ai_reasoning_menu, self.ai_reasoning_button))
        self.ai_reasoning_description_var = tk.StringVar()
        self.ai_reasoning_description = tk.Label(
            ai_settings, textvariable=self.ai_reasoning_description_var, anchor="w",
            justify="left", wraplength=220)
        self.ai_reasoning_description.pack(fill="x", padx=(72, 0), pady=(0, 2))
        self.muted_labels.append(self.ai_reasoning_description)

        self.ai_token_entry = setting_entry("API Key", self.ai_token_var, True)
        self.ai_token_entry.bind("<FocusIn>", self.clear_ai_token_mask)
        self.ai_token_entry.bind("<FocusOut>", self.restore_ai_token_mask)

        self.llama_runtime_frame = tk.Frame(ai_settings)
        self.llama_runtime_frame.pack(fill="x", pady=(3, 1))
        self.bg_widgets.append(self.llama_runtime_frame)
        self.llama_executable_var = tk.StringVar(
            value=self.store.settings.get("llama_cpp_executable", ""))
        self.llama_model_path_var = tk.StringVar(
            value=self.store.settings.get("llama_cpp_model_path", ""))
        self.llama_autostart_var = tk.BooleanVar(
            value=bool(self.store.settings.get("llama_cpp_autostart", False)))

        def runtime_path_row(label_text, variable, command):
            row = tk.Frame(self.llama_runtime_frame)
            row.pack(fill="x", pady=2)
            self.bg_widgets.append(row)
            label = tk.Label(row, text=label_text, width=9, anchor="w")
            label.pack(side="left")
            self.settings_contrast_labels.append(label)
            entry = tk.Entry(row, textvariable=variable, relief="solid", bd=1)
            entry.pack(side="left", fill="x", expand=True, ipady=3)
            ttk.Button(row, text="选择", width=5, command=command).pack(side="left", padx=(4, 0))
            return entry

        self.llama_executable_entry = runtime_path_row(
            "服务程序", self.llama_executable_var, self.choose_llama_executable)
        self.llama_model_path_entry = runtime_path_row(
            "GGUF模型", self.llama_model_path_var, self.choose_llama_model)
        runtime_options = tk.Frame(self.llama_runtime_frame)
        runtime_options.pack(fill="x", pady=2)
        self.bg_widgets.append(runtime_options)
        self.llama_autostart_check = tk.Checkbutton(
            runtime_options, text="随轻笺自动启动本地大模型",
            variable=self.llama_autostart_var, anchor="w")
        self.llama_autostart_check.pack(side="left")
        self.llama_start_button = ttk.Button(
            runtime_options, text="启动/检查", command=self.start_local_llama_from_settings)
        self.llama_start_button.pack(side="right")
        self.llama_runtime_status_var = tk.StringVar(value="本地服务：尚未检查")
        self.llama_runtime_status = tk.Label(
            self.llama_runtime_frame, textvariable=self.llama_runtime_status_var,
            anchor="w", justify="left", wraplength=220)
        self.llama_runtime_status.pack(fill="x", padx=(72, 0), pady=(0, 2))
        self.muted_labels.append(self.llama_runtime_status)
        self.ai_hint_window = None
        ai_settings.bind("<Configure>", self.update_ai_description_wrap, add="+")
        self.refresh_ai_provider()
        self.select_ai_reasoning(self.ai_reasoning_var.get())
        try:
            voice_status = SenseVoiceTranscriber().model_status()
        except Exception:
            voice_status = {"ready": False, "missing": ["独立环境"]}
        asr_row = tk.Frame(ai_settings)
        asr_row.pack(fill="x", pady=2)
        self.bg_widgets.append(asr_row)
        asr_label = tk.Label(asr_row, text="提问识别", width=9, anchor="w")
        asr_label.pack(side="left")
        self.question_asr_box = ttk.Combobox(
            asr_row, textvariable=self.question_asr_var,
            values=list(QUESTION_ASR_OPTIONS), state="readonly")
        self.question_asr_box.pack(side="left", fill="x", expand=True)
        self.settings_contrast_labels.append(asr_label)
        asr_help = tk.Label(
            ai_settings,
            text="自动模式优先使用本地SenseVoice；连续问题按15秒内部块识别并拼接，最长约75秒。仅本地失败时调用在线StepAudio。",
            anchor="w", justify="left", wraplength=220)
        asr_help.pack(fill="x", padx=(72, 0), pady=(0, 2))
        self.muted_labels.append(asr_help)
        voice_rows = (
            ("会后转写", "SenseVoice-Small（本地）"),
            ("语音分段", "FSMN-VAD（已启用）"),
            ("多人标签", "CAM++（已启用）"),
            ("模型状态", "已就绪" if voice_status["ready"] else
             "缺少：" + "、".join(voice_status["missing"])),
        )
        for label_text, value_text in voice_rows:
            row = tk.Frame(ai_settings)
            row.pack(fill="x", pady=2)
            self.bg_widgets.append(row)
            label = tk.Label(row, text=label_text, width=9, anchor="w")
            label.pack(side="left")
            value = tk.Label(row, text=value_text, anchor="w", relief="solid", bd=1,
                             padx=4, pady=3)
            value.pack(side="left", fill="x", expand=True)
            self.settings_contrast_labels.extend((label, value))
        self.ai_settings_status_var = tk.StringVar()
        self.ai_status = tk.Label(ai_settings, textvariable=self.ai_settings_status_var,
                                  anchor="w", justify="left", wraplength=220)
        self.ai_status.pack(fill="x", pady=(6, 3))
        self.settings_contrast_labels.append(self.ai_status)
        ai_controls = tk.Frame(ai_settings)
        ai_controls.pack(fill="x", pady=(2, 0))
        self.bg_widgets.append(ai_controls)
        self.ai_test_button = ttk.Button(
            ai_controls, text="测试LLM", command=self.test_ai_connection)
        self.ai_test_button.pack(side="left", fill="x", expand=True)
        self.stepaudio_test_button = ttk.Button(
            ai_controls, text="测试StepAudio", command=self.test_stepaudio_connection)
        self.stepaudio_test_button.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(ai_controls, text="保存配置",
                   command=self.save_ai_configuration).pack(
                       side="left", fill="x", expand=True)
        self.ai_connection_testing = False
        self.stepaudio_connection_testing = False
        self.settings_visible = False

        # 窄窗口时这里的横向分隔条就是底部标题框的可拖动上边框。
        body = tk.PanedWindow(self.root, orient="horizontal", sashwidth=8,
                              sashpad=2, sashrelief="raised", bd=0, relief="flat")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        left = tk.Frame(body, width=145)
        right = tk.Frame(body)
        self.body = body
        self.left_panel = left
        self.right_panel = right
        self.panel_widgets.append(left)
        self.bg_widgets.append(right)
        body.add(left, minsize=125)
        body.add(right, minsize=220)

        self.listbox = tk.Listbox(left,
                                  selectforeground="white", relief="flat", bd=0,
                                  activestyle="none", font=("Microsoft YaHei UI", 10))
        self.note_filter_frame = tk.Frame(left, padx=4, pady=4)
        self.panel_widgets.append(self.note_filter_frame)
        self.category_filter_var = tk.StringVar(value="全部分类")
        self.category_filter = ttk.Combobox(self.note_filter_frame,
                                            textvariable=self.category_filter_var,
                                            state="readonly", width=10)
        self.category_filter.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.note_filter_frame, textvariable=self.search_var,
                                     relief="flat")
        self.search_entry.pack(fill="x", pady=(4, 0))
        # 在窄窗口中，列表填满底部面板，使其底边始终贴合轻笺窗口底边。
        self.listbox.pack(fill="both", expand=True, padx=4, pady=4)

        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(right, textvariable=self.title_var,
                                    relief="flat", font=("Microsoft YaHei UI", 15, "bold"))
        self.title_entry.pack(fill="x", padx=10, pady=(10, 5))
        self.news_title_var = tk.StringVar()
        self.news_title_label = tk.Label(
            right, textvariable=self.news_title_var, relief="flat",
            font=("Microsoft YaHei UI", 15, "bold"), anchor="nw",
            justify="left", padx=0, pady=0,
        )
        right.bind("<Configure>", self.update_news_title_wrap, add="+")
        self.editor = tk.Text(right, relief="flat",
                              wrap="word", undo=True, font=("Microsoft YaHei UI", 11),
                              padx=10, pady=8)
        self.editor.pack(fill="both", expand=True)
        self.editor.tag_configure("bold", font=("Microsoft YaHei UI", 11, "bold"))
        self.configure_task_checklist(self.editor)

        # 保留统计变量以兼容已有学习记录；不再显示学习积累按钮区域。
        self.learning_stats_var = tk.StringVar()

        reminder_actions = tk.Frame(right, padx=10, pady=5)
        self.reminder_actions = reminder_actions
        reminder_actions.pack(fill="x")
        self.bg_widgets.append(reminder_actions)
        ttk.Button(reminder_actions, text="✓ 完成", command=self.complete_current_reminder).pack(side="left")
        ttk.Button(reminder_actions, text="稍后", command=self.snooze_current_reminder).pack(side="left", padx=3)
        ttk.Button(reminder_actions, text="来源", command=self.open_current_source).pack(side="left")
        ttk.Button(reminder_actions, text="跳过", command=self.skip_current_reminder).pack(side="left", padx=3)
        ttk.Button(reminder_actions, text="暂停", command=self.pause_current_reminder).pack(side="left")

        # 保留提醒数据变量，兼容已有提醒数据；不再在便签编辑区显示提醒控件。
        self.reminder_var = tk.StringVar()

        self.status_var = tk.StringVar(value="本地保存")
        self.reminder_actions.pack_forget()
        self._build_quick_rail()
        self._build_resize_handles()












    def _build_resize_handles(self):
        """为无系统边框窗口补充左、右、底边和两个底角缩放热区。"""
        specs = {
            "left": ({"x": 0, "y": 34, "width": 6, "relheight": 1, "height": -40}, "size_we"),
            "right": ({"relx": 1, "x": -6, "y": 34, "width": 6, "relheight": 1, "height": -40}, "size_we"),
            "bottom": ({"x": 10, "rely": 1, "y": -6, "relwidth": 1, "width": -20, "height": 6}, "size_ns"),
            "bottom_left": ({"x": 0, "rely": 1, "y": -12, "width": 12, "height": 12}, "size_ne_sw"),
            "bottom_right": ({"relx": 1, "x": -12, "rely": 1, "y": -12, "width": 12, "height": 12}, "size_nw_se"),
        }
        self.resize_handles = []
        for edge, (placement, cursor) in specs.items():
            handle = tk.Frame(self.root, bd=0, cursor=cursor)
            handle.place(**placement)
            handle.bind("<ButtonPress-1>", lambda event, e=edge: self.start_resize(event, e))
            handle.bind("<B1-Motion>", self.resize_window)
            handle.bind("<ButtonRelease-1>", self.end_resize)
            handle.lift()
            self.resize_handles.append(handle)

    def start_resize(self, event, edge):
        self.reveal_from_edge()
        self.resizing = True
        self.resize_origin = {
            "edge": edge, "pointer_x": event.x_root, "pointer_y": event.y_root,
            "x": self.root.winfo_x(), "y": self.root.winfo_y(),
            "width": self.root.winfo_width(), "height": self.root.winfo_height(),
        }

    def resize_window(self, event):
        if not self.resizing or not self.resize_origin:
            return
        start = self.resize_origin
        dx = event.x_root - start["pointer_x"]
        dy = event.y_root - start["pointer_y"]
        edge = start["edge"]
        min_width, min_height = 320, 420
        x, y = start["x"], start["y"]
        width, height = start["width"], start["height"]
        if edge in ("right", "bottom_right"):
            width = max(min_width, start["width"] + dx)
        if edge in ("left", "bottom_left"):
            width = max(min_width, start["width"] - dx)
            x = start["x"] + start["width"] - width
        if edge in ("bottom", "bottom_left", "bottom_right"):
            height = max(min_height, start["height"] + dy)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def end_resize(self, _event=None):
        if not self.resizing:
            return
        self.resizing = False
        self.resize_origin = None
        self.store.settings["geometry"] = self.root.geometry()
        self.store.save()

    def _bind_events(self):
        self.listbox.bind("<<ListboxSelect>>", self.on_list_select)
        self.listbox.bind("<Double-Button-1>", self.edit_selected_note)
        self.listbox.bind("<ButtonPress-1>", self.prepare_item_drag, add="+")
        self.listbox.bind("<B1-Motion>", self.track_item_drag, add="+")
        self.listbox.bind("<ButtonRelease-1>", self.end_item_drag, add="+")
        self.listbox.bind("<Button-3>", self.show_list_context_menu)
        self.listbox.bind("<Up>", lambda event: self.move_title_key(event, -1))
        self.listbox.bind("<Down>", lambda event: self.move_title_key(event, 1))
        self.listbox.bind("<Left>", lambda event: self.move_section_key(event, -1))
        self.listbox.bind("<Right>", lambda event: self.move_section_key(event, 1))
        self.title_var.trace_add("write", lambda *_: self.schedule_save())
        self.editor.bind("<<Modified>>", self.on_text_modified)
        self.bind_undo_redo(self.editor)
        self.theme_box.bind("<<ComboboxSelected>>", self.change_theme)
        self.ui_font_box.bind("<<ComboboxSelected>>", self.change_ui_font_size)
        self.category_filter.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())
        self.search_var.trace_add("write", lambda *_: self.refresh_list())
        for widget in (self.titlebar, self.app_title):
            widget.bind("<ButtonPress-1>", self.start_window_drag)
            widget.bind("<B1-Motion>", self.drag_window)
        self.root.bind("<Configure>", self.on_configure)
        self.body.bind("<Configure>", self.schedule_responsive_layout)
        self.body.bind("<ButtonRelease-1>", self.remember_compact_sash, add="+")
        self.root.bind("<Map>", self.on_window_map)
        self.root.bind("<Alt-Key-1>", lambda _e: self.switch_section("reminder"))
        self.root.bind("<Alt-Key-2>", lambda _e: self.switch_section("sticky"))
        self.root.bind("<Alt-Key-3>", lambda _e: self.switch_section("journal"))
        self.root.bind("<Alt-Key-4>", lambda _e: self.switch_section("news"))
        for key, direction in (("<Left>", "left"), ("<Right>", "right"),
                               ("<Up>", "up"), ("<Down>", "down")):
            self.root.bind(key, lambda event, d=direction: self.handle_direction_key(event, d), add="+")
        self.root.bind("<Return>", self.activate_focused_control, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    @staticmethod
    def is_editing_widget(widget):
        return isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Scale, tk.Scale))

    def is_action_control(self, widget):
        if not isinstance(widget, (tk.Button, tk.Checkbutton, ttk.Button, ttk.Checkbutton)):
            return False
        if widget.winfo_toplevel() is not self.root or not widget.winfo_viewable():
            return False
        try:
            if isinstance(widget, (ttk.Button, ttk.Checkbutton)) and widget.instate(["disabled"]):
                return False
            return str(widget.cget("state")) != "disabled"
        except tk.TclError:
            return False

    def visible_action_controls(self):
        controls = []

        def visit(parent):
            for child in parent.winfo_children():
                if child.winfo_toplevel() is not self.root:
                    continue
                if self.is_action_control(child):
                    controls.append(child)
                visit(child)

        visit(self.root)
        return controls

    def handle_direction_key(self, event, direction):
        widget = event.widget
        if isinstance(widget, SegmentedNav) or self.is_editing_widget(widget):
            return None
        if self.is_action_control(widget):
            return self.focus_nearest_control(widget, direction)
        if direction in ("left", "right"):
            self.move_section(-1 if direction == "left" else 1)
            return "break"
        if direction in ("up", "down"):
            self.move_title(-1 if direction == "up" else 1)
            return "break"
        return None

    def focus_nearest_control(self, current, direction):
        cx = current.winfo_rootx() + current.winfo_width() / 2
        cy = current.winfo_rooty() + current.winfo_height() / 2
        candidates = []
        for widget in self.visible_action_controls():
            if widget is current:
                continue
            wx = widget.winfo_rootx() + widget.winfo_width() / 2
            wy = widget.winfo_rooty() + widget.winfo_height() / 2
            dx, dy = wx - cx, wy - cy
            if ((direction == "left" and dx >= -2) or
                    (direction == "right" and dx <= 2) or
                    (direction == "up" and dy >= -2) or
                    (direction == "down" and dy <= 2)):
                continue
            primary = abs(dx) if direction in ("left", "right") else abs(dy)
            secondary = abs(dy) if direction in ("left", "right") else abs(dx)
            candidates.append((primary * 3 + secondary, widget))
        if candidates:
            min(candidates, key=lambda item: item[0])[1].focus_set()
        return "break"

    def activate_focused_control(self, event):
        if self.is_action_control(event.widget):
            event.widget.invoke()
            return "break"
        return None

    def move_title_key(self, _event, step):
        self.move_title(step)
        return "break"

    def move_section_key(self, _event, step):
        self.move_section(step)
        return "break"

    def move_section(self, step):
        sections = [item[0] for item in SegmentedNav.SECTIONS]
        current = sections.index(self.current_section)
        self.switch_section(sections[(current + step) % len(sections)])

    def move_title(self, step):
        if self.current_section == "reminder":
            items = sorted(self.store.reminders, key=lambda item: item.get("remind_at", ""))
            current_id = self.current_reminder.get("id") if self.current_reminder else None
        elif self.current_section == "news":
            items = self.news_items
            current_id = self.current_news.get("permalink") if self.current_news else None
        else:
            items = self.visible_notes()
            current_id = self.current.get("id") if self.current else None
        identities = [item.get("permalink") if self.current_section == "news" else item.get("id")
                      for item in items]
        current_index = identities.index(current_id) if current_id in identities else None
        target_index = cyclic_index(len(items), current_index, step)
        if target_index is None:
            return
        if self.current_section == "reminder":
            self.select_reminder(items[target_index]["id"])
        elif self.current_section == "news":
            self.select_news(target_index)
        else:
            self.select_note(items[target_index]["id"])
        self.listbox.focus_set()

    def move_news(self, step):
        if not self.news_items:
            return
        selection = self.listbox.curselection()
        current = selection[0] if selection else 0
        target = min(len(self.news_items) - 1, max(0, current + step))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(target)
        self.listbox.activate(target)
        self.listbox.see(target)
        self.select_news(target)

    def _build_quick_rail(self):
        self.quick_transparent = "#ff00ff"
        self.quick_rail = tk.Toplevel(self.root)
        self.quick_rail.overrideredirect(True)
        self.quick_rail.attributes("-topmost", self.top_var.get())
        self.quick_rail.configure(bg=self.quick_transparent)
        try:
            self.quick_rail.attributes("-transparentcolor", self.quick_transparent)
        except tk.TclError:
            pass
        self.quick_rail_frame = tk.Frame(self.quick_rail, bg=self.quick_transparent, bd=0)
        self.quick_rail_frame.pack(fill="both", expand=True)
        self.quick_buttons_frame = tk.Frame(self.quick_rail_frame, bg=self.quick_transparent)
        self.quick_buttons_frame.pack(fill="both", expand=True)
        self.quick_buttons = []
        self.quick_drop_label = None
        self.refresh_quick_rail()

    def refresh_quick_rail(self):
        for button in getattr(self, "quick_buttons", []):
            self.stop_quick_pulse(button)
        for child in self.quick_buttons_frame.winfo_children():
            child.destroy()
        self.quick_buttons = []
        width, cell_height, wraplength, quick_font = self._quick_rail_metrics()
        self.quick_cell_width = width
        self.quick_cell_height = cell_height
        self.quick_wraplength = wraplength
        self.quick_font = quick_font
        self.quick_layout_root_width = self.root.winfo_width()
        for slot in self.store.quick_slots[:8]:
            text = slot.get("label") or "快捷"
            cell = tk.Frame(self.quick_buttons_frame, width=width, height=cell_height,
                            bg=self.quick_transparent, bd=0)
            cell.pack(fill="x", pady=3)
            cell.pack_propagate(False)
            # 快捷标签改用统一的圆角 Canvas 按钮，避免原生 tk.Button 的方角边框。
            button = ModernButton(
                cell, text=self._wrap_quick_text(text, quick_font, wraplength),
                command=lambda s=slot: self.open_quick_slot(s),
                style="ghost", width=width, height=cell_height, radius=12,
                font=quick_font, cursor="hand2", attached_side="right",
                canvas_bg=self.quick_transparent)
            button.pack(fill="both", expand=True)
            button.bind("<Enter>", lambda _e, b=button: self.start_quick_pulse(b))
            button.bind("<Leave>", lambda _e, b=button: self.stop_quick_pulse(b))
            button.bind("<Button-3>", lambda e, s=slot: self.show_quick_menu(e, s))
            self.quick_buttons.append(button)
        self.position_quick_rail()
        self.sync_quick_visibility()

    @staticmethod
    def _wrap_quick_text(text, font, wraplength):
        """按字体实际宽度换行，确保圆角快捷标签中的长标题完整显示。"""
        lines = []
        current = ""
        for char in str(text):
            candidate = current + char
            if current and font.measure(candidate) > wraplength:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current or not lines:
            lines.append(current)
        return "\n".join(lines)

    def _quick_rail_metrics(self):
        """根据完整标题、当前窗口宽度和 DPI 计算统一的快捷标签尺寸。"""
        dpi_scale = ((self.main_dpi_scaler.current_dpi / 96)
                     if self.main_dpi_scaler and self.main_dpi_scaler.current_dpi else 1.0)
        user_scale = UI_FONT_SCALINGS.get(self.ui_font_size, 1.0)
        quick_font = tkfont.Font(
            root=self.quick_rail, family="Microsoft YaHei UI",
            size=max(8, round(9 * dpi_scale * user_scale)))
        titles = [(slot.get("label") or "快捷") for slot in self.store.quick_slots[:8]]
        if self.quick_drop_label:
            titles.append("固定到快捷标签")
        longest = max((quick_font.measure(title) for title in titles), default=0)
        minimum = round(68 * dpi_scale)
        maximum = max(minimum, round(max(self.root.winfo_width(), 320) * 0.30))
        width = min(maximum, max(minimum, longest + round(18 * dpi_scale)))
        wraplength = max(round(46 * dpi_scale), width - round(12 * dpi_scale))

        # Tk 的 wraplength 会自动换行；这里预估最长标签行数，使每个标签等高且完整显示。
        max_lines = 1
        for title in titles:
            line_width = 0
            lines = 1
            for char in title:
                char_width = quick_font.measure(char)
                if line_width and line_width + char_width > wraplength:
                    lines += 1
                    line_width = char_width
                else:
                    line_width += char_width
            max_lines = max(max_lines, lines)
        line_height = quick_font.metrics("linespace")
        cell_height = max(round(44 * dpi_scale),
                          max_lines * line_height + round(12 * dpi_scale))
        return width, cell_height, wraplength, quick_font

    @staticmethod
    def blend_color(first, second, ratio):
        """按比例混合两个 #RRGGBB 颜色，用于轻量悬停动画。"""
        a = tuple(int(first[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(second[i:i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(x + (y - x) * ratio) for x, y in zip(a, b))
        return "#" + "".join(f"{value:02x}" for value in mixed)

    def start_quick_pulse(self, button):
        if isinstance(button, ModernButton):
            return
        self.stop_quick_pulse(button, restore=False)
        button._quick_pulse_phase = 0
        button._quick_pulse_active = True
        self.animate_quick_pulse(button)

    def animate_quick_pulse(self, button):
        if not getattr(button, "_quick_pulse_active", False) or not button.winfo_exists():
            return
        phase = button._quick_pulse_phase
        ratio = phase / 5 if phase <= 5 else (10 - phase) / 5
        button.configure(bg=self.blend_color(self.colors["panel"], self.colors["accent"], ratio))
        button._quick_pulse_phase = (phase + 1) % 10
        button._quick_pulse_job = button.after(85, lambda: self.animate_quick_pulse(button))

    def stop_quick_pulse(self, button, restore=True):
        button._quick_pulse_active = False
        job = getattr(button, "_quick_pulse_job", None)
        if job:
            try:
                button.after_cancel(job)
            except tk.TclError:
                pass
            button._quick_pulse_job = None
        if restore and button.winfo_exists():
            button.configure(bg=self.colors["panel"])

    def stop_all_quick_pulses(self):
        for button in getattr(self, "quick_buttons", []):
            self.stop_quick_pulse(button)

    def show_quick_menu(self, event, slot):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="打开", command=lambda: self.open_quick_slot(slot))
        menu.add_separator()
        menu.add_command(label="从快捷标签移除", command=lambda: self.remove_quick_slot(slot))
        menu.tk_popup(event.x_root, event.y_root)

    def position_quick_rail(self):
        if not hasattr(self, "quick_rail") or not self.quick_rail.winfo_exists():
            return
        dpi_scale = ((self.main_dpi_scaler.current_dpi / 96)
                     if self.main_dpi_scaler and self.main_dpi_scaler.current_dpi else 1.0)
        width = getattr(self, "quick_cell_width", round(68 * dpi_scale))
        x = self.root.winfo_x() - width
        root_bounds = window_bounds(self.root)
        displays = (self.edge_controller.displays if hasattr(self, "edge_controller")
                    else enumerate_displays())
        display = display_for_bounds(root_bounds, displays)
        if display and x < display.work_left:
            x = self.root.winfo_x() + self.root.winfo_width()
        y = self.root.winfo_y() + round(115 * dpi_scale)
        count = len(self.store.quick_slots[:8]) + (1 if self.quick_drop_label else 0)
        cell_height = getattr(self, "quick_cell_height", round(44 * dpi_scale))
        row_gap = round(6 * dpi_scale)
        height = max(cell_height, (cell_height + row_gap) * max(1, count))
        if display:
            if x + width > display.work_right:
                x = max(display.work_left, self.root.winfo_x() - width)
            y = min(max(y, display.work_top), max(display.work_top, display.work_bottom - height))
        self.quick_rail.geometry(f"{width}x{height}")
        self._apply_rounded_region(self.quick_rail, radius=14)
        set_window_position(self.quick_rail, x, y)

    def sync_quick_visibility(self):
        should_show = (self.root.state() == "normal" and not self.hidden_edge and
                       (bool(self.store.quick_slots) or getattr(self, "dragging_item", False)))
        if should_show:
            self.quick_rail.deiconify()
            self.position_quick_rail()
            self.quick_rail.after(40, lambda: self._apply_rounded_region(self.quick_rail, radius=14))
        else:
            self.stop_all_quick_pulses()
            self.quick_rail.withdraw()

    def add_quick_source(self, source_type, source_id, title):
        self.store.add_quick_slot(source_type, source_id, title or "快捷")
        self.refresh_quick_rail()

    def add_current_quick(self):
        source = self.current_reminder or self.current
        if not source:
            return
        source_type = "reminder" if self.current_reminder else source.get("kind", "sticky")
        self.add_quick_source(source_type, source.get("id", ""), source.get("title", "快捷"))

    def remove_quick_slot(self, slot):
        self.store.remove_quick_slot(slot.get("source_type", ""), slot.get("source_id", ""))
        self.refresh_quick_rail()

    def open_quick_slot(self, slot):
        self.show_window()
        self.open_item(slot.get("source_type", "sticky"), slot.get("source_id", ""))

    def open_item(self, source_type: str, source_id: str):
        """统一按类型和条目 ID 打开内容，不经过板块默认首项。"""
        if source_type == "reminder":
            if not any(item.get("id") == source_id for item in self.store.reminders):
                self.status_var.set("快捷标签对应的提醒已不存在")
                return
            if self.current_section != "reminder":
                self.switch_section("reminder", select_default=False)
            self.select_reminder(source_id)
            return

        note = next((item for item in self.store.notes if item.get("id") == source_id), None)
        if not note:
            self.status_var.set("快捷标签对应的内容已不存在")
            return
        section = note.get("kind", source_type)
        if self.current_section != section:
            self.switch_section(section, select_default=False)
        if section == "journal" and note not in self.visible_notes():
            self.category_filter_var.set("全部分类")
            self.search_var.set("")
        self.select_note(source_id)

    def list_source_at(self, index):
        if self.current_section == "reminder":
            items = sorted(self.store.reminders, key=lambda r: r.get("remind_at", ""))
            if index < len(items):
                item = items[index]
                return {"source_type": "reminder", "source_id": item.get("id", ""),
                        "title": item.get("title", "未命名提醒")}
        else:
            items = self.visible_notes()
            if index < len(items):
                item = items[index]
                return {"source_type": item.get("kind", self.current_section),
                        "source_id": item.get("id", ""),
                        "title": item.get("title", "无标题")}
        return None

    def prepare_item_drag(self, event):
        index = self.listbox.nearest(event.y)
        box = self.listbox.bbox(index)
        if not box or not (box[1] <= event.y <= box[1] + box[3]):
            self.drag_candidate = None
            return
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.drag_candidate = {"x": event.x_root, "y": event.y_root,
                               "source": self.list_source_at(index)}

    def track_item_drag(self, event):
        if getattr(self, "dragging_item", False) or not self.drag_candidate:
            return
        dx = event.x_root - self.drag_candidate["x"]
        dy = event.y_root - self.drag_candidate["y"]
        if dx * dx + dy * dy >= 100:
            self.start_item_drag(self.drag_candidate.get("source"))

    def start_item_drag(self, source=None):
        if not source:
            return
        self.drag_source = source
        self.dragging_item = True
        if not self.quick_drop_label:
            width, cell_height, wraplength, quick_font = self._quick_rail_metrics()
            self.quick_cell_width = width
            self.quick_cell_height = cell_height
            self.quick_drop_label = tk.Frame(self.quick_buttons_frame,
                                             width=width, height=cell_height,
                                             bg=self.colors["accent"], bd=0)
            self.quick_drop_label.pack(fill="x", pady=3)
            self.quick_drop_label.pack_propagate(False)
            preview = source.get("title") or "快捷"
            tk.Label(self.quick_drop_label, text=f"固定\n{preview}", bg=self.colors["accent"],
                     fg="white", wraplength=wraplength, font=quick_font,
                     justify="center").pack(fill="both", expand=True)
        self.sync_quick_visibility()

    def end_item_drag(self, event):
        if not getattr(self, "dragging_item", False):
            self.drag_candidate = None
            return
        self.dragging_item = False
        qx, qy = self.quick_rail.winfo_rootx(), self.quick_rail.winfo_rooty()
        dropped_on_rail = (qx <= event.x_root <= qx + self.quick_rail.winfo_width() and
                           qy <= event.y_root <= qy + self.quick_rail.winfo_height())
        if self.quick_drop_label:
            self.quick_drop_label.destroy()
            self.quick_drop_label = None
        if dropped_on_rail and self.drag_source:
            source = self.drag_source
            self.add_quick_source(source["source_type"], source["source_id"], source["title"])
        else:
            self.refresh_quick_rail()
        self.drag_candidate = None
        self.drag_source = None

    def show_list_context_menu(self, event):
        index = self.listbox.nearest(event.y)
        box = self.listbox.bbox(index)
        if not box or not (box[1] <= event.y <= box[1] + box[3]):
            return
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.on_list_select()
        source = self.list_source_at(index)
        if not source:
            return
        fixed = any(q.get("source_type") == source["source_type"] and
                    q.get("source_id") == source["source_id"] for q in self.store.quick_slots)
        is_sticky_journal = source.get("source_type") in ("sticky", "journal")
        # 右键菜单与标题列表使用同一字体，随界面缩放保持一致。
        menu = tk.Menu(self.root, tearoff=False, font=self.listbox.cget("font"))
        if is_sticky_journal:
            menu.add_command(label="复制",
                             command=lambda s=source: self.copy_note_by_source(s))
        if is_sticky_journal or source.get("source_type") == "reminder":
            menu.add_command(label="删除",
                             command=lambda s=source: self.delete_note_by_source(s))
        menu.add_command(label="已固定到快捷标签" if fixed else "固定到快捷标签",
                         state="disabled" if fixed else "normal",
                         command=lambda s=source: self.add_quick_source(
                             s["source_type"], s["source_id"], s["title"]))
        menu.tk_popup(event.x_root, event.y_root)

    def update_compact_layout(self, width):
        compact = width < 500
        if compact == self.compact_mode:
            return
        self.compact_mode = compact
        self.compact_sash_user_resized = False
        self.wide_sash_user_resized = False
        for pane in (self.left_panel, self.right_panel):
            if str(pane) in self.body.panes():
                self.body.forget(pane)
        if compact:
            self.body.configure(orient="vertical")
            self.body.add(self.left_panel, minsize=180)
            self.body.add(self.right_panel, before=self.left_panel, minsize=120)
            self.category_filter.pack_forget()
            self.search_entry.pack_forget()
            self.category_filter.pack(side="left", fill="x", expand=True)
            self.search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self.root.after_idle(lambda: self.position_compact_sash(force=True))
        else:
            self.body.configure(orient="horizontal")
            self.body.add(self.right_panel, minsize=220)
            self.body.add(self.left_panel, before=self.right_panel, minsize=125)
            self.category_filter.pack_forget()
            self.search_entry.pack_forget()
            self.category_filter.pack(fill="x")
            self.search_entry.pack(fill="x", pady=(4, 0))
            self.root.after_idle(self.position_wide_sash)

    def remember_compact_sash(self, event):
        """用户拖动窄窗口分隔条后，保留其手动设置的标题框高度。"""
        if len(self.body.panes()) != 2:
            return
        try:
            sash_x, sash_y = self.body.sash_coord(0)
        except tk.TclError:
            return
        if self.compact_mode and abs(event.y - sash_y) <= 12:
            self.compact_sash_user_resized = True
        elif not self.compact_mode and abs(event.x - sash_x) <= 12:
            self.wide_sash_user_resized = True

    def position_compact_sash(self, force=False):
        if (not self.compact_mode or len(self.body.panes()) != 2 or
                not self.body.winfo_ismapped() or
                (self.compact_sash_user_resized and not force)):
            return
        available = self.body.winfo_height()
        row_height = tkfont.Font(font=self.listbox.cget("font")).metrics("linespace") + 4
        filter_height = 36 if self.current_section == "journal" else 0
        # 默认高度严格按当前标题条数计算；标题框底部由下方面板自动贴住窗口底边。
        list_height = max(1, self.listbox.size()) * row_height + filter_height + 12
        list_height = min(list_height, max(row_height + filter_height + 12, available - 120))
        sash_y = min(max(120, available - list_height), max(120, available - 40))
        self.body.sash_place(0, 0, sash_y)

    def position_wide_sash(self):
        if (self.compact_mode or self.wide_sash_user_resized or
                len(self.body.panes()) != 2 or not self.body.winfo_ismapped()):
            return
        font = tkfont.Font(font=self.listbox.cget("font"))
        titles = self.listbox.get(0, "end")
        longest = max((font.measure(str(title)) for title in titles), default=110)
        maximum = min(300, max(125, int(self.body.winfo_width() * 0.42)))
        self.body.sash_place(0, max(125, min(longest + 24, maximum)), 0)

    def adjust_responsive_sash(self):
        self.layout_job = None
        if self.settings_visible:
            return
        if not self.compact_mode:
            self.position_wide_sash()
        self.enforce_news_clean_layout()

    def schedule_responsive_layout(self, _event=None):
        if self.layout_job:
            try:
                self.root.after_cancel(self.layout_job)
            except tk.TclError:
                pass
        self.layout_job = self.root.after_idle(self.adjust_responsive_sash)

    def update_news_title_wrap(self, event=None):
        if self.current_section != "news":
            return
        width = event.width if event is not None else self.right_panel.winfo_width()
        self.news_title_label.configure(wraplength=max(120, width - 20))

    def show_news_title(self, visible):
        if visible:
            self.title_entry.pack_forget()
            if not self.news_title_label.winfo_manager():
                self.news_title_label.pack(fill="x", padx=10, pady=(10, 5),
                                           before=self.editor)
            self.update_news_title_wrap()
        else:
            self.news_title_label.pack_forget()
            if not self.title_entry.winfo_manager():
                self.title_entry.pack(fill="x", padx=10, pady=(10, 5),
                                      before=self.editor)

    def enforce_news_clean_layout(self):
        """新闻板块只保留新闻控件，防止异步或跨屏布局恢复旧编辑控件。"""
        if self.current_section != "news":
            return
        for widget in (self.title_entry, self.reminder_actions,
                       self.note_filter_frame, self.ai_interview_frame):
            widget.pack_forget()
        self.show_news_title(True)

    def apply_theme(self, save=True):
        self.colors = THEMES.get(self.theme_name, THEMES["黄色"])
        c = self.colors
        self.root.configure(bg=c["bg"])
        # QQ 风格：容器面板透明（= root bg），让背景图透出；
        # 只有列表/编辑器/输入框等需要可读性的区域才用 panel 色。
        for widget in self.bg_widgets:
            widget.configure(bg=c["bg"])
        for widget in self.panel_widgets:
            widget.configure(bg=c["bg"])
        for label in self.muted_labels:
            label.configure(bg=c["bg"], fg=c["muted"])
        for label in self.settings_contrast_labels:
            label.configure(bg=c["bg"], fg=c["text"])
        self.app_title.configure(bg=c["bg"], fg=c["text"])
        self.titlebar.configure(bg=c["bg"])
        self.body.configure(bg=c["bg"])
        self.left_panel.configure(bg=c["bg"])
        if hasattr(self, "right_panel"):
            self.right_panel.configure(bg=c["bg"])
        for button in (self.min_button, self.close_button):
            button.configure(bg=c["bg"], fg=c["text"],
                             activebackground=c["accent"], activeforeground="white")
        for check in (self.top_check, self.edge_check, self.autostart_check):
            check.configure(bg=c["bg"], fg=c["text"], selectcolor=c["bg"],
                            activebackground=c["bg"], activeforeground=c["accent"])
        self.section_nav.set_theme(c)
        self.section_nav.set_counts({"reminder": sum(
            1 for r in self.store.reminders if r.get("status") in ("pending", "notified"))})
        if self.compact_mode and not self.compact_sash_user_resized:
            self.root.after_idle(self.position_compact_sash)
        self.root.after_idle(self.adjust_responsive_sash)
        for handle in self.resize_handles:
            handle.configure(bg=c["bg"])
        self.quick_rail_frame.configure(bg=self.quick_transparent)
        self.quick_buttons_frame.configure(bg=self.quick_transparent)
        for button in getattr(self, "quick_buttons", []):
            self.stop_quick_pulse(button)
            if isinstance(button, ModernButton):
                button.apply_palette(c)
            else:
                button.configure(bg=c["panel"], fg=c["text"],
                                 activebackground=c["accent"], activeforeground="white")
        self.quick_rail.attributes("-alpha", float(self.store.settings["alpha"]))
        # 内容区域保留 panel 色，形成 QQ 风格的可读面板。
        self.listbox.configure(bg=c["panel"], fg=c["text"],
                               selectbackground=c["accent"])
        for widget in (self.title_entry, self.editor):
            widget.configure(bg=c["panel"], fg=c["text"], insertbackground=c["text"])
        self.news_title_label.configure(bg=c["panel"], fg=c["text"])
        for entry in self.ai_setting_entries:
            entry.configure(bg=c["input"], fg=c["text"], insertbackground=c["text"])
        for button in (self.ai_model_button, self.ai_reasoning_button):
            button.configure(bg=c["input"], fg=c["text"], activebackground=c["accent"],
                             activeforeground="white")
        for menu in (self.ai_model_menu, self.ai_reasoning_menu):
            menu.configure(bg=c["panel"], fg=c["text"], activebackground=c["accent"],
                           activeforeground="white")
        self.style.configure("TButton", background=c["panel"], foreground=c["text"],
                             padding=(10, 6), font=("Microsoft YaHei UI", 10),
                             borderwidth=0, focusthickness=0)
        self.style.map("TButton",
                       background=[("selected", c["accent"]), ("active", c["accent"]),
                                   ("pressed", c["accent"]), ("disabled", c["panel"])],
                       foreground=[("selected", "white"), ("active", "white"),
                                   ("disabled", c["muted"])])
        self.style.configure("TCheckbutton", background=c["panel"], foreground=c["text"],
                             focuscolor=c["accent"])
        self.style.configure("Horizontal.TScale", background=c["bg"], troughcolor=c["panel"])
        self.style.configure("TCombobox", fieldbackground=c["input"], foreground=c["text"],
                             background=c["panel"], bordercolor=c["panel"],
                             arrowcolor=c["text"], padding=(6, 4),
                             font=("Microsoft YaHei UI", 12))
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", c["input"]), ("disabled", c["panel"])],
                       foreground=[("readonly", c["text"]), ("disabled", c["muted"])])
        toolbar_font = self.style.lookup("TButton", "font") or "TkDefaultFont"
        toolbar_padding = self.style.lookup("TButton", "padding") or 5
        self.style.configure("NewsTab.TButton", background=c["panel"], foreground=c["text"],
                             font=toolbar_font, padding=toolbar_padding)
        self.style.map("NewsTab.TButton",
                       background=[("selected", c["accent"]), ("active", c["accent"])],
                       foreground=[("selected", "white"), ("active", "white")])
        # 通知所有 ModernButton/ModernEntry/ModernToggle 同步新调色板
        apply_palette_to_all(c)
        self.update_news_tabs()
        if save:
            self.store.settings["theme"] = self.theme_name
            self.store.save()

    def change_theme(self, _event=None):
        self.theme_name = self.theme_var.get()
        self.apply_theme()

    @staticmethod
    def ai_profile_key(provider, field):
        return f"ai_{provider}_{field}"

    def remember_ai_profile(self, provider=None):
        provider = provider or self._active_ai_provider_mode
        self.store.settings[self.ai_profile_key(provider, "base_url")] = (
            self.ai_base_url_var.get().strip().rstrip("/"))
        self.store.settings[self.ai_profile_key(provider, "model")] = (
            self.ai_model_var.get().strip())
        self.store.settings[self.ai_profile_key(provider, "reasoning_effort")] = (
            self.ai_reasoning_var.get())

    def load_ai_profile(self, provider):
        self.ai_base_url_var.set(self.store.settings.get(
            self.ai_profile_key(provider, "base_url"), ""))
        self.ai_model_var.set(self.store.settings.get(
            self.ai_profile_key(provider, "model"), ""))
        self.ai_reasoning_var.set(self.store.settings.get(
            self.ai_profile_key(provider, "reasoning_effort"), "low"))
        self.ai_token_var.set(self.TOKEN_MASK if load_ai_token(provider) else "")
        self.select_ai_reasoning(self.ai_reasoning_var.get())

    def change_ai_provider(self, _event=None):
        provider = AI_PROVIDER_OPTIONS.get(self.ai_provider_var.get(), "custom")
        if provider == self._active_ai_provider_mode:
            return
        self.remember_ai_profile(self._active_ai_provider_mode)
        self._active_ai_provider_mode = provider
        self.store.settings["ai_provider_mode"] = provider
        self.load_ai_profile(provider)
        self.refresh_ai_provider()
        self.ai_settings_status_var.set(
            "已切换配置；保存后生效。不同提供商的地址、模型和API Key分别保存。")

    def refresh_ai_provider(self, _event=None):
        provider = self._active_ai_provider_mode
        if provider == "step_plan":
            self.ai_model_entry.pack_forget()
            if not self.ai_model_button.winfo_manager():
                self.ai_model_button.pack(side="left", fill="x", expand=True, ipady=3)
            self.ai_model_menu.delete(0, "end")
            for model in STEP_PLAN_MODELS:
                self.ai_model_menu.add_command(
                    label=model, command=lambda value=model: self.select_ai_model(value))
            if self.ai_model_var.get() not in STEP_PLAN_MODELS:
                self.ai_model_var.set(next(iter(STEP_PLAN_MODELS)))
            self.ai_model_description_var.set(
                STEP_PLAN_MODELS.get(self.ai_model_var.get(), ""))
        else:
            self.ai_model_button.pack_forget()
            if not self.ai_model_entry.winfo_manager():
                self.ai_model_entry.pack(side="left", fill="x", expand=True, ipady=3)
            if provider == "llama_cpp":
                self.ai_model_description_var.set(
                    "本地 llama.cpp：实时回答关闭显式Thinking；会后复盘保留推理。")
            else:
                self.ai_model_description_var.set(
                    "自定义兼容接口：请手动填写服务支持的模型 ID。")
        if hasattr(self, "llama_runtime_frame"):
            if provider == "llama_cpp":
                options = {"fill": "x", "pady": (3, 1)}
                if hasattr(self, "ai_status"):
                    options["before"] = self.ai_status
                self.llama_runtime_frame.pack(**options)
            else:
                self.llama_runtime_frame.pack_forget()

    def select_ai_model(self, model):
        self.ai_model_var.set(model)
        self.ai_model_description_var.set(STEP_PLAN_MODELS.get(model, ""))
        self.hide_ai_hint()

    def select_ai_reasoning(self, effort):
        if effort not in REASONING_EFFORTS:
            effort = "low"
        self.ai_reasoning_var.set(effort)
        self.ai_reasoning_description_var.set(REASONING_EFFORTS[effort])
        self.hide_ai_hint()

    def update_ai_description_wrap(self, event):
        wrap = max(140, event.width - 82)
        self.ai_model_description.configure(wraplength=wrap)
        self.ai_reasoning_description.configure(wraplength=wrap)

    @staticmethod
    def open_ai_menu(menu, button):
        menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
        return "break"

    def on_ai_model_menu_hover(self, event):
        active = event.widget.index("active")
        if active is None:
            self.hide_ai_hint()
            return
        model = event.widget.entrycget(active, "label")
        self.show_ai_hint(STEP_PLAN_MODELS.get(model, ""))

    def on_ai_reasoning_menu_hover(self, event):
        active = event.widget.index("active")
        if active is None:
            self.hide_ai_hint()
            return
        effort = event.widget.entrycget(active, "label")
        self.show_ai_hint(REASONING_EFFORTS.get(effort, ""))

    def show_ai_hint(self, text):
        if not text:
            self.hide_ai_hint()
            return
        if self.ai_hint_window is None or not self.ai_hint_window.winfo_exists():
            self.ai_hint_window = tk.Toplevel(self.root)
            self.ai_hint_window.overrideredirect(True)
            self.ai_hint_window.attributes("-topmost", True)
            self.ai_hint_label = tk.Label(
                self.ai_hint_window, justify="left", anchor="w", wraplength=360,
                padx=9, pady=7, relief="solid", bd=1)
            self.ai_hint_label.pack()
        c = self.colors
        self.ai_hint_label.configure(
            text=text, bg=c["panel"], fg=c["text"], highlightbackground=c["muted"])
        x, y = self.root.winfo_pointerxy()
        self.ai_hint_window.geometry(f"+{x + 14}+{y + 14}")
        self.ai_hint_window.deiconify()

    def hide_ai_hint(self):
        window = getattr(self, "ai_hint_window", None)
        if window is not None and window.winfo_exists():
            window.withdraw()

    def ai_configuration(self, provider=None):
        provider = provider or self.store.settings.get("ai_provider_mode", "step_plan")
        if provider == self.store.settings.get("ai_provider_mode", "step_plan"):
            base_url = self.store.settings.get("ai_base_url", "")
            model = self.store.settings.get("ai_model", "")
            reasoning = self.store.settings.get("ai_reasoning_effort", "low")
        else:
            base_url = self.store.settings.get(self.ai_profile_key(provider, "base_url"), "")
            model = self.store.settings.get(self.ai_profile_key(provider, "model"), "")
            reasoning = self.store.settings.get(
                self.ai_profile_key(provider, "reasoning_effort"), "low")
        return {
            "base_url": base_url,
            "model": model,
            "timeout": self.store.settings.get("ai_timeout", 180),
            "reasoning_effort": reasoning,
            "api_key": load_ai_token(provider),
        }

    def clear_ai_token_mask(self, _event=None):
        if self.ai_token_var.get() == self.TOKEN_MASK:
            self.ai_token_var.set("")

    def restore_ai_token_mask(self, _event=None):
        if (not self.ai_token_var.get().strip() and
                load_ai_token(self._active_ai_provider_mode)):
            self.ai_token_var.set(self.TOKEN_MASK)

    @staticmethod
    def _path_is_on_c_drive(value):
        try:
            return Path(value).resolve().drive.upper() == "C:"
        except (OSError, ValueError):
            return False

    def choose_llama_executable(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选择 llama-server.exe",
            filetypes=[("llama.cpp 服务程序", "llama-server.exe"), ("EXE", "*.exe")])
        if not path:
            return
        if self._path_is_on_c_drive(path):
            messagebox.showerror("路径不允许", "llama.cpp 服务程序不能放在C盘。", parent=self.root)
            return
        self.llama_executable_var.set(path)

    def choose_llama_model(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选择 GGUF 本地模型",
            filetypes=[("GGUF模型", "*.gguf")])
        if not path:
            return
        if self._path_is_on_c_drive(path):
            messagebox.showerror("路径不允许", "GGUF模型不能放在C盘。", parent=self.root)
            return
        self.llama_model_path_var.set(path)

    def ensure_local_llama_ready(self, provider="llama_cpp", progress=None):
        if provider != "llama_cpp":
            return ""
        settings = self.store.settings
        return self.llama_runtime.ensure_ready(
            executable=settings.get("llama_cpp_executable", ""),
            model_path=settings.get("llama_cpp_model_path", ""),
            base_url=settings.get("ai_llama_cpp_base_url", "http://127.0.0.1:8080/v1"),
            model_alias=settings.get("ai_llama_cpp_model", "qwen3-8b-local"),
            timeout=settings.get("ai_timeout", 180), progress=progress)

    def _start_local_llama_async(self, notify=False):
        self.llama_runtime_status_var.set("本地服务：正在检查并加载模型……")
        if hasattr(self, "llama_start_button"):
            self.llama_start_button.configure(state="disabled")

        def worker():
            try:
                message = self.ensure_local_llama_ready()
                self.root.after(0, lambda: finish(True, message))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc): finish(False, error))

        def finish(success, message):
            if self.exiting:
                return
            if hasattr(self, "llama_start_button"):
                self.llama_start_button.configure(state="normal")
            self.llama_runtime_status_var.set(
                "本地服务：已就绪" if success else "本地服务：启动失败 - " + message)
            if notify:
                if success:
                    messagebox.showinfo("本地大模型", message, parent=self.root)
                else:
                    messagebox.showerror("本地大模型启动失败", message, parent=self.root)

        threading.Thread(target=worker, name="llama-runtime-start", daemon=True).start()

    def start_local_llama_from_settings(self):
        if not self.save_ai_configuration(notify=False):
            return
        self._start_local_llama_async(notify=True)

    def autostart_local_llama(self):
        if self.exiting or not self.store.settings.get("llama_cpp_autostart"):
            return
        self._start_local_llama_async(notify=False)

    def save_ai_configuration(self, notify=True):
        provider = self._active_ai_provider_mode
        base_url = self.ai_base_url_var.get().strip().rstrip("/")
        self.refresh_ai_provider()
        model = self.ai_model_var.get().strip()
        if not base_url.startswith(("https://", "http://")) or not model:
            self.ai_settings_status_var.set("请填写有效的接口地址和模型名称")
            return False
        token = self.ai_token_var.get().strip()
        if token == self.TOKEN_MASK:
            token = ""
        if token:
            if not save_ai_token(token, provider):
                self.ai_settings_status_var.set("Token写入Windows凭据管理器失败")
                return False
            self.ai_token_var.set(self.TOKEN_MASK)
        if not load_ai_token(provider):
            self.ai_settings_status_var.set("请填写并保存API Key；本地接口可使用占位值")
            return False
        llama_executable = self.llama_executable_var.get().strip()
        llama_model_path = self.llama_model_path_var.get().strip()
        if provider == "llama_cpp":
            if not llama_executable or not llama_model_path:
                self.ai_settings_status_var.set(
                    "请选择非C盘的 llama-server.exe 和 GGUF 模型文件")
                return False
            if (self._path_is_on_c_drive(llama_executable) or
                    self._path_is_on_c_drive(llama_model_path)):
                self.ai_settings_status_var.set("本地大模型程序和模型文件不能位于C盘")
                return False
        self.remember_ai_profile(provider)
        self.store.settings["ai_provider_mode"] = provider
        self.store.settings["ai_base_url"] = base_url
        self.store.settings["ai_model"] = model
        self.store.settings["ai_reasoning_effort"] = self.ai_reasoning_var.get()
        self.store.settings["question_asr_mode"] = QUESTION_ASR_OPTIONS.get(
            self.question_asr_var.get(), "auto")
        self.store.settings["llama_cpp_executable"] = llama_executable
        self.store.settings["llama_cpp_model_path"] = llama_model_path
        self.store.settings["llama_cpp_autostart"] = bool(self.llama_autostart_var.get())
        self.store.save()
        self.ai_settings_status_var.set("")
        if notify:
            messagebox.showinfo("AI配置", "配置已保存。Token未写入便签数据文件。", parent=self.root)
        return True

    def test_ai_connection(self):
        if self.ai_connection_testing:
            return
        if not self.save_ai_configuration(notify=False):
            return
        self.ai_connection_testing = True
        self.ai_test_button.configure(text="测试中…", state="disabled")
        self.ai_settings_status_var.set("正在测试LLM连接……")
        results = queue.Queue()

        def worker():
            try:
                self.ensure_local_llama_ready(self._active_ai_provider_mode)
                reply = stream_chat_completion(self.ai_configuration(), [
                    {"role": "system", "content": "只输出最终答案，不输出思考过程。"},
                    {"role": "user", "content": "请只回复：连接成功"},
                ], max_tokens=512)
                results.put((True, reply))
            except Exception as exc:
                results.put((False, str(exc)))

        threading.Thread(target=worker, name="ai-connection-test", daemon=True).start()

        def poll():
            try:
                success, message = results.get_nowait()
            except queue.Empty:
                if not self.exiting:
                    self.root.after(100, poll)
                return
            self.ai_settings_status_var.set(
                "LLM连接成功：" + message[:40] if success else "LLM连接失败：" + message)
            self.ai_connection_testing = False
            self.ai_test_button.configure(text="测试LLM", state="normal")

        self.root.after(100, poll)

    def test_stepaudio_connection(self):
        if self.stepaudio_connection_testing:
            return
        if not self.save_ai_configuration(notify=False):
            return
        self.stepaudio_connection_testing = True
        self.stepaudio_test_button.configure(text="测试中…", state="disabled")
        self.ai_settings_status_var.set("正在测试StepAudio接口、API Key和额度……")
        results = queue.Queue()

        def worker():
            try:
                config = self.ai_configuration("step_plan")
                config["timeout"] = 30
                message = StepAudioASR(config).test_connection()
                results.put((True, message))
            except Exception as exc:
                results.put((False, str(exc)))

        threading.Thread(
            target=worker, name="stepaudio-connection-test", daemon=True).start()

        def poll():
            try:
                success, message = results.get_nowait()
            except queue.Empty:
                if not self.exiting:
                    self.root.after(100, poll)
                return
            if success:
                self.ai_settings_status_var.set(
                    "StepAudio连接成功；可作为在线识别或本地失败备用。")
            else:
                mode = self.store.settings.get("question_asr_mode", "auto")
                fallback = ("；录音时将自动使用SenseVoice本地识别"
                            if mode == "auto" else "")
                self.ai_settings_status_var.set(
                    "StepAudio连接失败：" + message + fallback)
            self.stepaudio_connection_testing = False
            self.stepaudio_test_button.configure(text="测试StepAudio", state="normal")

        self.root.after(100, poll)

    def open_ai_interview(self, review_type="interview", show_recording=None,
                          source_text=None):
        recording_mode = review_type == "recording"
        is_meeting = review_type == "meeting"
        is_summary = review_type == "summary"
        dialog_name = ("录音转写" if recording_mode else
                       "摘要生成" if is_summary else
                       "AI会议总结" if is_meeting else "AI面试复盘")
        tasks = {} if recording_mode else (TRANSCRIPT_TASKS if is_summary else (
            MEETING_TASKS if is_meeting else INTERVIEW_TASKS))
        analyzer = None if recording_mode or is_summary else (analyze_meeting if is_meeting else analyze_interview)
        if show_recording is None:
            show_recording = recording_mode
        if self.current_section != "journal" or not self.current:
            if not recording_mode and not is_summary and source_text is None:
                messagebox.showinfo(dialog_name, "请先选择一篇需要分析的笔记。", parent=self.root)
                return
            source_id = None
            source_note = {"title": "录音转写", "content": source_text or "",
                           "tags": [], "category": ""}
        else:
            self.flush_save()
            source_id = self.current.get("id")
            source_note = next(
                (note for note in self.store.notes if note.get("id") == source_id), None)
            if not source_note:
                return
        if self.ai_dialog and self.ai_dialog.winfo_exists():
            self.ai_dialog.lift()
            return

        c = self.colors
        dialog = tk.Toplevel(self.root)
        self.ai_dialog = dialog
        dialog.title(dialog_name)
        # V2 起录音窗口不再使用旧版 DPI 换算后的尺寸。旧缓存曾在跨屏时把
        # 960×983 的窗口缩小到 640×560，挤掉录音和底部操作区。
        voice_layout_version = int(self.store.settings.get("voice_dialog_layout_version", 0) or 0)
        saved_voice_bounds = self.store.settings.get("voice_dialog_bounds")
        if (recording_mode and voice_layout_version >= 2 and
                isinstance(saved_voice_bounds, list) and len(saved_voice_bounds) == 4):
            dialog.geometry(
                f"{max(800, int(saved_voice_bounds[2]))}x{max(720, int(saved_voice_bounds[3]))}")
        else:
            # 以完整录音流程为基准：设备、录音提问助手、转写/摘要和底部保存操作
            # 必须同时可见，不能让输出框挤占这些操作区。
            dialog.geometry("960x820")
        dialog.minsize(800, 720)
        dialog.configure(bg=c["bg"])
        dialog.transient(self.root)
        dialog.attributes("-topmost", self.top_var.get())
        dialog.grid_rowconfigure(0, minsize=42)
        dialog.grid_rowconfigure(1, minsize=236)
        dialog.grid_rowconfigure(2, minsize=42)
        dialog.grid_rowconfigure(3, weight=1, minsize=160)
        dialog.grid_rowconfigure(4, minsize=28)
        dialog.grid_rowconfigure(5, minsize=40)
        dialog.grid_columnconfigure(0, weight=1)

        tk.Label(dialog, text=dialog_name, bg=c["bg"], fg=c["text"],
                 font=("Microsoft YaHei UI", 15, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        record_frame = tk.LabelFrame(dialog, text="录音转写（麦克风 + 会议声音）",
                                     bg=c["bg"], fg=c["text"], padx=8, pady=7)
        record_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 8))
        record_frame.grid_columnconfigure(1, weight=1)
        microphone_var = tk.StringVar()
        output_device_var = tk.StringVar()
        record_state_var = tk.StringVar(value="● 未录音")
        record_state_label = tk.Label(record_frame, textvariable=record_state_var,
                                      bg=c["bg"], fg=c["muted"], anchor="w")
        record_state_label.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 5))
        tk.Label(record_frame, text="我的麦克风", bg=c["bg"], fg=c["text"]).grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        microphone_box = ttk.Combobox(record_frame, textvariable=microphone_var,
                                      state="readonly")
        microphone_box.grid(row=1, column=1, sticky="ew", pady=2)
        tk.Label(record_frame, text="会议声音", bg=c["bg"], fg=c["text"]).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        output_device_box = ttk.Combobox(record_frame, textvariable=output_device_var,
                                         state="readonly")
        output_device_box.grid(row=2, column=1, sticky="ew", pady=2)
        if not show_recording:
            record_frame.grid_remove()

        record_controls = tk.Frame(record_frame, bg=c["bg"])
        record_controls.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        question_frame = tk.LabelFrame(
            record_frame, text="录音提问助手（仅分析会议方音轨）",
            bg=c["bg"], fg=c["text"], padx=7, pady=6)
        question_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        question_frame.grid_columnconfigure(0, weight=1)
        question_enabled_var = tk.BooleanVar(value=True)
        answer_mode = self.store.settings.get("interview_answer_mode", "hybrid")
        answer_mode_var = tk.StringVar(
            value=INTERVIEW_ANSWER_LABELS.get(answer_mode, "智能混合"))
        question_text_var = tk.StringVar(value="录音后将自动识别候选提问，不会自动发送给AI。")
        recognized_text_var = tk.StringVar(value="最近识别文字：等待会议声音……")
        question_status_var = tk.StringVar(value="")
        tk.Checkbutton(
            question_frame, text="启用准实时提问检测", variable=question_enabled_var,
            bg=c["bg"], fg=c["text"], selectcolor=c["panel"],
            activebackground=c["bg"], activeforeground=c["text"]).grid(
                row=0, column=0, sticky="w")
        tk.Label(question_frame, text="回答模式", bg=c["bg"], fg=c["text"]).grid(
            row=0, column=1, sticky="e", padx=(8, 4))
        answer_mode_box = ttk.Combobox(
            question_frame, textvariable=answer_mode_var,
            values=list(INTERVIEW_ANSWER_OPTIONS), state="readonly", width=11)
        answer_mode_box.grid(row=0, column=2, sticky="e")

        def save_answer_mode(_event=None):
            self.store.settings["interview_answer_mode"] = INTERVIEW_ANSWER_OPTIONS.get(
                answer_mode_var.get(), "hybrid")
            self.store.save()

        answer_mode_box.bind("<<ComboboxSelected>>", save_answer_mode)
        tk.Label(
            question_frame, textvariable=question_text_var, bg=c["input"], fg=c["text"],
            anchor="w", justify="left", wraplength=620, relief="solid", bd=1,
            padx=7, pady=6).grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)
        tk.Label(
            question_frame, textvariable=recognized_text_var, bg=c["bg"], fg=c["muted"],
            anchor="w", justify="left", wraplength=620).grid(
                row=2, column=0, columnspan=3, sticky="ew", pady=(1, 4))
        question_actions = tk.Frame(question_frame, bg=c["bg"])
        question_actions.grid(row=3, column=0, sticky="w")
        tk.Label(question_frame, textvariable=question_status_var, bg=c["bg"],
                 fg=c["muted"], anchor="w").grid(row=4, column=0, sticky="ew", pady=(3, 0))
        if not recording_mode:
            question_frame.grid_remove()

        task_frame = tk.Frame(dialog, bg=c["bg"])
        task_frame.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 8))
        for column in range(3):
            task_frame.grid_columnconfigure(column, weight=1, uniform="ai-tasks")

        output = tk.Text(dialog, bg=c["input"], fg=c["text"], insertbackground=c["text"],
                         wrap="word", relief="solid", bd=1,
                         font=("Microsoft YaHei UI", 10), padx=10, pady=10,
                         height=10)
        output.grid(row=3, column=0, sticky="nsew", padx=16)
        output.configure(state="disabled")
        initial_status = ("可开始录音或导入音频，转写后可查看转写内容或生成内容摘要。"
                          if recording_mode else "请选择一项 AI 分析任务。")
        status_var = tk.StringVar(value=initial_status)
        tk.Label(dialog, textvariable=status_var, bg=c["bg"], fg=c["muted"],
                 anchor="w").grid(row=4, column=0, sticky="ew", padx=16, pady=6)
        action_frame = tk.Frame(dialog, bg=c["bg"])
        action_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(2, 14))

        state = {"result": "", "task": "", "mode": "", "busy": False,
                 "voice_busy": False, "closing": False, "voice_warning": "",
                 "live_offset": 0, "question": None, "answered_question": "",
                 "question_answer_busy": False, "answer_stream": "",
                 "answer_timings": {}, "last_sources": []}
        result_queue = queue.Queue()
        voice_queue = queue.Queue()
        live_queue = queue.Queue()
        live_stop_event = threading.Event()
        question_detector = InterviewQuestionDetector()
        task_buttons = []
        analysis_entry_buttons = []
        device_maps = {"microphones": {}, "outputs": {}}

        def set_output(text):
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.insert("1.0", text)
            output.configure(state="disabled")

        def append_output(text):
            if not text:
                return
            output.configure(state="normal")
            output.insert("end", text)
            output.see("end")
            output.configure(state="disabled")

        def clear_question(message="等待识别新的问题……"):
            state["question"] = None
            state["last_sources"] = []
            question_detector.reset_context()
            question_text_var.set(message)
            question_send_button.state(["disabled"])
            question_ignore_button.state(["disabled"])
            cloud_answer_button.state(["disabled"])

        def ignore_question():
            clear_question("已忽略，继续监听会议方提问……")
            question_status_var.set("")

        def send_question_to_ai(force_provider=None):
            candidate = state.get("question")
            if not candidate or state["question_answer_busy"]:
                return
            state["question_answer_busy"] = True
            question_detector.reset_context()
            state["answer_stream"] = ""
            state["answer_timings"] = {}
            set_output("")
            question_send_button.state(["disabled"])
            cloud_answer_button.state(["disabled"])
            question_status_var.set("正在检索知识库……")
            question = candidate["question"]
            context = candidate.get("context", "")
            answer_started = time.perf_counter()

            def worker():
                try:
                    knowledge = candidate.get("knowledge")
                    if knowledge is None:
                        knowledge = self.interview_knowledge_base.search(
                            f"{question}\n{context}", limit=4)
                    retrieval_elapsed = time.perf_counter() - answer_started
                    provider, route_reason = (
                        (force_provider, "用户要求云端重新回答")
                        if force_provider else choose_interview_answer_provider(
                            self.store.settings.get("interview_answer_mode", "hybrid"),
                            candidate.get("terminology_risk") or {}, knowledge.sources))
                    if provider == "llama_cpp":
                        live_queue.put(("answer_stage", {
                            "stage": "runtime", "elapsed": retrieval_elapsed,
                            "sources": knowledge.sources, "provider": provider,
                            "route_reason": "正在检查并启动本地大模型"}))
                        self.ensure_local_llama_ready(provider)
                    config = self.ai_configuration(provider)
                    if not config.get("api_key"):
                        provider_name = "Step Plan云端" if provider == "step_plan" else "本地 llama.cpp"
                        raise AIServiceError(f"请先在设置中保存{provider_name}的API Key")
                    live_queue.put(("answer_stage", {
                        "stage": "knowledge", "elapsed": retrieval_elapsed,
                        "sources": knowledge.sources, "provider": provider,
                        "route_reason": route_reason}))
                    first_delta = True

                    def receive_delta(delta):
                        nonlocal first_delta
                        elapsed = time.perf_counter() - answer_started
                        live_queue.put(("answer_delta", {
                            "text": delta, "elapsed": elapsed,
                            "first": first_delta}))
                        first_delta = False

                    answer = answer_interview_question(
                        question, context, knowledge.context, config,
                        knowledge_sources=knowledge.sources,
                        on_delta=receive_delta)
                    live_queue.put(("answer", {
                        "question": question, "answer": answer,
                        "sources": knowledge.sources,
                        "provider": provider, "route_reason": route_reason,
                        "total_seconds": time.perf_counter() - answer_started,
                        "retrieval_seconds": retrieval_elapsed}))
                except Exception as exc:
                    live_queue.put(("answer_error", str(exc)))

            threading.Thread(
                target=worker, name="interview-question-answer", daemon=True).start()

        question_send_button = ttk.Button(
            question_actions, text="发送给AI", command=send_question_to_ai)
        question_send_button.pack(side="left", padx=(0, 5))
        question_ignore_button = ttk.Button(
            question_actions, text="忽略", command=ignore_question)
        question_ignore_button.pack(side="left")
        cloud_answer_button = ttk.Button(
            question_actions, text="云端重新回答",
            command=lambda: send_question_to_ai("step_plan"))
        cloud_answer_button.pack(side="left", padx=(5, 0))
        ttk.Button(
            question_actions, text="编辑术语词典",
            command=lambda: subprocess.Popen(
                ["notepad.exe", str(self.interview_terminology.path)])).pack(
                    side="left", padx=(5, 0))
        question_send_button.state(["disabled"])
        question_ignore_button.state(["disabled"])
        cloud_answer_button.state(["disabled"])

        def poll_live_results():
            if not dialog.winfo_exists():
                return
            while True:
                try:
                    event, value = live_queue.get_nowait()
                except queue.Empty:
                    break
                if event == "live_status":
                    question_status_var.set(value)
                elif event == "live_transcript":
                    recent = value.get("recent") or "（未识别出文字）"
                    corrected = value.get("corrected") or recent
                    combined = value.get("combined") or recent
                    display = f"最近原始识别片段：{recent}"
                    if corrected != recent:
                        display += f"\n术语纠正：{corrected}"
                    if combined not in (recent, corrected):
                        display += f"\n当前累计问题（最长75秒）：{combined}"
                    recognized_text_var.set(display)
                elif event == "question":
                    value["detected_at"] = time.perf_counter()
                    value["question_id"] = time.time_ns()
                    state["question"] = value
                    confidence = int(float(value.get("confidence", 0)) * 100)
                    context_count = len([
                        line for line in value.get("context", "").splitlines() if line.strip()])
                    question_text_var.set(
                        f"识别到提问（置信度 {confidence}%）：{value['question']}\n"
                        f"回答时将结合最近 {context_count} 句上下文理解完整问题。")
                    asr_seconds = value.get("asr_seconds")
                    timing = (f" ASR {asr_seconds:.1f}秒；" if asr_seconds is not None else " ")
                    question_status_var.set(
                        f"长问题已完成拼接；{timing}可立即发送；知识库正在后台检索。")
                    question_send_button.state(["!disabled"])
                    question_ignore_button.state(["!disabled"])

                    def prepare_knowledge(candidate):
                        started = time.perf_counter()
                        try:
                            knowledge = self.interview_knowledge_base.search(
                                f"{candidate['question']}\n{candidate.get('context', '')}", limit=4)
                            live_queue.put(("question_knowledge", {
                                "question_id": candidate["question_id"],
                                "knowledge": knowledge,
                                "elapsed": time.perf_counter() - started}))
                        except Exception as exc:
                            live_queue.put(("question_knowledge_error", {
                                "question_id": candidate["question_id"],
                                "error": str(exc)}))

                    threading.Thread(target=prepare_knowledge, args=(value,),
                                     name="interview-knowledge-prepare", daemon=True).start()
                elif event == "question_knowledge":
                    candidate = state.get("question")
                    if not candidate or candidate.get("question_id") != value["question_id"]:
                        continue
                    candidate["knowledge"] = value["knowledge"]
                    sources = value["knowledge"].sources
                    state["last_sources"] = sources
                    source_text = ("、".join(Path(item).name for item in sources[:3])
                                   if sources else "无直接命中，将使用通用知识")
                    if not state["question_answer_busy"]:
                        question_status_var.set(
                            f"知识库预检索 {value['elapsed']:.2f}秒；{source_text}。可立即发送。")
                elif event == "question_knowledge_error":
                    candidate = state.get("question")
                    if not candidate or candidate.get("question_id") != value["question_id"]:
                        continue
                    if not state["question_answer_busy"]:
                        question_status_var.set(
                            f"知识库预检索暂不可用：{value['error']}；仍可直接发送。")
                elif event == "answer_stage":
                    state["answer_timings"]["retrieval"] = value["elapsed"]
                    sources = value.get("sources") or []
                    provider_name = ("Step云端" if value.get("provider") == "step_plan"
                                     else "本地Llama")
                    route_text = f"{provider_name}（{value.get('route_reason', '')}）"
                    if sources:
                        names = "、".join(Path(source).name for source in sources[:3])
                        question_status_var.set(
                            f"{route_text}；知识库检索 {value['elapsed']:.2f}秒，命中：{names}；等待AI首字……")
                    else:
                        question_status_var.set(
                            f"{route_text}；知识库无直接命中；等待AI首字……")
                elif event == "answer_delta":
                    if value.get("first"):
                        state["answer_timings"]["first_token"] = value["elapsed"]
                        question_status_var.set(
                            f"AI首字 {value['elapsed']:.1f}秒，正在流式生成……")
                    state["answer_stream"] += value["text"]
                    append_output(value["text"])
                elif event == "answer":
                    state["question_answer_busy"] = False
                    state["answered_question"] = value["question"]
                    state["result"] = value["answer"]
                    state["mode"] = "question_answer"
                    state["answer_provider"] = value.get("provider")
                    if state["answer_stream"] != value["answer"]:
                        set_output(value["answer"])
                    sources = value.get("sources") or []
                    first_token = state["answer_timings"].get("first_token")
                    timing = f"首字 {first_token:.1f}秒，完成 {value['total_seconds']:.1f}秒。" if first_token else f"完成 {value['total_seconds']:.1f}秒。"
                    if sources:
                        names = "、".join(Path(source).name for source in sources[:3])
                        question_status_var.set(
                            f"回答已生成：{timing} 知识库命中：{names}")
                    else:
                        question_status_var.set(
                            f"回答已生成：{timing} 知识库无直接依据，使用通用知识。")
                    question_send_button.state(["!disabled"])
                    cloud_answer_button.state(
                        ["disabled"] if value.get("provider") == "step_plan"
                        else ["!disabled"])
                    for button in result_buttons:
                        button.state(["!disabled"])
                elif event in ("live_error", "answer_error"):
                    if event == "answer_error":
                        state["question_answer_busy"] = False
                        question_send_button.state(["!disabled"] if state.get("question") else ["disabled"])
                        cloud_answer_button.state(
                            ["!disabled"] if state.get("question") else ["disabled"])
                    if event == "answer_error" and state.get("last_sources"):
                        names = "、".join(Path(item).name for item in state["last_sources"][:3])
                        question_status_var.set(
                            f"知识库已命中：{names}；AI回答失败：{value}")
                    else:
                        question_status_var.set(("回答失败：" if event == "answer_error" else
                                                 "提问检测暂不可用：") + value)
            if (self.voice_recorder or state["question_answer_busy"] or
                    not live_queue.empty()):
                dialog.after(150, poll_live_results)

        def set_busy(busy):
            state["busy"] = busy
            for button in task_buttons:
                button.state(["disabled"] if busy else ["!disabled"])
            for button in result_buttons:
                button.state(["disabled"] if busy or not state["result"] else ["!disabled"])

        def set_voice_busy(busy):
            state["voice_busy"] = busy
            start_record_button.state(["disabled"] if busy else ["!disabled"])
            import_button.state(["disabled"] if busy else ["!disabled"])
            refresh_button.state(["disabled"] if busy else ["!disabled"])
            microphone_box.configure(state="disabled" if busy else "readonly")
            output_device_box.configure(state="disabled" if busy else "readonly")

        def poll_results():
            if not dialog.winfo_exists():
                return
            finished = False
            while True:
                try:
                    event, value = result_queue.get_nowait()
                except queue.Empty:
                    break
                if event == "status":
                    status_var.set(value)
                elif event == "result":
                    state["result"] = value
                    state["mode"] = "analysis"
                    set_output(value)
                    status_var.set("生成完成。请确认后复制、追加或生成新笔记。")
                    finished = True
                elif event == "error":
                    status_var.set("生成失败：" + value)
                    finished = True
            if finished:
                set_busy(False)
            elif state["busy"]:
                dialog.after(100, poll_results)

        def start_analysis(task):
            if state["busy"]:
                return
            live_note = next((item for item in self.store.notes if item.get("id") == source_id), None)
            analysis_text = source_text if source_text is not None else (
                live_note.get("content", "") if live_note else "")
            if not analysis_text.strip():
                messagebox.showinfo(dialog_name, "当前笔记还没有可分析的正文。", parent=dialog)
                return
            if not self.ai_configuration().get("api_key"):
                messagebox.showinfo(dialog_name, "请先在设置中保存API Key。", parent=dialog)
                return
            state["task"] = task
            state["mode"] = "analysis"
            state["result"] = ""
            set_output("")
            self.ai_cancel_event = threading.Event()
            set_busy(True)

            def worker():
                try:
                    provider = self.store.settings.get("ai_provider_mode", "step_plan")
                    self.ensure_local_llama_ready(provider)
                    result = analyzer(
                        task, analysis_text, self.ai_configuration(),
                        status=lambda message: result_queue.put(("status", message)),
                        cancelled=self.ai_cancel_event)
                    result_queue.put(("result", result))
                except Exception as exc:
                    result_queue.put(("error", str(exc)))

            thread_name = "ai-meeting-summary" if is_meeting else "ai-interview-review"
            threading.Thread(target=worker, name=thread_name, daemon=True).start()
            dialog.after(100, poll_results)

        def show_transcript():
            """在输出区显示已经完成的录音转写内容。"""
            transcript = state["result"].strip()
            if not transcript:
                messagebox.showinfo("录音转写", "请先完成录音转写或导入音频。", parent=dialog)
                return
            state["mode"] = "transcript"
            set_output(transcript)
            status_var.set("转写内容已显示。")

        def generate_summary():
            """将当前录音转写交给摘要生成窗口。"""
            transcript = state["result"].strip()
            if not transcript:
                messagebox.showinfo("录音转写", "请先完成录音转写或导入音频。", parent=dialog)
                return
            close_dialog()
            self.root.after_idle(
                lambda: self.open_ai_interview(
                    "summary", show_recording=False, source_text=transcript))

        if recording_mode:
            for column, (label, handler) in enumerate(
                    (("转写内容", show_transcript), ("摘要生成", generate_summary))):
                task_frame.grid_columnconfigure(column, weight=1, uniform="ai-tasks")
                button = ttk.Button(
                    task_frame, text=label, state="disabled",
                    command=handler)
                button.grid(row=0, column=column, sticky="ew", padx=2)
                analysis_entry_buttons.append(button)
        else:
            for column, (task, (label, _prompt)) in enumerate(tasks.items()):
                button = ttk.Button(task_frame, text=label,
                                    command=lambda value=task: start_analysis(value))
                button.grid(row=0, column=column, sticky="ew", padx=2)
                task_buttons.append(button)

        def device_label(item):
            return f"[{item['index']}] {item['name']}"

        def refresh_devices():
            try:
                devices = list_audio_devices()
            except VoiceServiceError as exc:
                status_var.set(str(exc))
                microphone_box.configure(values=())
                output_device_box.configure(values=())
                return
            for key, box, variable in (("microphones", microphone_box, microphone_var),
                                       ("outputs", output_device_box, output_device_var)):
                mapping = {device_label(item): item for item in devices[key]}
                device_maps[key] = mapping
                box.configure(values=list(mapping))
                setting_key = ("voice_microphone_name" if key == "microphones"
                               else "voice_output_name")
                preferred_terms = (("麦克风阵列", "realtek") if key == "microphones"
                                   else ("扬声器", "realtek", "loopback"))
                variable.set(preferred_device_label(
                    mapping, self.store.settings.get(setting_key, ""), preferred_terms))
            if not devices["outputs"]:
                status_var.set("没有发现WASAPI回环设备，请检查耳机/扬声器是否已启用。")
            else:
                status_var.set("设备已就绪。会议声音请选择当前实际播放会议的耳机或扬声器。")

        def remember_device(key, variable):
            device = device_maps[key].get(variable.get())
            if not device:
                return
            setting_key = ("voice_microphone_name" if key == "microphones"
                           else "voice_output_name")
            self.store.settings[setting_key] = device.get("name", "")
            self.store.save()

        microphone_box.bind(
            "<<ComboboxSelected>>",
            lambda _event: remember_device("microphones", microphone_var))
        output_device_box.bind(
            "<<ComboboxSelected>>",
            lambda _event: remember_device("outputs", output_device_var))

        def update_record_timer():
            recorder = self.voice_recorder
            if not dialog.winfo_exists() or not recorder or not recorder.is_recording:
                return
            seconds = int(recorder.elapsed_seconds)
            clock = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
            prefix = "● 已暂停" if recorder.is_paused else "● 正在录音"
            received = recorder.track_bytes
            microphone_state = "✓" if received["microphone"] else "…"
            meeting_state = "✓" if received["meeting"] else "未检测到"
            record_state_var.set(
                f"{prefix}  {clock}　麦克风 {microphone_state}　会议声音 {meeting_state}")
            dialog.after(250, update_record_timer)

        def run_live_question_detection(recorder):
            mode = self.store.settings.get("question_asr_mode", "auto")
            cloud_asr = StepAudioASR(self.ai_configuration("step_plan"))
            local_session = None
            local_disabled = mode == "stepaudio"
            offset = 0
            sequence = 0
            segmenter = MeetingUtteranceSegmenter(
                recorder.system_rate, recorder.system_channels,
                # 面试官在长问题中经常会自然停顿 1～2 秒。这里需要把短停顿
                # 保留在同一个问题窗口内，只有较长静音才认为问题已经结束。
                silence_seconds=3.5, max_seconds=15.0, overlap_seconds=1.0)
            continued_chunks = 0
            max_continued_chunks = 5
            recognized_parts = []
            terminology_risk = {
                "correction_applied": False, "matched_terms": [],
                "acronyms": [], "unknown_acronyms": []}

            def local_transcribe(chunk_path):
                nonlocal local_session
                if local_session is None:
                    local_session = SenseVoiceLiveSession()
                    local_session.start()
                segments = local_session.transcribe(chunk_path, "会议方")
                return " ".join(
                    item.get("text", "").strip() for item in segments
                    if item.get("text", "").strip())

            try:
                if not local_disabled:
                    live_queue.put(("live_status", "正在预热本地SenseVoice；仅识别会议声音……"))
                    try:
                        local_session = SenseVoiceLiveSession()
                        local_session.start()
                    except Exception as local_exc:
                        if mode == "sensevoice":
                            raise
                        local_disabled = True
                        live_queue.put((
                            "live_status",
                            f"SenseVoice启动失败，已切换StepAudio在线备用：{local_exc}"))
                if local_disabled:
                    live_queue.put(("live_status", "提问助手使用StepAudio在线识别，正在监听会议方音轨。"))
                else:
                    live_queue.put(("live_status", "SenseVoice已就绪，仅监听会议声音；麦克风只录制不识别。"))
                while not live_stop_event.wait(0.2):
                    if recorder.is_paused:
                        continue
                    raw, offset = recorder.read_meeting_audio(offset)
                    if not raw:
                        continue
                    for chunk in segmenter.feed_events(raw):
                        utterance = chunk.audio
                        sequence += 1
                        chunk_path = recorder.write_live_meeting_chunk(utterance, sequence)
                        asr_started = time.perf_counter()
                        try:
                            if local_disabled:
                                text = cloud_asr.transcribe_wav(chunk_path)
                            else:
                                try:
                                    text = local_transcribe(chunk_path)
                                except Exception as local_exc:
                                    if mode == "sensevoice":
                                        raise
                                    local_disabled = True
                                    live_queue.put((
                                        "live_status",
                                        f"SenseVoice不可用，已自动切换StepAudio在线识别：{local_exc}"))
                                    text = cloud_asr.transcribe_wav(chunk_path)
                            if not chunk.is_final:
                                continued_chunks += 1
                            finalize = (chunk.is_final or
                                        continued_chunks >= max_continued_chunks)
                            recent_text = str(text or "").strip()
                            terminology = self.interview_terminology.correct(recent_text)
                            corrected_text = terminology["corrected"].strip()
                            text = corrected_text
                            for key in ("matched_terms", "acronyms", "unknown_acronyms"):
                                terminology_risk[key] = list(dict.fromkeys(
                                    terminology_risk[key] + terminology["risk"].get(key, [])))
                            terminology_risk["correction_applied"] = (
                                terminology_risk["correction_applied"] or
                                terminology["risk"].get("correction_applied", False))
                            merged_text = corrected_text
                            if recognized_parts and merged_text:
                                merged_text = question_detector._remove_overlap(
                                    recognized_parts[-1], merged_text)
                            if merged_text:
                                recognized_parts.append(merged_text)
                            combined_text = "".join(recognized_parts).strip()
                            live_queue.put(("live_transcript", {
                                "recent": recent_text,
                                "corrected": corrected_text,
                                "combined": combined_text,
                                "final": finalize,
                            }))
                            candidate = question_detector.add_utterance(
                                text, finalize=finalize)
                            if finalize:
                                continued_chunks = 0
                                recognized_parts.clear()
                            if candidate:
                                candidate["terminology_risk"] = dict(terminology_risk)
                                candidate["asr_seconds"] = time.perf_counter() - asr_started
                                live_queue.put(("question", candidate))
                            elif not text:
                                live_queue.put((
                                    "live_status", "检测到会议声音，但本段没有识别出文字，继续监听。"))
                            elif finalize:
                                live_queue.put((
                                    "live_status", "已识别一段会议声音，未检测到明确提问，继续监听。"))
                            else:
                                live_queue.put((
                                    "live_status", f"已识别长问题片段 {continued_chunks}，等待问题结束……"))
                            if finalize:
                                terminology_risk = {
                                    "correction_applied": False, "matched_terms": [],
                                    "acronyms": [], "unknown_acronyms": []}
                        finally:
                            try:
                                chunk_path.unlink()
                            except OSError:
                                pass
            except Exception as exc:
                if not live_stop_event.is_set():
                    live_queue.put(("live_error", str(exc)))
            finally:
                if local_session is not None:
                    local_session.close()

        def start_recording():
            microphone = device_maps["microphones"].get(microphone_var.get())
            meeting_output = device_maps["outputs"].get(output_device_var.get())
            if not microphone or not meeting_output:
                messagebox.showinfo("录音转写", "请选择麦克风和会议声音设备。", parent=dialog)
                return
            try:
                recorder = DualTrackRecorder(self.store.path.parent / "recordings")
                recorder.start(microphone, meeting_output)
            except (VoiceServiceError, OSError) as exc:
                messagebox.showerror("录音启动失败", str(exc), parent=dialog)
                return
            self.voice_recorder = recorder
            live_stop_event.clear()
            state["live_offset"] = 0
            set_voice_busy(True)
            pause_button.state(["!disabled"])
            stop_button.state(["!disabled"])
            record_state_label.configure(fg="#ff5b5b")
            record_state_var.set("● 正在录音  00:00:00")
            status_var.set("正在分别录制麦克风与会议声音。停止后执行完整转写。")
            if recording_mode and question_enabled_var.get():
                clear_question("正在启动提问助手……")
                recognized_text_var.set("最近识别文字：正在等待会议声音……")
                self.interview_terminology.refresh()
                threading.Thread(
                    target=run_live_question_detection, args=(recorder,),
                    name="live-interview-question-detection", daemon=True).start()
                dialog.after(150, poll_live_results)
            update_record_timer()

        def toggle_pause():
            recorder = self.voice_recorder
            if not recorder or not recorder.is_recording:
                return
            if recorder.is_paused:
                recorder.resume()
                pause_button.configure(text="暂停")
            else:
                recorder.pause()
                pause_button.configure(text="继续")

        def transcribe_files(tracks, warning=""):
            state["result"] = ""
            state["mode"] = "transcript"
            state["voice_warning"] = warning
            set_output("")
            set_voice_busy(True)
            status_var.set("正在加载本地 SenseVoice 并转写，首次加载可能需要一些时间……")

            def worker():
                try:
                    transcriber = SenseVoiceTranscriber()
                    segments = transcriber.transcribe_tracks([
                        (Path(path), label, label != "我") for path, label in tracks
                    ])
                    transcript = format_transcript(segments)
                    if not transcript:
                        raise VoiceServiceError("未识别到有效语音，请检查录音设备和音量。")
                    voice_queue.put(("transcript", transcript))
                except Exception as exc:
                    voice_queue.put(("error", str(exc)))

            threading.Thread(target=worker, name="local-sensevoice-transcribe", daemon=True).start()
            dialog.after(100, poll_voice_results)

        def stop_and_transcribe():
            recorder = self.voice_recorder
            if not recorder:
                return
            pause_button.state(["disabled"])
            stop_button.state(["disabled"])
            live_stop_event.set()
            record_state_var.set("● 正在停止录音……")

            def worker():
                try:
                    result = recorder.stop()
                    voice_queue.put(("recorded", result))
                except Exception as exc:
                    voice_queue.put(("error", str(exc)))

            threading.Thread(target=worker, name="stop-interview-recording", daemon=True).start()
            dialog.after(100, poll_voice_results)

        def import_audio():
            path = filedialog.askopenfilename(
                parent=dialog, title="选择录音文件",
                filetypes=(("音频文件", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"), ("所有文件", "*.*")))
            if path:
                transcribe_files([(Path(path), "录音")])

        def poll_voice_results():
            if not dialog.winfo_exists():
                return
            try:
                event, value = voice_queue.get_nowait()
            except queue.Empty:
                if state["voice_busy"] or self.voice_recorder:
                    dialog.after(100, poll_voice_results)
                return
            if event == "recorded":
                self.voice_recorder = None
                record_state_var.set(f"● 录音完成  {int(value.duration_seconds)} 秒")
                record_state_label.configure(fg=c["muted"])
                recording_tracks.clear()
                if value.microphone_path:
                    recording_tracks["麦克风"] = str(value.microphone_path)
                if value.system_path:
                    recording_tracks["会议方"] = str(value.system_path)
                tracks = []
                if value.microphone_path:
                    tracks.append((value.microphone_path, "我"))
                if value.system_path:
                    tracks.append((value.system_path, "会议方"))
                transcribe_files(tracks, "；".join(value.warnings))
            elif event == "transcript":
                state["result"] = value
                state["mode"] = "transcript"
                set_output(value)
                set_voice_busy(False)
                for button in result_buttons:
                    button.state(["!disabled"])
                for button in analysis_entry_buttons:
                    button.state(["!disabled"])
                save_transcript_button.state(["!disabled"])
                save_audio_button.state(
                    ["!disabled"] if recording_tracks else ["disabled"])
                prefix = (state["voice_warning"] + "；") if state["voice_warning"] else ""
                next_action = "AI 摘要生成" if recording_mode or is_summary else "AI 分析"
                status_var.set(prefix + f"本地转写完成，可追加到当前笔记后继续进行 {next_action}。")
            else:
                self.voice_recorder = None
                set_voice_busy(False)
                pause_button.state(["disabled"])
                stop_button.state(["disabled"])
                record_state_var.set("● 未录音")
                record_state_label.configure(fg=c["muted"])
                status_var.set("录音/转写失败：" + value)

        refresh_button = ttk.Button(record_controls, text="刷新设备", command=refresh_devices)
        refresh_button.pack(side="left", padx=(0, 4))
        start_record_button = ttk.Button(record_controls, text="开始录音", command=start_recording)
        start_record_button.pack(side="left", padx=4)
        pause_button = ttk.Button(record_controls, text="暂停", command=toggle_pause)
        pause_button.pack(side="left", padx=4)
        stop_button = ttk.Button(record_controls, text="停止并转写", command=stop_and_transcribe)
        stop_button.pack(side="left", padx=4)
        import_button = ttk.Button(record_controls, text="导入音频", command=import_audio)
        import_button.pack(side="left", padx=4)
        pause_button.state(["disabled"])
        stop_button.state(["disabled"])

        def copy_result():
            if state["result"]:
                self.root.clipboard_clear()
                self.root.clipboard_append(state["result"])
                status_var.set("结果已复制。")

        def result_header():
            if state["mode"] == "transcript":
                transcript_title = ("录音转写" if recording_mode else
                                    "会议录音转写" if is_meeting else "面试录音转写")
                return (f"## {transcript_title}\n\n{state['result']}\n\n"
                        "转写模型：SenseVoice-Small（本地）\n"
                        "语音分段：FSMN-VAD；多人标签：CAM++\n"
                        f"转写时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            if state["mode"] == "question_answer":
                question = state.get("answered_question") or "面试提问"
                return (f"## 面试问题回答建议\n\n问题：{question}\n\n{state['result']}\n\n"
                        f"模型：{self.store.settings.get('ai_model', '')}\n"
                        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
            label = tasks.get(state["task"], (dialog_name, ""))[0]
            return (f"## {label}\n\n{state['result']}\n\n"
                    f"模型：{self.store.settings.get('ai_model', '')}\n"
                    f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        def append_result():
            self.flush_save()
            target_id = self.current.get("id") if self.current else source_id
            note = next((item for item in self.store.notes if item.get("id") == target_id), None)
            if not note or not state["result"]:
                status_var.set("请先在主界面选择需要追加的便签或笔记。")
                return
            note["content"] = note.get("content", "").rstrip() + "\n\n" + result_header()
            note["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.store.save()
            if self.current and self.current.get("id") == target_id:
                self.select_note(target_id, flush_current=False)
            status_var.set(f"结果已追加到：{note.get('title', '无标题')}。")

        def create_result_note():
            if not state["result"]:
                return
            is_transcript = state["mode"] == "transcript"
            transcript_label = ("录音转写" if recording_mode else
                                "会议录音转写" if is_meeting else "面试录音转写")
            label = (transcript_label if is_transcript else
                     tasks.get(state["task"], (dialog_name, ""))[0])
            transcript_tag = ("录音" if recording_mode else
                              "会议录音" if is_meeting else "面试录音")
            analysis_tag = "会议纪要" if is_meeting else "AI复盘"
            tags = list(dict.fromkeys(list(source_note.get("tags", [])) +
                                      ([transcript_tag] if is_transcript else [analysis_tag])))
            if is_meeting and not is_transcript:
                note_title = (f"会议纪要｜{datetime.now().strftime('%Y-%m-%d')}｜"
                              f"{source_note.get('title', '未命名会议')}")
            else:
                note_title = f"{source_note.get('title', transcript_label)}｜{label}"
            note = self.store.new_note(
                note_title, result_header(),
                kind="journal", category=source_note.get("category", ""), tags=tags)
            note["source_note_id"] = source_id
            if not is_transcript:
                note["ai_model"] = self.store.settings.get("ai_model", "")
            self.store.save()
            self.refresh_list()
            self.select_note(note["id"], flush_current=False)
            status_var.set("已生成独立会议纪要。" if is_meeting else "已生成独立复盘笔记。")

        recording_tracks = {}  # 存储最近一次录音的音频文件路径
        result_buttons = []
        create_button_text = ("生成独立转写笔记" if recording_mode else
                              "生成独立会议纪要" if is_meeting else "生成独立复盘笔记")
        for text_value, command in (("复制", copy_result), ("追加到当前笔记", append_result),
                                    (create_button_text, create_result_note)):
            button = ttk.Button(action_frame, text=text_value, command=command)
            button.pack(side="left", padx=(0, 5))
            result_buttons.append(button)

        def save_audio():
            """保存录音音频文件到用户选择的目录"""
            if not recording_tracks:
                messagebox.showinfo("保存音频", "没有可保存的录音文件。", parent=dialog)
                return
            dest_dir = filedialog.askdirectory(
                parent=dialog, title="选择保存目录")
            if not dest_dir:
                return
            saved = []
            for label, src in recording_tracks.items():
                if src and Path(src).exists():
                    dst = Path(dest_dir) / f"{label}_{Path(src).name}"
                    try:
                        shutil.copy2(src, dst)
                        saved.append(f"{label}: {dst.name}")
                    except Exception as exc:
                        messagebox.showerror("保存失败", f"{label}: {exc}", parent=dialog)
            if saved:
                status_var.set("音频已保存：" + "、".join(saved))

        def save_transcript():
            """保存转写文字到文本文件"""
            if not state["result"]:
                messagebox.showinfo("保存转写", "没有可保存的转写内容。", parent=dialog)
                return
            path = filedialog.asksaveasfilename(
                parent=dialog, title="保存转写内容",
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                initialfile=f"转写_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            if not path:
                return
            try:
                Path(path).write_text(state["result"], encoding="utf-8")
                status_var.set(f"转写已保存：{path}")
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)

        save_audio_button = ttk.Button(action_frame, text="保存音频", command=save_audio)
        save_audio_button.pack(side="left", padx=(0, 5))
        save_audio_button.state(["disabled"])

        save_transcript_button = ttk.Button(action_frame, text="保存转写", command=save_transcript)
        save_transcript_button.pack(side="left", padx=(0, 5))
        save_transcript_button.state(["disabled"])

        def clear_recording_content():
            """清空本次录音会话的内存内容，保留已写入磁盘的原始音频。"""
            recorder = self.voice_recorder
            if state["busy"] or state["voice_busy"] or (recorder and recorder.is_recording):
                messagebox.showinfo(
                    "清空内容", "请先等待当前录音、转写或摘要生成结束，再清空内容。", parent=dialog)
                return
            state.update({
                "result": "", "task": "", "mode": "", "voice_warning": "",
                "live_offset": 0, "answered_question": "", "answer_stream": "",
                "answer_timings": {}, "last_sources": [],
            })
            # 清空会话引用而不删除实际文件；用户如需保留，应在清空前点击“保存音频”。
            recording_tracks.clear()
            set_output("")
            clear_question("等待录制新的会议声音……")
            recognized_text_var.set("最近识别文字：等待会议声音……")
            question_status_var.set("")
            record_state_var.set("● 未录音")
            record_state_label.configure(fg=c["muted"])
            pause_button.configure(text="暂停")
            pause_button.state(["disabled"])
            stop_button.state(["disabled"])
            for button in analysis_entry_buttons + result_buttons:
                button.state(["disabled"])
            save_audio_button.state(["disabled"])
            save_transcript_button.state(["disabled"])
            set_voice_busy(False)
            status_var.set("当前内容已清空，可重新开始录音或导入音频。")

        clear_button = ttk.Button(action_frame, text="清空内容", command=clear_recording_content)
        clear_button.pack(side="right", padx=(5, 0))

        def close_dialog():
            if self.ai_cancel_event:
                self.ai_cancel_event.set()
            live_stop_event.set()
            recorder = self.voice_recorder
            if recorder and recorder.is_recording:
                try:
                    recorder.stop()
                except Exception:
                    pass
                self.voice_recorder = None
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            if recording_mode and self.voice_edge_controller:
                self.voice_edge_controller.stop(reveal=True)
                dialog.update_idletasks()
                self.store.settings["voice_dialog_bounds"] = list(window_bounds(dialog))
                if self.voice_dpi_scaler and self.voice_dpi_scaler.current_dpi:
                    self.store.settings["voice_dialog_dpi"] = self.voice_dpi_scaler.current_dpi
                self.store.settings["voice_dialog_layout_version"] = 2
                self.store.save()
                self.voice_edge_controller = None
                self.voice_dpi_scaler = None
            self.ai_dialog = None
            dialog.destroy()

        ttk.Button(action_frame, text="关闭", command=close_dialog).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        set_busy(False)
        if show_recording:
            refresh_devices()
        if not recording_mode:
            dialog.grab_set()
        if recording_mode:
            def initialize_voice_display():
                if not dialog.winfo_exists():
                    return
                bounds = self.store.settings.get("voice_dialog_bounds")
                displays = enumerate_displays()
                if isinstance(bounds, list) and len(bounds) == 4:
                    x, y = ensure_visible_position(tuple(int(value) for value in bounds), displays)
                    set_window_position(dialog, x, y)
                display = display_for_bounds(window_bounds(dialog), displays)

                def on_voice_display_enter(target_display):
                    if not self.voice_dpi_scaler:
                        return
                    self.voice_dpi_scaler.apply(target_display.dpi)
                    scale = target_display.dpi / 96
                    if self.voice_edge_controller:
                        self.voice_edge_controller.gap = round(self.EDGE_GAP * scale)
                        self.voice_edge_controller.visible_size = max(
                            self.HIDDEN_SIZE, round(self.HIDDEN_SIZE * scale))

                self.voice_dpi_scaler = WindowDpiScaler(
                    dialog, user_factor=UI_FONT_SCALINGS.get(self.ui_font_size, 1.0),
                    base_min_size=(800, 720))
                if display:
                    # 初次打开时先保留当前安全几何尺寸，仅按当前显示器放大字体和
                    # 间距；跨屏移动时再由 on_voice_display_enter 做比例换算。
                    self.voice_dpi_scaler.apply(display.dpi, resize=False)
                self.voice_edge_controller = EdgeHideController(
                    dialog, enabled=lambda: self.edge_var.get(),
                    gap=self.EDGE_GAP, visible_size=self.HIDDEN_SIZE,
                    on_display_enter=on_voice_display_enter)
                if display:
                    scale = display.dpi / 96
                    self.voice_edge_controller.gap = round(self.EDGE_GAP * scale)
                    self.voice_edge_controller.visible_size = max(
                        self.HIDDEN_SIZE, round(self.HIDDEN_SIZE * scale))
                self.voice_edge_controller.start()

            dialog.after(80, initialize_voice_display)


    def toggle_settings(self):
        self.switch_section("settings")

    def sync_ai_interview_entry(self):
        self.ai_interview_frame.pack_forget()
        self.news_tabs_frame.pack_forget()

    def clear_toolbar_layout(self):
        buttons = (self.new_button, self.pending_button, self.task_button, self.calendar_button,
                   self.news_refresh_button, self.news_home_button,
                   self.news_source_button, self.record_button, self.settings_button)
        for button in buttons:
            button.pack_forget()
            button.grid_forget()

    def update_toolbar_labels(self, width=None):
        if self.settings_visible:
            return
        compact = (width if width is not None else self.root.winfo_width()) < 620
        full_new = {"reminder": "＋ 新建提醒", "sticky": "＋ 新建便签",
                    "journal": "＋ 新建笔记"}
        if self.current_section in full_new:
            self.new_button_text.set("＋ 新建" if compact else full_new[self.current_section])
            if hasattr(self.new_button, "set_text"):
                self.new_button.set_text(self.new_button_text.get())
        self.calendar_button.configure(text="📅 日历" if compact else "📅 日历视图")
        if self.news_mode == "flash":
            self.news_home_button.configure(text="快讯" if compact else "打开快讯页")
            self.news_source_button.configure(text="来源" if compact else "打开来源")
        else:
            self.news_home_button.configure(text="AI HOT" if compact else "打开 AI HOT")
            self.news_source_button.configure(text="原文" if compact else "打开原文")
        self.record_button.configure(text="录音" if compact else "🎙 录音")
        self.pending_button.configure(text="待办")
        self.task_button.configure(text="已完成")

    def configure_toolbar_for_section(self):
        self.clear_toolbar_layout()
        if self.settings_visible:
            return
        self.update_toolbar_labels()
        if self.current_section == "news":
            buttons = (self.news_refresh_button, self.news_home_button,
                       self.news_source_button, self.settings_button)
        elif self.current_section == "reminder":
            buttons = (self.new_button, self.calendar_button, self.settings_button)
        elif self.current_section == "journal":
            buttons = (self.new_button, self.pending_button, self.task_button,
                       self.record_button)
        else:
            buttons = (self.new_button, self.pending_button, self.task_button)
        for column in range(6):
            self.toolbar.grid_columnconfigure(
                column, weight=1 if column < len(buttons) else 0,
                uniform="section-actions" if column < len(buttons) else "")
        for column, button in enumerate(buttons):
            button.grid(row=0, column=column, sticky="ew", padx=2)
        if self.current_section in ("sticky", "journal"):
            self.pending_button.state(["selected"] if self.task_view == "pending" else ["!selected"])
            self.task_button.state(["selected"] if self.task_view == "completed" else ["!selected"])

    def sync_check_labels(self):
        self.top_label_var.set(("✔" if self.top_var.get() else "□") + " 置顶")
        self.edge_label_var.set(("✔" if self.edge_var.get() else "□") + " 贴边隐藏")
        if hasattr(self, "autostart_check"):
            self.autostart_check.configure(
                text=("✔" if self.autostart_var.get() else "□") + " 开机启动")

    def toggle_autostart(self):
        wanted = self.autostart_var.get()
        if not set_autostart(wanted, Path(__file__)):
            self.autostart_var.set(not wanted)
            messagebox.showerror("开机启动", "无法修改Windows开机启动设置。", parent=self.root)
        self.sync_check_labels()

    def poll_tray_events(self):
        if self.exiting:
            return
        while not self.tray.events.empty():
            action = self.tray.events.get_nowait()
            if action == "show":
                self.show_window()
            elif action == "new_reminder":
                self.show_window(); self.switch_section("reminder"); self.add_note()
            elif action == "new_sticky":
                self.show_window(); self.switch_section("sticky"); self.add_note()
            elif action == "new_journal":
                self.show_window(); self.switch_section("journal"); self.add_note()
            elif action == "toggle_pause":
                paused = not self.store.settings.get("reminders_paused", False)
                self.store.settings["reminders_paused"] = paused
                self.store.save()
                self.status_var.set("提醒已暂停" if paused else "提醒已恢复")
            elif action == "restart":
                self.restart_app()
                return
            elif action == "exit":
                self.exit_app()
        self.root.after(250, self.poll_tray_events)

    def poll_instance_requests(self):
        if self.exiting:
            return
        if self.instance_guard and self.instance_guard.consume_show_request():
            self.show_window()
        self.root.after(300, self.poll_instance_requests)

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.sync_quick_visibility()

    def start_window_drag(self, event):
        self.drag_offset = (event.x_root - self.root.winfo_x(),
                            event.y_root - self.root.winfo_y())
        self.reveal_from_edge()
        # 把 motion/release 绑到 root，鼠标移出标题栏也不会中断拖动。
        self.root.bind("<B1-Motion>", self.drag_window)
        self.root.bind("<ButtonRelease-1>", self.end_window_drag)

    def end_window_drag(self, _event=None):
        try:
            self.root.unbind("<B1-Motion>")
            self.root.unbind("<ButtonRelease-1>")
        except tk.TclError:
            pass

    def drag_window(self, event):
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        set_window_position(self.root, x, y)

    def minimize_window(self):
        """隐藏主窗口，仅保留 Windows 通知区域中的托盘图标。"""
        self.reveal_from_edge()
        self.flush_save()
        self.stop_all_quick_pulses()
        self.quick_rail.withdraw()
        self.root.withdraw()
        self.status_var.set("轻笺正在系统托盘运行")

    def on_window_map(self, _event=None):
        if self.minimized:
            self.minimized = False
            self.root.after(10, lambda: self.root.overrideredirect(True))
        self.root.after(20, self.sync_quick_visibility)

    def add_note(self):
        if self.current_section in ("news",):
            return
        self.flush_save()
        if self.current_section == "reminder":
            remind_at = self.pick_datetime()
            if not remind_at:
                return
            result = self.open_reminder_dialog(remind_at)
            if result:
                self.store.new_independent_reminder(result["title"], result["content"],
                                                    result["remind_at"], result.get("repeat", "none"),
                                                    result.get("rule"))
                self.refresh_list()
            return
        result = self.open_note_dialog(kind=self.current_section)
        if not result:
            return
        note = self.store.new_note(result["title"], result["content"], result["formats"],
                                   kind=self.current_section, category=result.get("category", ""),
                                   tags=result.get("tags", []))
        self.store.remember_category(result.get("category", ""))
        if self.current_section != "journal":
            self.store.set_source_reminder(note, result["remind_at"], result["repeat"], result.get("rule"))
        self.refresh_list()
        # 对话框已经把完整结果写入存储；此处不能再保存仍显示旧值的主编辑器。
        self.select_note(note["id"], flush_current=False)
        if result.get("open_ai"):
            self.root.after_idle(lambda value=result["open_ai"]:
                                 self.open_ai_interview(value, show_recording=False))

    def copy_note(self):
        """复制当前选中的便签/笔记，创建副本并选中编辑。"""
        if not self.current:
            return
        if self.current_section in ("news", "reminder"):
            return
        self.flush_save()
        source = self.current
        title = source.get("title", "无标题")
        # 去掉已有"副本"后缀再追加，避免多次复制后变成"副本 (副本)"
        base_title = title.replace(" (副本)", "").replace("副本", "").strip()
        if base_title:
            new_title = base_title + " (副本)"
        else:
            new_title = "副本"
        note = self.store.new_note(
            title=new_title,
            content=source.get("content", ""),
            formats=[dict(f) for f in (source.get("formats") or [])],
            kind=source.get("kind", "sticky"),
            category=source.get("category", ""),
            tags=list(source.get("tags") or []),
        )
        if source.get("kind") != "journal":
            source_reminder = source.get("reminder", "")
            if source_reminder:
                self.store.set_source_reminder(note, source_reminder,
                                               source.get("repeat", "none"))
        self.refresh_list()
        self.select_note(note["id"], flush_current=False)

    def copy_note_by_source(self, source):
        """右键菜单：根据列表数据源复制便签/笔记。"""
        source_type = source.get("source_type")
        source_id = source.get("source_id")
        if source_type not in ("sticky", "journal"):
            return
        # 列表来源只保存 source_id；先恢复真实记录，才能完整继承正文、格式、标签等数据。
        note = next((item for item in self.store.notes
                     if item.get("id") == source_id), None)
        if not note:
            return
        self.current_section = source_type
        self.current = note
        self.copy_note()

    def delete_note_by_source(self, source):
        """右键菜单：根据列表数据源删除便签/笔记。"""
        source_type = source.get("source_type")
        source_id = source.get("source_id")
        if source_type == "reminder":
            reminder = next((item for item in self.store.reminders
                             if item.get("id") == source_id), None)
            if not reminder:
                return
            self.current_section = "reminder"
            self.current_reminder = reminder
        else:
            # 右键列表项只存 source_id；删除前恢复为真实记录，避免误用不存在的 id 字段。
            note = next((item for item in self.store.notes
                         if item.get("id") == source_id), None)
            if not note:
                return
            self.current_section = source_type or "sticky"
            self.current = note
        self.delete_note(parent=self.listbox)

    def pick_datetime(self, value: str = "", parent=None):
        try:
            initial = datetime.strptime(value, "%Y-%m-%d %H:%M") if value else None
        except ValueError:
            initial = None
        return CalendarPicker(parent or self.root, self.colors, initial,
                              self.store.reminders).show()

    def open_calendar_view(self):
        selected = self.pick_datetime()
        if not selected:
            return
        day = selected[:10]
        matches = [r for r in self.store.reminders if r.get("remind_at", "").startswith(day)]
        self.switch_section("reminder")
        if matches:
            self.select_reminder(matches[0]["id"])
            self.status_var.set(f"{day} 共 {len(matches)} 条提醒")
        else:
            self.status_var.set(f"{day} 暂无提醒")

    def active_news_cache(self):
        return self.flash_cache if self.news_mode == "flash" else self.news_cache

    @staticmethod
    def flash_cache_complete(payload):
        items = (payload or {}).get("items") or []
        return bool(items) and all(isinstance(item, dict) and
            str(item.get("features") or "").strip() and
            str(item.get("use_cases") or "").strip()
            for item in items)

    def update_news_tabs(self):
        if not hasattr(self, "news_daily_tab"):
            return
        self.news_daily_tab.state(
            ["selected"] if self.news_mode == "daily" else ["!selected"])
        self.news_flash_tab.state(
            ["selected"] if self.news_mode == "flash" else ["!selected"])

    def switch_news_mode(self, mode):
        if mode not in ("daily", "flash"):
            return
        self.news_mode = mode
        self.current_news = None
        self.news_items = []
        self.listbox.delete(0, "end")
        self.update_news_tabs()
        self.enforce_news_clean_layout()
        self.update_toolbar_labels()
        self.show_news_loading("正在读取免费模型快讯……" if mode == "flash"
                               else "正在获取 AI HOT 今日日报……")
        self.load_news(False)

    def load_news(self, force=False):
        mode = self.news_mode
        is_flash = mode == "flash"
        target_date = effective_flash_date() if is_flash else effective_daily_date()
        memory_cache = self.flash_cache if is_flash else self.news_cache
        cache_path = self.flash_cache_path if is_flash else self.news_cache_path
        memory_complete = not is_flash or self.flash_cache_complete(memory_cache)
        if not force and memory_cache and memory_complete and memory_cache.get("date") == target_date:
            self.apply_news_payload(memory_cache)
            return
        if is_flash and memory_cache and not memory_complete:
            self.flash_cache = None
        disk_cache = load_daily_cache(cache_path)
        if disk_cache:
            disk_complete = not is_flash or self.flash_cache_complete(disk_cache)
            if is_flash and disk_complete:
                self.flash_cache = disk_cache
            elif not is_flash:
                self.news_cache = disk_cache
            if not force and disk_complete and disk_cache.get("date") == target_date:
                self.apply_news_payload(disk_cache)
                return
        if mode in self.news_loading_modes:
            return
        self.news_loading_modes.add(mode)
        self.news_loading = True
        if self.current_section == "news":
            self.show_news_loading("正在获取免费模型快讯……" if is_flash
                                   else "正在获取 AI HOT 今日日报……")

        def worker():
            try:
                payload, error = (fetch_free_model_digest() if is_flash else fetch_daily()), None
                if payload.get("date") != target_date:
                    label = "免费模型快讯" if is_flash else "AI HOT 日报"
                    payload, error = None, f"{label}尚未发布 {target_date} 内容"
            except NewsServiceError as exc:
                payload, error = None, str(exc)
            except Exception:
                payload, error = None, "获取日报时发生未知错误"
            self.news_results.put((mode, payload, error))

        threading.Thread(target=worker, name="aihot-daily", daemon=True).start()
        if not self.news_poll_job:
            self.news_poll_job = self.root.after(80, self.poll_news_results)

    def poll_news_results(self):
        self.news_poll_job = None
        try:
            mode, payload, error = self.news_results.get_nowait()
        except queue.Empty:
            if self.news_loading and not self.exiting:
                self.news_poll_job = self.root.after(80, self.poll_news_results)
            return
        self.finish_news_load(mode, payload, error)
        if self.news_loading_modes and not self.news_poll_job:
            self.news_poll_job = self.root.after(80, self.poll_news_results)

    def finish_news_load(self, mode, payload, error):
        self.news_loading_modes.discard(mode)
        self.news_loading = bool(self.news_loading_modes)
        is_flash = mode == "flash"
        cache_path = self.flash_cache_path if is_flash else self.news_cache_path
        if payload:
            if is_flash:
                self.flash_cache = payload
            else:
                self.news_cache = payload
            try:
                save_daily_cache(cache_path, payload)
            except OSError:
                pass
            if self.current_section == "news" and self.news_mode == mode:
                self.apply_news_payload(payload)
            return
        cache = self.flash_cache if is_flash else self.news_cache
        if self.current_section == "news" and self.news_mode == mode:
            if cache:
                self.apply_news_payload(cache)
                cached_date = cache.get("date", "未知日期")
                self.status_var.set(f"联网失败，正在展示 {cached_date} 的本地缓存")
            else:
                fallback_message = ("暂时无法获取免费模型快讯" if is_flash
                                    else "暂时无法获取 AI HOT 日报")
                self.show_news_loading(error or fallback_message)

    def apply_news_payload(self, payload):
        self.enforce_news_clean_layout()
        selected_permalink = ((self.current_news or {}).get("permalink") or
                              self.section_selection_ids.get("news"))
        self.news_items = list(payload.get("items") or [])
        self.refresh_list()
        if self.news_items:
            target = next((index for index, item in enumerate(self.news_items)
                           if item.get("permalink") == selected_permalink), 0)
            self.select_news(target)
            self.listbox.focus_set()
        else:
            self.show_news_loading("今日暂无新闻")

    def show_news_loading(self, message):
        self.enforce_news_clean_layout()
        self.current_news = None
        self.editor.configure(state="normal")
        self.news_title_var.set("免费模型快讯" if self.news_mode == "flash" else "AI HOT 日报")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", message)
        self.editor.edit_modified(False)
        self.editor.configure(state="disabled")
        self.news_source_button.state(["disabled"])

    def select_news(self, index):
        if not (0 <= index < len(self.news_items)):
            return
        item = self.news_items[index]
        self.section_selection_ids["news"] = item.get("permalink")
        self.current_news = item
        self.current = None
        self.current_reminder = None
        report_date = (self.active_news_cache() or {}).get("date", "")
        if self.news_mode == "flash":
            detail = (f"{item.get('category', '其他模型')} · {report_date}\n"
                      f"免费方式：{item.get('free_type') or '待核验'}\n"
                      f"使用方式：{item.get('access_type') or '见来源页'}\n"
                      f"模型：{item.get('model_id') or item.get('title', '')}\n"
                      f"截止：{item.get('expires_at') or '未公布'}\n"
                      f"状态：{item.get('status') or '待核验'} · 可信度：{item.get('confidence') or '未知'}\n\n"
                      f"特点：{item.get('features', '')}\n\n"
                      f"适用场景：{item.get('use_cases', '')}\n\n"
                      f"{item.get('summary', '')}\n\n来源：{item.get('source_name', '公开来源')}\n"
                      f"链接：{item.get('source_url', '')}")
        else:
            detail = (f"{item.get('category', '其他')} · {report_date}\n"
                      f"来源：{item.get('source_name', 'AI HOT')}\n\n"
                      f"{item.get('summary', '')}\n\n"
                      f"AI HOT：{item.get('permalink', '')}\n"
                      f"原文：{item.get('source_url', '')}")
        self.editor.configure(state="normal")
        self.news_title_var.set(item.get("title", "未命名新闻"))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", detail)
        self.editor.edit_modified(False)
        self.editor.configure(state="disabled")
        self.news_source_button.state(["!disabled"] if item.get("source_url") else ["disabled"])
        self.refresh_list()
        self.enforce_news_clean_layout()

    def open_news_home(self):
        fallback = ("https://github.com/zhulvglos/QINGJIAN/releases/tag/free-model-daily"
                    if self.news_mode == "flash" else "https://aihot.virxact.com/daily")
        webbrowser.open((self.active_news_cache() or {}).get("canonical") or fallback)

    def open_news_source(self):
        if self.current_news and self.current_news.get("source_url"):
            webbrowser.open(self.current_news["source_url"])

    def switch_section(self, section: str, select_default: bool = True):
        if section not in ("reminder", "sticky", "journal", "news", "settings"):
            return
        self.flush_save()
        self.current_section = section
        self.current = None
        self.current_reminder = None
        self.current_news = None
        self.ai_interview_frame.pack_forget()
        self.show_news_title(section == "news")
        if section == "settings":
            self.settings_visible = True
            self.section_nav.set_active(section)
            self.clear_toolbar_layout()
            self.toolbar.pack_forget()
            self.body.pack_forget()
            self.news_tabs_frame.pack_forget()
            self.settings_frame.pack(fill="both", expand=True, after=self.section_nav)
            return
        self.settings_visible = False
        self.settings_frame.pack_forget()
        self.toolbar.pack(fill="x", after=self.section_nav)
        labels = {"reminder": "＋ 新建提醒", "sticky": "＋ 新建便签",
                  "journal": "＋ 新建笔记", "news": "新闻"}
        self.new_button_text.set(labels[section])
        if hasattr(self.new_button, "set_text"):
            self.new_button.set_text(self.new_button_text.get())
        self.section_nav.set_active(section)

        # 先清空各板块的附属控件，再按目标板块重建，确保重复调用也安全。
        self.reminder_actions.pack_forget()
        self.note_filter_frame.pack_forget()
        self.calendar_button.pack_forget()
        self.configure_toolbar_for_section()
        self.body.pack_forget()
        self.body.pack(fill="both", expand=True, padx=8, pady=8, after=self.toolbar)
        if section == "reminder":
            self.reminder_actions.pack(fill="x")
        elif section == "journal":
            self.category_filter.configure(values=["全部分类", "未分类"] + self.store.categories)
            self.note_filter_frame.pack(fill="x", before=self.listbox)
            self.sync_ai_interview_entry()
        elif section == "sticky":
            pass
        self.apply_theme(save=False)
        self.refresh_list()
        if section == "news":
            self.news_tabs_frame.pack(fill="x", after=self.toolbar)
            self.body.pack_forget()
            self.body.pack(fill="both", expand=True, padx=8, pady=8,
                           after=self.news_tabs_frame)
            self.update_news_tabs()
            self.enforce_news_clean_layout()
            self.show_news_loading("正在读取免费模型快讯……" if self.news_mode == "flash"
                                   else "正在获取 AI HOT 今日日报……")
            self.load_news(False)
            return
        if not select_default:
            self.clear_editor()
            return
        if section == "reminder" and self.store.reminders:
            items = sorted(self.store.reminders, key=lambda item: item.get("remind_at", ""))
            selected_id = self.section_selection_ids.get("reminder")
            target = next((item for item in items if item.get("id") == selected_id), items[0])
            self.select_reminder(target["id"])
        else:
            notes = self.visible_notes()
            if notes:
                selected_id = self.section_selection_ids.get(section)
                target = next((item for item in notes if item.get("id") == selected_id), notes[0])
                self.select_note(target["id"])
            else:
                self.clear_editor()

    def clear_editor(self):
        self.current = None
        self.current_reminder = None
        self.current_news = None
        self.title_entry.configure(state="normal")
        self.editor.configure(state="normal")
        self.title_var.set("")
        self.editor.delete("1.0", "end")
        self.editor.tag_remove("bold", "1.0", "end")
        self.editor.edit_modified(False)
        self.reminder_var.set("")
        self.learning_stats_var.set("")

    def mark_learning(self):
        if self.current and self.current.get("kind") == "journal":
            self.store.log_learning(self.current["id"])
            self.update_learning_stats()

    def unmark_learning(self):
        if self.current and self.current.get("kind") == "journal":
            self.store.unlog_learning(self.current["id"])
            self.update_learning_stats()

    def update_learning_stats(self):
        if not self.current or self.current.get("kind") != "journal":
            self.learning_stats_var.set("")
            return
        stats = self.store.learning_stats(self.current)
        self.learning_stats_var.set(
            f"连续{stats['streak']}天 · 本周{stats['week']}次 · 累计{stats['total']}次")

    def open_learning_calendar(self):
        if not self.current or self.current.get("kind") != "journal":
            return
        records = [{"title": "已积累", "remind_at": day + " 12:00"}
                   for day in self.current.get("learning_log", [])]
        CalendarPicker(self.root, self.colors, reminders=records,
                       title="学习积累日历").show()

    def edit_selected_note(self, _event=None):
        if self.current_section == "reminder":
            self.open_current_source()
            return
        selection = self.listbox.curselection()
        notes = self.visible_notes()
        if not selection or selection[0] >= len(notes):
            return
        self.flush_save()
        note = notes[selection[0]]
        result = self.open_note_dialog(note, self.current_section)
        if not result:
            return
        note["title"] = result["title"]
        note["content"] = result["content"]
        note["formats"] = result["formats"]
        note["category"] = result.get("category", "")
        note["tags"] = result.get("tags", [])
        self.store.remember_category(note["category"])
        note["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.store.save()
        if self.current_section != "journal":
            self.store.set_source_reminder(note, result["remind_at"], result["repeat"], result.get("rule"))
        self.refresh_list()
        # 编辑对话框已保存完整结果，禁止旧的主编辑器内容再次覆盖它。
        self.select_note(note["id"], flush_current=False)
        if result.get("open_ai"):
            self.root.after_idle(lambda value=result["open_ai"]:
                                 self.open_ai_interview(value, show_recording=False))

    def enable_dialog_dpi_scaling(self, dialog, base_min_size):
        """让独立弹窗随所在显示器的 DPI 同步字体、间距和最小尺寸。"""
        scaler = WindowDpiScaler(
            dialog, user_factor=UI_FONT_SCALINGS.get(self.ui_font_size, 1.0),
            base_min_size=base_min_size)
        dialog._dpi_scaler = scaler  # 保持缩放器和字体对象的生命周期。
        refresh_job = None

        def refresh_dpi():
            nonlocal refresh_job
            refresh_job = None
            if not dialog.winfo_exists():
                return
            display = display_for_bounds(window_bounds(dialog), enumerate_displays())
            if display and display.dpi != scaler.current_dpi:
                scaler.apply(display.dpi)

        def schedule_refresh(_event=None):
            nonlocal refresh_job
            if refresh_job:
                try:
                    dialog.after_cancel(refresh_job)
                except tk.TclError:
                    pass
            # 等待窗口实际跨入目标屏幕后再读取 DPI，避免拖动过程反复缩放。
            refresh_job = dialog.after(80, refresh_dpi)

        dialog.bind("<Configure>", schedule_refresh, add="+")
        dialog.after_idle(refresh_dpi)
        return scaler

    def open_note_dialog(self, note: Optional[Dict] = None, kind: str = "sticky"):
        c = self.colors
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑便签" if kind == "sticky" else "编辑笔记")
        dialog.geometry("680x600" if kind == "journal" else "640x550")
        dialog.minsize(560, 470)
        dialog.configure(bg=c["bg"])
        dialog.transient(self.root)
        dialog.attributes("-topmost", self.top_var.get())
        result = {}

        form = tk.Frame(dialog, bg=c["bg"], padx=16, pady=14)
        form.grid(row=0, column=0, sticky="nsew")
        dialog.grid_rowconfigure(0, weight=1)
        dialog.grid_columnconfigure(0, weight=1)
        form.grid_rowconfigure(3, weight=1)
        form.grid_columnconfigure(0, weight=1)
        tk.Label(form, text="标题", bg=c["bg"], fg=c["muted"], anchor="w").grid(
            row=0, column=0, sticky="ew")
        title_var = tk.StringVar(value=(note or {}).get("title", ""))
        title_entry = tk.Entry(form, textvariable=title_var, bg=c["input"], fg=c["text"],
                               insertbackground=c["text"], relief="solid", bd=1,
                               font=("Microsoft YaHei UI", 11))
        title_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12), ipady=5)

        content_header = tk.Frame(form, bg=c["bg"])
        content_header.grid(row=2, column=0, sticky="ew")
        tk.Label(content_header, text="内容", bg=c["bg"], fg=c["muted"]).pack(side="left")
        bold_var = tk.BooleanVar(value=False)
        bold_button = tk.Button(content_header, text="B  加粗", bg=c["panel"], fg=c["text"],
                                activebackground=c["accent"], activeforeground="white",
                                relief="flat", bd=0, padx=10, pady=3,
                                font=("Microsoft YaHei UI", 9, "bold"))
        bold_button.pack(side="right")
        task_button = tk.Button(content_header, text="☐/☑ 完成", bg=c["panel"], fg=c["text"],
                                activebackground=c["accent"], activeforeground="white",
                                relief="flat", bd=0, padx=10, pady=3)
        task_button.pack(side="right", padx=(0, 6))

        content = tk.Text(form, bg=c["input"], fg=c["text"], insertbackground=c["text"],
                          relief="solid", bd=1, wrap="word", undo=True,
                          font=("Microsoft YaHei UI", 11), padx=8, pady=8, height=8)
        content.grid(row=3, column=0, sticky="nsew", pady=(5, 12))
        content.tag_configure("bold", font=("Microsoft YaHei UI", 11, "bold"))
        content.insert("1.0", (note or {}).get("content", ""))
        self.apply_format_ranges(content, (note or {}).get("formats", []))
        self.configure_task_checklist(content)

        source_reminder = next((r for r in self.store.reminders
                                if note and r.get("source_id") == note.get("id")), None)
        category_var = tk.StringVar(value=(note or {}).get("category", ""))
        tags_var = tk.StringVar(value="、".join((note or {}).get("tags", [])))

        def parsed_tags():
            values = [value.strip() for value in
                      tags_var.get().replace(",", "、").split("、") if value.strip()]
            return list(dict.fromkeys(values))

        def set_tags(values):
            tags_var.set("、".join(dict.fromkeys(value.strip() for value in values
                                                if value.strip())))

        schedule_row = 4
        if kind == "journal":
            metadata = tk.Frame(form, bg=c["bg"])
            metadata.grid(row=4, column=0, sticky="ew", pady=(0, 8))
            metadata_top = tk.Frame(metadata, bg=c["bg"])
            metadata_top.pack(fill="x")
            tk.Label(metadata_top, text="分类", bg=c["bg"], fg=c["muted"]).pack(side="left")
            category_box = ttk.Combobox(metadata_top, textvariable=category_var,
                                        values=self.store.categories, width=12)
            category_box.pack(side="left", padx=(5, 12))
            tk.Label(metadata_top, text="标签", bg=c["bg"], fg=c["muted"]).pack(side="left")
            tags_entry = tk.Entry(metadata_top, textvariable=tags_var, bg=c["input"],
                                  fg=c["text"], insertbackground=c["text"])
            tags_entry.pack(side="left", fill="x", expand=True, padx=5)
            tk.Label(metadata, text="已有标签（单击选择，双击或右键改名）",
                     bg=c["bg"], fg=c["muted"], anchor="w").pack(fill="x", pady=(7, 3))
            tag_cards = tk.Frame(metadata, bg=c["bg"])
            tag_cards.pack(fill="x")
            tag_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
            tag_refresh_job = None
            tag_layout_width = 0
            tag_click_jobs = {}
            suppress_tag_click = set()

            def toggle_tag(tag):
                tag_click_jobs.pop(tag, None)
                selected = parsed_tags()
                if tag in selected:
                    selected.remove(tag)
                else:
                    selected.append(tag)
                set_tags(selected)

            def schedule_tag_toggle(tag):
                if tag in suppress_tag_click:
                    suppress_tag_click.discard(tag)
                    return
                old_job = tag_click_jobs.pop(tag, None)
                if old_job:
                    dialog.after_cancel(old_job)
                tag_click_jobs[tag] = dialog.after(220, lambda: toggle_tag(tag))

            def rename_tag(tag, suppress_click=False):
                if suppress_click:
                    suppress_tag_click.add(tag)
                pending = tag_click_jobs.pop(tag, None)
                if pending:
                    dialog.after_cancel(pending)
                new_name = simpledialog.askstring(
                    "修改标签名", f"将“{tag}”修改为：", initialvalue=tag, parent=dialog)
                if new_name is None:
                    return "break"
                new_name = new_name.strip()
                if not new_name:
                    messagebox.showerror("标签名无效", "标签名不能为空。", parent=dialog)
                    return "break"
                if new_name != tag:
                    self.store.rename_tag(category_var.get(), tag, new_name)
                    set_tags([new_name if value == tag else value for value in parsed_tags()])
                    refresh_tag_cards()
                return "break"

            def refresh_tag_cards(*_args):
                nonlocal tag_layout_width
                for job in tag_click_jobs.values():
                    try:
                        dialog.after_cancel(job)
                    except tk.TclError:
                        pass
                tag_click_jobs.clear()
                for child in tag_cards.winfo_children():
                    child.destroy()
                available = max(240, tag_cards.winfo_width())
                tag_layout_width = available
                historical = self.store.tags_for_category(category_var.get())
                if not historical:
                    tk.Label(tag_cards, text="该分类暂无历史标签", bg=c["bg"],
                             fg=c["muted"], anchor="w").grid(row=0, column=0, sticky="w")
                    return
                selected = set(parsed_tags())
                row = column = used = 0
                for tag in historical:
                    card_width = min(available, tag_font.measure(tag) + 30)
                    if used and used + card_width + 5 > available:
                        row, column, used = row + 1, 0, 0
                    card = tk.Button(
                        tag_cards, text=tag, relief="flat", bd=0, padx=9, pady=3,
                        bg=c["accent"] if tag in selected else c["panel"],
                        fg="white" if tag in selected else c["text"],
                        activebackground=c["accent"], activeforeground="white",
                        command=lambda value=tag: schedule_tag_toggle(value),
                    )
                    card.grid(row=row, column=column, sticky="w", padx=(0, 5), pady=2)
                    card.bind("<Double-Button-1>",
                              lambda _e, value=tag: rename_tag(value, True))
                    card.bind("<Button-3>", lambda _e, value=tag: rename_tag(value))
                    column += 1
                    used += card_width + 5

            def schedule_tag_refresh(_event=None):
                nonlocal tag_refresh_job
                if tag_refresh_job:
                    try:
                        dialog.after_cancel(tag_refresh_job)
                    except tk.TclError:
                        pass

                def run_refresh():
                    nonlocal tag_refresh_job
                    tag_refresh_job = None
                    refresh_tag_cards()

                tag_refresh_job = dialog.after_idle(run_refresh)

            def on_tag_cards_resize(event):
                if abs(event.width - tag_layout_width) > 20:
                    schedule_tag_refresh()

            category_var.trace_add("write", schedule_tag_refresh)
            tags_var.trace_add("write", schedule_tag_refresh)
            tag_cards.bind("<Configure>", on_tag_cards_resize)
            dialog.after_idle(refresh_tag_cards)
            schedule_row = 5
        schedule = tk.Frame(form, bg=c["bg"])
        schedule.grid(row=schedule_row, column=0, sticky="ew", pady=(0, 10))
        tk.Label(schedule, text="提醒时间", bg=c["bg"], fg=c["muted"]).pack(side="left")
        remind_var = tk.StringVar(value=(source_reminder or {}).get("remind_at", ""))
        remind_entry = tk.Entry(schedule, textvariable=remind_var, width=18,
                                bg=c["input"], fg=c["text"], insertbackground=c["text"])
        remind_entry.pack(side="left", padx=(7, 4), ipady=3)
        tk.Button(schedule, text="选择", command=lambda: self._set_picked_time(remind_var, dialog),
                  bg=c["panel"], fg=c["text"], relief="flat", bd=0, padx=8).pack(side="left")
        tk.Label(schedule, text="年-月-日 时:分", bg=c["bg"], fg=c["muted"]).pack(side="left")
        repeat_names = {"none": "单次", "daily": "每天", "weekly": "每周",
                        "monthly": "每月", "yearly": "每年", "workday": "工作日"}
        repeat_var = tk.StringVar(value=repeat_names.get(
            (source_reminder or {}).get("repeat", "none"), "单次"))
        repeat_values = tuple(repeat_names.values())
        repeat_box = ttk.Combobox(schedule, textvariable=repeat_var, values=repeat_values,
                                  state="readonly", width=5)
        repeat_box.pack(side="right")
        rule_state = {key: (source_reminder or {}).get(key, default) for key, default in (
            ("interval", 1), ("weekdays", []), ("end_date", ""),
            ("advance_minutes", 0), ("paused", False))}
        tk.Button(schedule, text="高级", command=lambda: self.open_rule_dialog(rule_state, dialog),
                  bg=c["panel"], fg=c["text"], relief="flat", bd=0, padx=7).pack(side="right", padx=4)
        if kind == "journal":
            schedule.grid_remove()
            remind_var.set("")
            repeat_var.set("单次")

        def refresh_bold_button():
            active = bold_var.get()
            bold_button.configure(relief="sunken" if active else "flat",
                                  bg=c["accent"] if active else c["panel"],
                                  fg="white" if active else c["text"])

        def toggle_bold(_event=None):
            try:
                start, end = content.index("sel.first"), content.index("sel.last")
                if "bold" in content.tag_names("sel.first"):
                    content.tag_remove("bold", start, end)
                    bold_var.set(False)
                else:
                    content.tag_add("bold", start, end)
                    bold_var.set(True)
            except tk.TclError:
                bold_var.set(not bold_var.get())
            refresh_bold_button()
            content.focus_set()
            return "break"

        def apply_typed_bold(start):
            if bold_var.get() and content.compare(content.index("insert"), ">", start):
                content.tag_add("bold", start, "insert")

        def on_keypress(event):
            if not bold_var.get() or event.keysym in {
                "BackSpace", "Delete", "Left", "Right", "Up", "Down",
                "Home", "End", "Prior", "Next", "Shift_L", "Shift_R",
                "Control_L", "Control_R", "Alt_L", "Alt_R", "Escape"
            }:
                return None
            start = content.index("insert")
            content.after_idle(lambda: apply_typed_bold(start))
            return None

        def save_dialog(_event=None, analyze_type=None):
            remind_at = remind_var.get().strip()
            if remind_at:
                try:
                    when = datetime.strptime(remind_at, "%Y-%m-%d %H:%M")
                except ValueError:
                    messagebox.showerror("时间格式错误", "请使用：2026-07-22 20:30", parent=dialog)
                    return "break"
                if when <= datetime.now() and not source_reminder:
                    messagebox.showerror("提醒时间无效", "首次提醒时间需要晚于当前时间。", parent=dialog)
                    return "break"
            result.update({
                "title": title_var.get().strip() or "无标题",
                "content": content.get("1.0", "end-1c"),
                "formats": self.extract_format_ranges(content),
                "remind_at": remind_at,
                "repeat": {value: key for key, value in repeat_names.items()}[repeat_var.get()],
                "rule": dict(rule_state),
                "category": category_var.get().strip(),
                "tags": parsed_tags(),
            })
            if analyze_type:
                result["open_ai"] = analyze_type
            dialog.destroy()
            return "break"

        def cancel_dialog(_event=None):
            dialog.destroy()
            return "break"

        bold_button.configure(command=toggle_bold)
        task_button.configure(command=lambda: self.toggle_task_line(content))
        content.bind("<KeyPress>", on_keypress, add="+")
        content.bind("<Control-b>", toggle_bold)
        content.bind("<Control-B>", toggle_bold)
        self.bind_undo_redo(content)
        dialog.bind("<Control-Return>", save_dialog)
        dialog.bind("<Escape>", cancel_dialog)
        dialog.protocol("WM_DELETE_WINDOW", cancel_dialog)

        actions_row = schedule_row + 1
        if kind == "journal":
            ai_actions = tk.Frame(form, bg=c["bg"])
            ai_actions.grid(row=actions_row, column=0, sticky="ew", pady=(0, 10))
            tk.Label(ai_actions, text="AI模板", bg=c["bg"], fg=c["muted"]).pack(side="left")
            tk.Button(
                ai_actions, text="面试复盘",
                command=lambda: save_dialog(analyze_type="interview"),
                bg=c["panel"], fg=c["text"], activebackground=c["accent"],
                activeforeground="white", relief="flat", padx=12, pady=5).pack(
                    side="left", padx=(8, 4), fill="x", expand=True)
            tk.Button(
                ai_actions, text="会议总结",
                command=lambda: save_dialog(analyze_type="meeting"),
                bg=c["panel"], fg=c["text"], activebackground=c["accent"],
                activeforeground="white", relief="flat", padx=12, pady=5).pack(
                    side="left", padx=(4, 0), fill="x", expand=True)
            actions_row += 1
        actions = tk.Frame(form, bg=c["bg"])
        actions.grid(row=actions_row, column=0, sticky="ew")
        tk.Button(actions, text="取消", command=cancel_dialog, bg=c["panel"], fg=c["text"],
                  relief="flat", padx=18, pady=5).pack(side="right")
        tk.Button(actions, text="保存", command=save_dialog, bg=c["accent"], fg="white",
                  relief="flat", padx=18, pady=5).pack(side="right", padx=(0, 8))

        self.enable_dialog_dpi_scaling(dialog, base_min_size=(560, 470))
        dialog.grab_set()
        title_entry.focus_set()
        dialog.wait_window()
        return result or None

    def _set_picked_time(self, target_var, parent=None):
        selected = self.pick_datetime(target_var.get().strip(), parent)
        if selected:
            target_var.set(selected)
        if parent and parent.winfo_exists():
            parent.grab_set()

    def open_reminder_dialog(self, initial_time: str):
        c = self.colors
        dialog = tk.Toplevel(self.root)
        dialog.title("新建提醒")
        dialog.geometry("560x430")
        dialog.minsize(480, 380)
        dialog.configure(bg=c["bg"])
        dialog.transient(self.root)
        dialog.attributes("-topmost", self.top_var.get())
        result = {}
        form = tk.Frame(dialog, bg=c["bg"], padx=16, pady=14)
        form.pack(fill="both", expand=True)
        tk.Label(form, text="标题", bg=c["bg"], fg=c["muted"], anchor="w").pack(fill="x")
        title_var = tk.StringVar()
        title = tk.Entry(form, textvariable=title_var, bg=c["input"], fg=c["text"],
                         insertbackground=c["text"])
        title.pack(fill="x", pady=(4, 10), ipady=5)
        tk.Label(form, text="说明", bg=c["bg"], fg=c["muted"], anchor="w").pack(fill="x")
        content = tk.Text(form, height=5, bg=c["input"], fg=c["text"],
                          insertbackground=c["text"], wrap="word", undo=True)
        content.pack(fill="both", expand=True, pady=(4, 10))
        self.bind_undo_redo(content)
        row = tk.Frame(form, bg=c["bg"])
        row.pack(fill="x")
        tk.Label(row, text="提醒时间", bg=c["bg"], fg=c["muted"]).pack(side="left")
        remind_var = tk.StringVar(value=initial_time)
        tk.Entry(row, textvariable=remind_var, bg=c["input"], fg=c["text"],
                 insertbackground=c["text"], width=18).pack(side="left", padx=7, ipady=3)
        tk.Button(row, text="重新选择", command=lambda: self._set_picked_time(remind_var, dialog),
                  bg=c["panel"], fg=c["text"], relief="flat", bd=0, padx=8).pack(side="left")
        repeat_names = {"none": "单次", "daily": "每天", "weekly": "每周",
                        "monthly": "每月", "yearly": "每年", "workday": "工作日"}
        repeat_var = tk.StringVar(value="单次")
        rule_state = {"interval": 1, "weekdays": [], "end_date": "",
                      "advance_minutes": 0, "paused": False}
        rule_row = tk.Frame(form, bg=c["bg"])
        rule_row.pack(fill="x", pady=(8, 0))
        tk.Label(rule_row, text="重复规则", bg=c["bg"], fg=c["muted"]).pack(side="left")
        ttk.Combobox(rule_row, textvariable=repeat_var, values=tuple(repeat_names.values()),
                     state="readonly", width=7).pack(side="left", padx=7)
        tk.Button(rule_row, text="高级设置", command=lambda: self.open_rule_dialog(rule_state, dialog),
                  bg=c["panel"], fg=c["text"], relief="flat", bd=0, padx=8).pack(side="left")

        def close():
            dialog.destroy()

        def save():
            try:
                when = datetime.strptime(remind_var.get().strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showerror("时间格式错误", "请使用：2026-07-22 20:30", parent=dialog)
                return
            if when <= datetime.now():
                messagebox.showerror("提醒时间无效", "提醒时间需要晚于当前时间。", parent=dialog)
                return
            result.update({"title": title_var.get().strip() or "未命名提醒",
                           "content": content.get("1.0", "end-1c"),
                           "remind_at": remind_var.get().strip(),
                           "repeat": {value: key for key, value in repeat_names.items()}[repeat_var.get()],
                           "rule": dict(rule_state)})
            dialog.destroy()

        actions = tk.Frame(form, bg=c["bg"])
        actions.pack(fill="x", pady=(10, 0))
        tk.Button(actions, text="取消", command=close, bg=c["panel"], fg=c["text"],
                  relief="flat", padx=18, pady=5).pack(side="right")
        tk.Button(actions, text="保存", command=save, bg=c["accent"], fg="white",
                  relief="flat", padx=18, pady=5).pack(side="right", padx=8)
        dialog.bind("<Escape>", lambda _e: close())
        self.enable_dialog_dpi_scaling(dialog, base_min_size=(480, 380))
        dialog.grab_set()
        title.focus_set()
        dialog.wait_window()
        return result or None

    def open_rule_dialog(self, rule_state: Dict, parent):
        c = self.colors
        dialog = tk.Toplevel(parent)
        dialog.title("高级提醒规则")
        dialog.geometry("470x360")
        dialog.configure(bg=c["bg"])
        dialog.transient(parent)
        form = tk.Frame(dialog, bg=c["bg"], padx=18, pady=16)
        form.pack(fill="both", expand=True)
        interval_var = tk.IntVar(value=max(1, int(rule_state.get("interval", 1))))
        advance_names = {"不提前": 0, "提前10分钟": 10, "提前30分钟": 30,
                         "提前1小时": 60, "提前1天": 1440}
        current_advance = int(rule_state.get("advance_minutes", 0))
        advance_var = tk.StringVar(value=next((k for k, v in advance_names.items()
                                               if v == current_advance), "不提前"))
        end_var = tk.StringVar(value=rule_state.get("end_date", ""))
        paused_var = tk.BooleanVar(value=bool(rule_state.get("paused", False)))
        row = tk.Frame(form, bg=c["bg"]); row.pack(fill="x", pady=5)
        tk.Label(row, text="间隔", bg=c["bg"], fg=c["text"], width=10, anchor="w").pack(side="left")
        tk.Spinbox(row, from_=1, to=99, textvariable=interval_var, width=5).pack(side="left")
        tk.Label(row, text="个周期", bg=c["bg"], fg=c["muted"]).pack(side="left", padx=6)
        row = tk.Frame(form, bg=c["bg"]); row.pack(fill="x", pady=5)
        tk.Label(row, text="每周日期", bg=c["bg"], fg=c["text"], width=10, anchor="w").pack(side="left")
        weekday_vars = []
        existing = {int(x) for x in rule_state.get("weekdays", [])}
        for index, name in enumerate("一二三四五六日"):
            var = tk.BooleanVar(value=index in existing); weekday_vars.append(var)
            tk.Checkbutton(row, text=name, variable=var, bg=c["bg"], fg=c["text"],
                           selectcolor=c["panel"], activebackground=c["bg"]).pack(side="left")
        row = tk.Frame(form, bg=c["bg"]); row.pack(fill="x", pady=5)
        tk.Label(row, text="提前提醒", bg=c["bg"], fg=c["text"], width=10, anchor="w").pack(side="left")
        ttk.Combobox(row, textvariable=advance_var, values=list(advance_names),
                     state="readonly", width=13).pack(side="left")
        row = tk.Frame(form, bg=c["bg"]); row.pack(fill="x", pady=5)
        tk.Label(row, text="结束日期", bg=c["bg"], fg=c["text"], width=10, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=end_var, bg=c["input"], fg=c["text"], width=14).pack(side="left")
        tk.Label(row, text="可留空，格式2026-12-31", bg=c["bg"], fg=c["muted"]).pack(side="left", padx=6)
        tk.Checkbutton(form, text="暂停该提醒", variable=paused_var, bg=c["bg"], fg=c["text"],
                       selectcolor=c["panel"], activebackground=c["bg"]).pack(anchor="w", pady=8)

        def save():
            end_date = end_var.get().strip()
            if end_date:
                try:
                    date.fromisoformat(end_date)
                except ValueError:
                    messagebox.showerror("日期错误", "结束日期格式应为2026-12-31", parent=dialog)
                    return
            rule_state.update({"interval": max(1, interval_var.get()),
                               "weekdays": [i for i, var in enumerate(weekday_vars) if var.get()],
                               "end_date": end_date,
                               "advance_minutes": advance_names[advance_var.get()],
                               "paused": paused_var.get()})
            dialog.destroy()
        actions = tk.Frame(form, bg=c["bg"]); actions.pack(fill="x", side="bottom")
        tk.Button(actions, text="取消", command=dialog.destroy, bg=c["panel"], fg=c["text"],
                  relief="flat", padx=16, pady=5).pack(side="right")
        tk.Button(actions, text="保存规则", command=save, bg=c["accent"], fg="white",
                  relief="flat", padx=16, pady=5).pack(side="right", padx=8)
        self.enable_dialog_dpi_scaling(dialog, base_min_size=(470, 360))
        dialog.grab_set(); dialog.wait_window()
        if parent.winfo_exists():
            parent.grab_set()

    @staticmethod
    def extract_format_ranges(text_widget: tk.Text):
        ranges = text_widget.tag_ranges("bold")
        return [{"start": str(ranges[i]), "end": str(ranges[i + 1]), "style": "bold"}
                for i in range(0, len(ranges), 2)]

    @staticmethod
    def apply_format_ranges(text_widget: tk.Text, formats):
        for item in formats or []:
            if item.get("style") != "bold":
                continue
            try:
                text_widget.tag_add("bold", item["start"], item["end"])
            except (tk.TclError, KeyError, TypeError):
                continue

    @staticmethod
    def undo_text(event):
        try:
            event.widget.edit_undo()
        except tk.TclError:
            pass
        return "break"

    @staticmethod
    def redo_text(event):
        try:
            event.widget.edit_redo()
        except tk.TclError:
            pass
        return "break"

    def bind_undo_redo(self, text_widget: tk.Text):
        for sequence in ("<Control-z>", "<Control-Z>"):
            text_widget.bind(sequence, self.undo_text)
        for sequence in ("<Control-y>", "<Control-Y>",
                         "<Control-Shift-z>", "<Control-Shift-Z>"):
            text_widget.bind(sequence, self.redo_text)

    @staticmethod
    def toggled_task_line(line: str) -> str:
        """将一行普通文本转为待办，或在未完成/已完成之间切换。"""
        if line.startswith("☐ "):
            return "☑ " + line[2:]
        if line.startswith("☑ "):
            return "☐ " + line[2:]
        return "☐ " + line

    @staticmethod
    def split_completed_task_blocks(content: str):
        """提取已勾选任务及其后续说明，保留未完成任务和普通正文。"""
        lines = content.splitlines(keepends=True)
        remaining, completed = [], []
        index = 0
        while index < len(lines):
            if lines[index].startswith("☑ "):
                block = [lines[index]]
                index += 1
                while index < len(lines) and not lines[index].startswith(("☐ ", "☑ ")):
                    block.append(lines[index])
                    index += 1
                completed.append("".join(block).strip())
                continue
            remaining.append(lines[index])
            index += 1
        return "".join(remaining).strip(), completed

    def set_task_view(self, view):
        if self.current_section not in ("sticky", "journal"):
            return
        self.task_view = view
        self.pending_button.state(["selected"] if view == "pending" else ["!selected"])
        self.task_button.state(["selected"] if view == "completed" else ["!selected"])
        self.apply_task_view()

    def apply_task_view(self):
        """在主界面按任务状态隐藏整段内容；完整正文仍保留，编辑请双击标题。"""
        if not self.current or self.current_section not in ("sticky", "journal"):
            return
        self.editor.configure(state="normal")
        self.editor.tag_remove("task_hidden", "1.0", "end")
        last_line = int(self.editor.index("end-1c").split(".")[0])
        task_lines = []
        for line in range(1, last_line + 1):
            prefix = self.editor.get(f"{line}.0", f"{line}.2")
            if prefix in ("☐ ", "☑ "):
                task_lines.append((line, prefix == "☑ "))
        if self.task_view == "completed":
            if task_lines:
                self.editor.tag_add("task_hidden", "1.0", f"{task_lines[0][0]}.0")
            else:
                self.editor.tag_add("task_hidden", "1.0", "end")
        for index, (line, completed) in enumerate(task_lines):
            end = f"{task_lines[index + 1][0]}.0" if index + 1 < len(task_lines) else "end"
            hide = completed if self.task_view == "pending" else not completed
            if hide:
                self.editor.tag_add("task_hidden", f"{line}.0", end)
        self.editor.tag_configure("task_hidden", elide=True)

    def archive_current_task_line(self, line_number):
        """将主界面中当前任务块归档，并从原正文中移除。"""
        if not self.current or self.current_section not in ("sticky", "journal"):
            return
        try:
            start = f"{line_number}.0"
            last_line = int(self.editor.index("end-1c").split(".")[0])
            next_line = line_number + 1
            while next_line <= last_line:
                prefix = self.editor.get(f"{next_line}.0", f"{next_line}.2")
                if prefix in ("☐ ", "☑ "):
                    break
                next_line += 1
            end = f"{next_line}.0" if next_line <= last_line else "end-1c"
            task_content = self.editor.get(start, end).strip()
            if not task_content.startswith("☐ "):
                return
            self.store.archive_completed_task(
                self.current_section, self.current.get("id", ""),
                self.title_var.get(), "☑ " + task_content[2:])
            self.editor.delete(start, end)
            self.refresh_task_checklist(self.editor)
            self.status_var.set("已归档到“已完成”")
        except tk.TclError:
            return

    def save_completed_task_blocks(self, note, kind, task_blocks):
        for task_content in task_blocks or []:
            self.store.archive_completed_task(
                kind, note.get("id", ""), note.get("title", "无标题"), task_content)

    def open_completed_tasks(self):
        """打开当前便签或笔记板块的已完成归档卡片。"""
        kind = self.current_section if self.current_section in ("sticky", "journal") else "sticky"
        title = "已完成便签" if kind == "sticky" else "已完成笔记"
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("620x460")
        dialog.minsize(480, 340)
        dialog.configure(bg=self.colors["bg"])
        dialog.transient(self.root)
        dialog.attributes("-topmost", self.top_var.get())
        frame = tk.Frame(dialog, bg=self.colors["bg"], padx=14, pady=14)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=title, bg=self.colors["bg"], fg=self.colors["text"],
                 font=("Microsoft YaHei UI", 14, "bold"), anchor="w").pack(fill="x")
        tk.Label(frame, text="已勾选任务会自动归档在这里。", bg=self.colors["bg"],
                 fg=self.colors["muted"], anchor="w").pack(fill="x", pady=(2, 8))
        body = tk.PanedWindow(frame, orient="horizontal", sashwidth=5, bd=0, relief="flat")
        body.pack(fill="both", expand=True)
        task_list = tk.Listbox(body, bg=self.colors["panel"], fg=self.colors["text"],
                               selectbackground=self.colors["accent"], activestyle="none")
        detail = tk.Text(body, bg=self.colors["input"], fg=self.colors["text"],
                         wrap="word", relief="solid", bd=1, padx=10, pady=8)
        detail.configure(state="disabled")
        body.add(task_list, minsize=150)
        body.add(detail, minsize=260)
        records = [record for record in self.store.completed_tasks if record.get("kind") == kind]
        for record in records:
            when = record.get("completed_at", "").replace("T", " ")[:16]
            task_list.insert("end", f"✓ {record.get('source_title', '无标题')[:12]} · {when}")

        def show_record(_event=None):
            selected = task_list.curselection()
            if not selected:
                return
            record = records[selected[0]]
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("1.0", f"来源：{record.get('source_title', '无标题')}\n"
                          f"完成时间：{record.get('completed_at', '').replace('T', ' ')}\n\n"
                          f"{record.get('content', '')}")
            detail.configure(state="disabled")

        task_list.bind("<<ListboxSelect>>", show_record)
        if records:
            task_list.selection_set(0)
            show_record()
        self.enable_dialog_dpi_scaling(dialog, base_min_size=(480, 340))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def refresh_task_checklist(self, text_widget: tk.Text):
        """依据正文中的任务标记更新完成项的视觉样式和可点击区域。"""
        try:
            text_widget.tag_remove("task_marker", "1.0", "end")
            text_widget.tag_remove("task_done", "1.0", "end")
            last_line = int(text_widget.index("end-1c").split(".")[0])
            for line_number in range(1, last_line + 1):
                start = f"{line_number}.0"
                prefix = text_widget.get(start, f"{line_number}.2")
                if prefix in ("☐ ", "☑ "):
                    text_widget.tag_add("task_marker", start, f"{line_number}.1")
                    if prefix == "☑ ":
                        text_widget.tag_add("task_done", f"{line_number}.2",
                                            f"{line_number}.end")
        except tk.TclError:
            return

    def configure_task_checklist(self, text_widget: tk.Text):
        """为正文编辑器配置待办点击和完成样式；任务状态仍保存为普通正文。"""
        if getattr(text_widget, "_task_checklist_configured", False):
            self.refresh_task_checklist(text_widget)
            return
        text_widget._task_checklist_configured = True
        text_widget.tag_configure("task_marker", foreground=self.colors["accent"], underline=1)
        text_widget.tag_configure("task_done", foreground=self.colors["muted"], overstrike=1)

        def toggle_clicked_marker(event):
            index = text_widget.index(f"@{event.x},{event.y}")
            line_number, column = (int(value) for value in index.split("."))
            if column <= 1:
                prefix = text_widget.get(f"{line_number}.0", f"{line_number}.2")
                complete_handler = getattr(text_widget, "_complete_task_handler", None)
                if prefix == "☐ " and complete_handler:
                    complete_handler(line_number)
                    return "break"
                self.toggle_task_line(text_widget, line_number)
                return "break"
            return None

        text_widget.tag_bind("task_marker", "<Button-1>", toggle_clicked_marker)
        text_widget.bind("<KeyRelease>",
                         lambda _event: text_widget.after_idle(
                             lambda: self.refresh_task_checklist(text_widget)), add="+")
        self.refresh_task_checklist(text_widget)

    def toggle_task_line(self, text_widget: tk.Text, line_number=None):
        """切换光标所在行的待办状态；普通行首次点击会转为未完成待办。"""
        try:
            line_number = line_number or int(text_widget.index("insert").split(".")[0])
            start, end = f"{line_number}.0", f"{line_number}.end"
            original = text_widget.get(start, end)
            text_widget.delete(start, end)
            text_widget.insert(start, self.toggled_task_line(original))
            text_widget.edit_separator()
            self.refresh_task_checklist(text_widget)
            text_widget.mark_set("insert", start)
            text_widget.focus_set()
            if text_widget is self.editor:
                self.apply_task_view()
                self.schedule_save()
        except tk.TclError:
            return

    def toggle_current_task(self):
        if self.current_section in ("sticky", "journal") and self.current:
            line_number = int(self.editor.index("insert").split(".")[0])
            prefix = self.editor.get(f"{line_number}.0", f"{line_number}.2")
            if prefix == "☐ ":
                self.archive_current_task_line(line_number)
            else:
                self.toggle_task_line(self.editor, line_number)

    def delete_note(self, parent=None):
        _parent = parent or self.root
        if self.current_section in ("news",):
            return
        if self.current_section == "reminder":
            if not self.current_reminder:
                return
            if messagebox.askyesno("删除提醒", "确定删除当前提醒吗？", parent=_parent):
                self.store.delete_reminder(self.current_reminder["id"])
                self.current_reminder = None
                self.refresh_list()
                if self.store.reminders:
                    self.select_reminder(self.store.reminders[0]["id"])
                else:
                    self.clear_editor()
            return
        if not self.current:
            return
        if not messagebox.askyesno("删除便签", "确定删除当前便签吗？", parent=_parent):
            return
        self.store.delete(self.current["id"])
        self.current = None
        self.refresh_list()
        remaining = self.visible_notes()
        if remaining:
            self.select_note(remaining[0]["id"])
        else:
            self.clear_editor()

    def visible_notes(self, section=None):
        section = section or self.current_section
        notes = self.store.notes_by_kind(section)
        if section != "journal":
            return notes
        category = self.category_filter_var.get()
        if category == "未分类":
            notes = [n for n in notes if not n.get("category")]
        elif category and category != "全部分类":
            notes = [n for n in notes if n.get("category") == category]
        query = self.search_var.get().strip().lower()
        if query:
            notes = [n for n in notes if query in " ".join([
                n.get("title", ""), n.get("content", ""), n.get("category", ""),
                " ".join(n.get("tags", []))]).lower()]
        return notes

    def refresh_list(self):
        if self.current_section == "journal":
            self.store.sync_categories()
            category_values = ["全部分类", "未分类"] + self.store.categories
            self.category_filter.configure(values=category_values)
            if self.category_filter_var.get() not in category_values:
                self.category_filter_var.set("全部分类")
        selected_id = (self.current_reminder.get("id") if self.current_section == "reminder" and self.current_reminder
                       else self.current.get("id") if self.current
                       else self.current_news.get("permalink") if self.current_news else None)
        self.listbox.delete(0, "end")
        if self.current_section == "reminder":
            items = sorted(self.store.reminders, key=lambda r: r.get("remind_at", ""))
            for reminder in items:
                state = "✓" if reminder.get("status") == "completed" else "⏰"
                short_time = reminder.get("remind_at", "")[5:]
                self.listbox.insert("end", f"{state} {reminder.get('title', '未命名')[:10]} · {short_time}")
        elif self.current_section == "news":
            items = self.news_items
            for item in items:
                self.listbox.insert("end", f"[{item.get('category', '其他')}] {item.get('title', '')}")
        else:
            items = self.visible_notes()
            reminder_ids = {r.get("source_id") for r in self.store.reminders
                            if r.get("status") in ("pending", "notified")}
            for note in items:
                mark = " ⏰" if note.get("id") in reminder_ids else ""
                prefix = f"[{note.get('category')}] " if self.current_section == "journal" and note.get("category") else ""
                title = prefix + (note.get("title") or "无标题").strip().replace("\n", " ")[:16]
                self.listbox.insert("end", title + mark)
        # Listbox 的 height 单位是行数；刷新、新建、删除或筛选后都会重新计算。
        self.listbox.configure(height=max(1, len(items)))
        if selected_id:
            for index, item in enumerate(items):
                identity = item.get("permalink") if self.current_section == "news" else item.get("id")
                if identity == selected_id:
                    self.listbox.selection_set(index)
                    break
        self.section_nav.set_counts({"reminder": sum(
            1 for r in self.store.reminders if r.get("status") in ("pending", "notified"))})

    def select_note(self, note_id: str, flush_current: bool = True):
        if flush_current:
            self.flush_save()
        note = next((n for n in self.store.notes if n.get("id") == note_id), None)
        if not note:
            return
        self.current = note
        self.section_selection_ids[note.get("kind", self.current_section)] = note_id
        self.current_reminder = None
        self.current_news = None
        self.title_entry.configure(state="normal")
        self.editor.configure(state="normal")
        self.title_var.set(note.get("title", ""))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", note.get("content", ""))
        self.editor.tag_remove("bold", "1.0", "end")
        self.apply_format_ranges(self.editor, note.get("formats", []))
        self.refresh_task_checklist(self.editor)
        self.editor.edit_modified(False)
        self.apply_task_view()
        source_reminder = next((r for r in self.store.reminders
                                if r.get("source_id") == note_id), None)
        self.reminder_var.set((source_reminder or {}).get("remind_at", ""))
        self.update_learning_stats()
        self.refresh_list()

    def select_reminder(self, reminder_id: str):
        reminder = next((r for r in self.store.reminders if r.get("id") == reminder_id), None)
        if not reminder:
            return
        self.current = None
        self.current_reminder = reminder
        self.section_selection_ids["reminder"] = reminder_id
        self.current_news = None
        self.title_entry.configure(state="normal")
        self.editor.configure(state="normal")
        self.title_var.set(reminder.get("title", "未命名提醒"))
        self.title_entry.configure(state="disabled")
        source_names = {"sticky": "便签", "journal": "笔记", "independent": "独立提醒"}
        repeat_names = {"none": "单次", "daily": "每天", "weekly": "每周",
                        "monthly": "每月", "yearly": "每年", "workday": "工作日"}
        detail = (f"提醒时间：{reminder.get('remind_at', '')}\n"
                  f"重复：{repeat_names.get(reminder.get('repeat'), '单次')}\n"
                  f"提前：{reminder.get('advance_minutes', 0)}分钟\n"
                  f"暂停：{'是' if reminder.get('paused') else '否'}\n"
                  f"来源：{source_names.get(reminder.get('source_type'), '提醒')}\n"
                  f"状态：{reminder.get('status', 'pending')}\n\n"
                  f"{reminder.get('content', '')}")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", detail)
        self.editor.configure(state="disabled")
        self.reminder_var.set(reminder.get("remind_at", ""))
        self.refresh_list()

    def on_list_select(self, _event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        if self.current_section == "news":
            wanted = self.news_items[selection[0]] if selection[0] < len(self.news_items) else None
            if wanted and (not self.current_news or
                           wanted.get("permalink") != self.current_news.get("permalink")):
                self.select_news(selection[0])
        elif self.current_section == "reminder":
            items = sorted(self.store.reminders, key=lambda r: r.get("remind_at", ""))
            if selection[0] < len(items):
                self.select_reminder(items[selection[0]]["id"])
        else:
            items = self.visible_notes()
            if selection[0] < len(items):
                wanted = items[selection[0]]["id"]
                if not self.current or wanted != self.current.get("id"):
                    self.select_note(wanted)

    def on_text_modified(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self.schedule_save()

    def schedule_save(self):
        if not self.current:
            return
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.status_var.set("正在编辑…")
        self.save_job = self.root.after(450, self.flush_save)

    def flush_save(self):
        if self.save_job:
            try:
                self.root.after_cancel(self.save_job)
            except tk.TclError:
                pass
            self.save_job = None
        if not self.current or self.current_section == "reminder":
            return
        self.current["title"] = self.title_var.get().strip() or "无标题"
        self.current["content"] = self.editor.get("1.0", "end-1c")
        self.current["formats"] = self.extract_format_ranges(self.editor)
        self.current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.store.save()
        source_reminder = next((r for r in self.store.reminders
                                if r.get("source_id") == self.current.get("id")), None)
        if source_reminder:
            source_reminder["title"] = self.current["title"]
            source_reminder["content"] = self.current["content"]
            self.store.save()
        self.refresh_list()
        self.status_var.set("已保存到本地")

    def set_reminder(self):
        if not self.current:
            return
        value = self.reminder_var.get().strip()
        if value:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showerror("时间格式错误", "请使用：年-月-日 时:分\n例如：2026-07-20 18:30", parent=self.root)
                return
            if parsed <= datetime.now():
                messagebox.showerror("提醒时间无效", "提醒时间需要晚于当前时间。", parent=self.root)
                return
        existing = next((r for r in self.store.reminders
                         if r.get("source_id") == self.current.get("id")), None)
        repeat = (existing or {}).get("repeat", "none")
        self.store.set_source_reminder(self.current, value, repeat)
        self.refresh_list()
        self.status_var.set("提醒已设置" if value else "提醒已取消")

    def check_reminders(self):
        if self.closing:
            return
        if self.store.settings.get("reminders_paused", False):
            self.root.after(15_000, self.check_reminders)
            return
        now = datetime.now()
        due = self.store.due_reminders(now)
        if due:
            self.refresh_list()
            for reminder in due:
                self.show_reminder(reminder)
        self.root.after(15_000, self.check_reminders)

    def show_reminder(self, reminder: Dict):
        was_hidden = self.root.state() == "withdrawn"
        self.reveal_from_edge()
        source_names = {"sticky": "便签", "journal": "笔记", "independent": "提醒"}
        notification_text = (reminder.get("content", "")[:160] or
                             f"来自{source_names.get(reminder.get('source_type'), '提醒')}，时间到了。")
        if was_hidden and send_windows_notification(
                reminder.get("title", "轻笺提醒"), notification_text):
            return
        self.root.deiconify()
        self.root.lift()
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except (ImportError, RuntimeError):
            self.root.bell()
        dialog = tk.Toplevel(self.root)
        dialog.title("轻笺提醒")
        dialog.geometry("420x240")
        dialog.configure(bg=self.colors["bg"])
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        tk.Label(dialog, text=reminder.get("title", "未命名提醒"),
                 bg=self.colors["bg"], fg=self.colors["text"],
                 font=("Microsoft YaHei UI", 15, "bold"), wraplength=370).pack(pady=(22, 8))
        tk.Label(dialog, text=reminder.get("content", "")[:180] or "提醒时间到了。",
                 bg=self.colors["bg"], fg=self.colors["muted"],
                 wraplength=370, justify="left").pack(fill="both", expand=True, padx=20)
        actions = tk.Frame(dialog, bg=self.colors["bg"], pady=14)
        actions.pack(fill="x")

        def complete():
            self.store.complete_reminder(reminder["id"])
            dialog.destroy()
            self.refresh_list()

        def snooze():
            self.store.snooze_reminder(reminder["id"], 30)
            dialog.destroy()
            self.refresh_list()

        def open_source():
            dialog.destroy()
            self.open_reminder_source(reminder)

        tk.Button(actions, text="完成", command=complete, bg=self.colors["accent"],
                  fg="white", relief="flat", padx=15, pady=5).pack(side="right", padx=(6, 18))
        tk.Button(actions, text="稍后30分钟", command=snooze, bg=self.colors["panel"],
                  fg=self.colors["text"], relief="flat", padx=12, pady=5).pack(side="right")
        if reminder.get("source_id"):
            tk.Button(actions, text="打开来源", command=open_source, bg=self.colors["panel"],
                      fg=self.colors["text"], relief="flat", padx=12, pady=5).pack(side="left", padx=18)
        dialog.protocol("WM_DELETE_WINDOW", snooze)

    def complete_current_reminder(self):
        if not self.current_reminder:
            return
        self.store.complete_reminder(self.current_reminder["id"])
        self.refresh_list()
        self.select_reminder(self.current_reminder["id"])

    def snooze_current_reminder(self):
        if not self.current_reminder:
            return
        self.store.snooze_reminder(self.current_reminder["id"], 30)
        self.refresh_list()
        self.select_reminder(self.current_reminder["id"])

    def skip_current_reminder(self):
        if self.current_reminder:
            self.store.complete_reminder(self.current_reminder["id"])
            self.refresh_list()
            self.select_reminder(self.current_reminder["id"])

    def pause_current_reminder(self):
        if self.current_reminder:
            self.store.toggle_reminder_paused(self.current_reminder["id"])
            self.refresh_list()
            self.select_reminder(self.current_reminder["id"])

    def open_current_source(self):
        if self.current_reminder:
            self.open_reminder_source(self.current_reminder)

    def open_reminder_source(self, reminder: Dict):
        source_id = reminder.get("source_id")
        note = next((n for n in self.store.notes if n.get("id") == source_id), None)
        if not note:
            return
        self.switch_section(note.get("kind", "sticky"))
        self.select_note(source_id)

    def toggle_topmost(self):
        value = self.top_var.get()
        self.root.attributes("-topmost", value)
        self.quick_rail.attributes("-topmost", value)
        self.store.settings["topmost"] = value
        self.sync_check_labels()
        self.store.save()

    def toggle_edge(self):
        self.store.settings["edge_hide"] = self.edge_var.get()
        if not self.edge_var.get():
            self.reveal_from_edge()
        self.sync_check_labels()
        self.store.save()

    def change_alpha(self, value):
        alpha = round(float(value), 2)
        self.store.settings["alpha"] = alpha
        self.quick_rail.attributes("-alpha", alpha)
        self.store.save()
        self.update_readability_alpha()

    def change_ui_font_size(self, _event=None):
        selected = self.ui_font_var.get()
        if selected not in UI_FONT_SCALINGS:
            return
        self.ui_font_size = selected
        self.store.settings["ui_font_size"] = selected
        self.store.save()
        self.ai_settings_status_var.set("界面字号已保存，使用托盘“刷新轻笺”后生效。")

    def update_readability_alpha(self, inside=None):
        """鼠标进入时略微提高不透明度，离开后恢复用户设置。"""
        if inside is not None:
            self.hovered = inside
        base = float(self.store.settings["alpha"])
        enhanced = self.store.settings.get("hover_readability", True) and self.hovered
        effective = min(0.96, base + 0.12) if enhanced else base
        self.root.attributes("-alpha", effective)

    def on_configure(self, event):
        if event.widget is self.root and not self.hidden_edge and self.root.state() == "normal":
            self._schedule_rounded_region(self.root, radius=18)
            self._enforce_ui_scaling()
            self.store.settings["geometry"] = self.root.geometry()
            self.store.settings["window_bounds"] = list(window_bounds(self.root))
            if self.main_dpi_scaler and self.main_dpi_scaler.current_dpi:
                self.store.settings["window_dpi"] = self.main_dpi_scaler.current_dpi
            self.update_compact_layout(self.root.winfo_width())
            self.update_toolbar_labels(self.root.winfo_width())
            self.root.after_idle(self.adjust_responsive_sash)
            old_width = getattr(self, "quick_layout_root_width", 0)
            if abs(self.root.winfo_width() - old_width) > 20:
                job = getattr(self, "quick_layout_job", None)
                if job:
                    try:
                        self.root.after_cancel(job)
                    except tk.TclError:
                        pass
                self.quick_layout_job = self.root.after_idle(self.refresh_quick_rail)
            else:
                self.position_quick_rail()

    def watch_edge(self):
        if not self.closing and hasattr(self, "edge_controller"):
            self.edge_controller.check()

    def detect_docked_edge(self, x: int, y: int, width: int,
                           screen_width: int) -> Optional[str]:
        """兼容旧调用；实际运行使用当前显示器工作区。"""
        display = DisplayArea(0, 0, 0, screen_width, 100000,
                              0, 0, screen_width, 100000, True)
        return detect_docked_edge((x, y, width, 1), display, self.EDGE_GAP)

    def hide_to_edge(self, edge: str):
        if hasattr(self, "edge_controller"):
            self.edge_controller.hide(edge)

    def reveal_from_edge(self):
        if hasattr(self, "edge_controller"):
            self.edge_controller.reveal()

    def on_close(self):
        self.reveal_from_edge()
        self.flush_save()
        self.store.settings["geometry"] = self.root.geometry()
        self.store.save()
        self.root.withdraw()
        self.stop_all_quick_pulses()
        self.quick_rail.withdraw()
        self.status_var.set("轻笺正在系统托盘运行")

    def exit_app(self):
        self.exiting = True
        self.closing = True
        if self.voice_recorder:
            try:
                self.voice_recorder.stop()
            except Exception:
                pass
            self.voice_recorder = None
        self.llama_runtime.stop_owned()
        self.reveal_from_edge()
        self.flush_save()
        if self.root.state() == "normal":
            self.store.settings["geometry"] = self.root.geometry()
            self.store.settings["window_bounds"] = list(window_bounds(self.root))
            if self.main_dpi_scaler and self.main_dpi_scaler.current_dpi:
                self.store.settings["window_dpi"] = self.main_dpi_scaler.current_dpi
        self.store.save()
        self.tray.stop()
        if self.instance_guard:
            self.instance_guard.close()
        self.root.destroy()

    def restart_app(self):
        if self.exiting:
            return
        self.exiting = True
        self.closing = True
        if self.voice_recorder:
            try:
                self.voice_recorder.stop()
            except Exception:
                pass
            self.voice_recorder = None
        self.llama_runtime.stop_owned()
        self.reveal_from_edge()
        self.flush_save()
        if self.root.state() == "normal":
            self.store.settings["geometry"] = self.root.geometry()
            self.store.settings["window_bounds"] = list(window_bounds(self.root))
            if self.main_dpi_scaler and self.main_dpi_scaler.current_dpi:
                self.store.settings["window_dpi"] = self.main_dpi_scaler.current_dpi
        self.store.save()
        self.tray.stop()
        if self.instance_guard:
            self.instance_guard.close()
        script = Path(__file__).resolve()
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent),
                             close_fds=True)
        except OSError as exc:
            self.exiting = False
            self.closing = False
            messagebox.showerror("刷新轻笺", f"无法重新启动轻笺：{exc}", parent=self.root)
            return
        self.root.destroy()


if __name__ == "__main__":
    enable_per_monitor_dpi_awareness()
    guard = SingleInstance()
    if not guard.is_primary:
        guard.signal_existing()
        guard.close()
    else:
        window = tk.Tk()
        StickyNotesApp(window, guard)
        window.mainloop()
