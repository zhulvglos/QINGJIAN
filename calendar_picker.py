import calendar
import tkinter as tk
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from calendar_service import LUNAR_DAYS, LUNAR_MONTHS, lunar_month, month_grid


WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")
WEEKDAY_LONG = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class CalendarPicker:
    def __init__(self, parent, colors: Dict[str, str], initial: Optional[datetime] = None,
                 reminders: Optional[List[Dict]] = None, title: str = "选择提醒时间"):
        self.parent = parent
        self.colors = colors
        self.initial = initial or (datetime.now() + timedelta(hours=1))
        self.selected = self.initial.date()
        self.view_year = self.selected.year
        self.view_month = self.selected.month
        self.reminders = reminders or []
        self.result = None
        self.days = []

        c = colors
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("600x650")
        self.dialog.minsize(520, 590)
        self.dialog.configure(bg=c["bg"])
        self.dialog.transient(parent)
        self.dialog.attributes("-topmost", bool(parent.attributes("-topmost")))
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)

        self.selected_title = tk.StringVar()
        self.selected_lunar = tk.StringVar()
        tk.Label(self.dialog, textvariable=self.selected_title, bg=c["bg"], fg=c["text"],
                 anchor="w", font=("Microsoft YaHei UI", 15, "bold")).pack(fill="x", padx=20, pady=(16, 2))
        tk.Label(self.dialog, textvariable=self.selected_lunar, bg=c["bg"], fg=c["muted"],
                 anchor="w", font=("Microsoft YaHei UI", 10)).pack(fill="x", padx=20, pady=(0, 10))

        month_bar = tk.Frame(self.dialog, bg=c["panel"], padx=12, pady=7)
        month_bar.pack(fill="x", padx=14)
        self.month_var = tk.StringVar()
        tk.Label(month_bar, textvariable=self.month_var, bg=c["panel"], fg=c["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self._bar_button(month_bar, "今天", self.go_today).pack(side="right", padx=(8, 0))
        self._bar_button(month_bar, "›", self.next_month).pack(side="right")
        self._bar_button(month_bar, "‹", self.previous_month).pack(side="right")

        weekdays = tk.Frame(self.dialog, bg=c["bg"])
        weekdays.pack(fill="x", padx=16, pady=(9, 0))
        for index, label in enumerate(WEEKDAYS):
            weekdays.grid_columnconfigure(index, weight=1)
            tk.Label(weekdays, text=label, bg=c["bg"], fg=c["muted"],
                     font=("Microsoft YaHei UI", 9)).grid(row=0, column=index, sticky="ew")

        self.canvas = tk.Canvas(self.dialog, bg=c["bg"], highlightthickness=0, bd=0, height=365)
        self.canvas.pack(fill="both", expand=True, padx=14)
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        self.canvas.bind("<Button-1>", self.choose_day)
        self.canvas.bind("<MouseWheel>", self.on_wheel)

        self.day_reminders = tk.StringVar()
        tk.Label(self.dialog, textvariable=self.day_reminders, bg=c["bg"], fg=c["muted"],
                 anchor="w", wraplength=550).pack(fill="x", padx=20, pady=(1, 6))

        bottom = tk.Frame(self.dialog, bg=c["panel"], padx=14, pady=10)
        bottom.pack(fill="x")
        tk.Label(bottom, text="提醒时间", bg=c["panel"], fg=c["text"]).pack(side="left")
        self.hour_var = tk.StringVar(value=f"{self.initial.hour:02d}")
        self.minute_var = tk.StringVar(value=f"{self.initial.minute:02d}")
        spin_args = dict(width=3, justify="center", bg=c["input"], fg=c["text"],
                         buttonbackground=c["panel"], relief="flat", font=("Microsoft YaHei UI", 10))
        tk.Spinbox(bottom, from_=0, to=23, wrap=True, textvariable=self.hour_var,
                   format="%02.0f", **spin_args).pack(side="left", padx=(8, 2), ipady=3)
        tk.Label(bottom, text=":", bg=c["panel"], fg=c["text"]).pack(side="left")
        tk.Spinbox(bottom, from_=0, to=59, wrap=True, textvariable=self.minute_var,
                   format="%02.0f", **spin_args).pack(side="left", padx=(2, 8), ipady=3)
        tk.Button(bottom, text="取消", command=self.cancel, bg=c["panel"], fg=c["text"],
                  activebackground=c["bg"], relief="flat", padx=16, pady=5).pack(side="right")
        tk.Button(bottom, text="确定", command=self.confirm, bg=c["accent"], fg="white",
                  activebackground=c["accent"], relief="flat", padx=18, pady=5).pack(side="right", padx=8)

        self.dialog.bind("<Escape>", lambda _e: self.cancel())
        self.dialog.bind("<Return>", lambda _e: self.confirm())
        self.refresh()

    def _bar_button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=self.colors["panel"],
                         fg=self.colors["text"], activebackground=self.colors["accent"],
                         activeforeground="white", relief="flat", bd=0, padx=9)

    def show(self) -> Optional[str]:
        self.dialog.grab_set()
        self.dialog.wait_window()
        return self.result

    def refresh(self):
        self.days = month_grid(self.view_year, self.view_month)
        self.lunar_data = lunar_month(self.view_year, self.view_month)
        self.month_var.set(f"{self.view_year}年{self.view_month}月")
        self.update_selected_info()
        self.draw()

    def draw(self):
        if not self.days:
            return
        self.canvas.delete("all")
        width = max(350, self.canvas.winfo_width())
        height = max(300, self.canvas.winfo_height())
        cell_w, cell_h = width / 7, height / 6
        c = self.colors
        today = date.today()
        counts = self._reminder_counts()
        for index, day in enumerate(self.days):
            row, col = divmod(index, 7)
            cx, top = cell_w * (col + 0.5), cell_h * row
            active_month = day.month == self.view_month
            info = self.lunar_data.get(day.isoformat(), {})
            if day == self.selected:
                radius = min(25, cell_h / 2 - 4)
                self.canvas.create_oval(cx - radius, top + 3, cx + radius, top + 3 + radius * 2,
                                        fill=c["accent"], outline="")
            elif day == today:
                radius = min(24, cell_h / 2 - 5)
                self.canvas.create_oval(cx - radius, top + 4, cx + radius, top + 4 + radius * 2,
                                        outline=c["accent"], width=2)
            text_color = "white" if day == self.selected else c["text"] if active_month else c["muted"]
            self.canvas.create_text(cx, top + 18, text=str(day.day), fill=text_color,
                                    font=("Microsoft YaHei UI", 11, "bold" if day == self.selected else "normal"))
            lunar_color = "white" if day == self.selected else c["accent"] if info.get("solar_term") or info.get("festival") else c["muted"]
            self.canvas.create_text(cx, top + 39, text=info.get("label", ""), fill=lunar_color,
                                    font=("Microsoft YaHei UI", 8))
            holiday = info.get("holiday")
            if holiday:
                badge = "休" if holiday["type"] == "holiday" else "班"
                badge_color = "#d9534f" if holiday["type"] == "holiday" else "#e69b35"
                self.canvas.create_text(cx + cell_w * 0.28, top + 10, text=badge,
                                        fill=badge_color, font=("Microsoft YaHei UI", 7, "bold"))
            if counts.get(day.isoformat()):
                self.canvas.create_oval(cx - 2, top + cell_h - 8, cx + 2, top + cell_h - 4,
                                        fill=c["accent"], outline="")

    def choose_day(self, event):
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        col = min(6, max(0, int(event.x / (width / 7))))
        row = min(5, max(0, int(event.y / (height / 6))))
        selected = self.days[row * 7 + col]
        self.selected = selected
        if selected.month != self.view_month:
            self.view_year, self.view_month = selected.year, selected.month
            self.refresh()
        else:
            self.update_selected_info()
            self.draw()

    def update_selected_info(self):
        info = self.lunar_data.get(self.selected.isoformat(), {})
        self.selected_title.set(f"{self.selected.month}月{self.selected.day}日，{WEEKDAY_LONG[self.selected.weekday()]}")
        lunar_text = ""
        if info.get("month") and info.get("day"):
            lunar_text = ("农历" + ("闰" if info.get("leap") else "") +
                          LUNAR_MONTHS[info["month"]] + LUNAR_DAYS[info["day"]])
        extras = [x for x in (info.get("solar_term"), info.get("festival")) if x]
        holiday = info.get("holiday")
        if holiday:
            extras.append(holiday["name"] + ("放假" if holiday["type"] == "holiday" else "补班"))
        self.selected_lunar.set(" · ".join([lunar_text] + extras))
        day_items = [r.get("title", "未命名提醒") for r in self.reminders
                     if r.get("remind_at", "").startswith(self.selected.isoformat())]
        self.day_reminders.set("当天提醒：" + "、".join(day_items) if day_items else "当天暂无提醒")

    def _reminder_counts(self):
        result = {}
        for reminder in self.reminders:
            day = reminder.get("remind_at", "")[:10]
            if day:
                result[day] = result.get(day, 0) + 1
        return result

    def previous_month(self):
        self.view_month -= 1
        if self.view_month == 0:
            self.view_year -= 1
            self.view_month = 12
        self.refresh()

    def next_month(self):
        self.view_month += 1
        if self.view_month == 13:
            self.view_year += 1
            self.view_month = 1
        self.refresh()

    def go_today(self):
        self.selected = date.today()
        self.view_year, self.view_month = self.selected.year, self.selected.month
        self.refresh()

    def on_wheel(self, event):
        self.previous_month() if event.delta > 0 else self.next_month()
        return "break"

    def confirm(self):
        try:
            hour = min(23, max(0, int(self.hour_var.get())))
            minute = min(59, max(0, int(self.minute_var.get())))
        except ValueError:
            return
        self.result = f"{self.selected.isoformat()} {hour:02d}:{minute:02d}"
        self.dialog.destroy()

    def cancel(self):
        self.result = None
        self.dialog.destroy()
