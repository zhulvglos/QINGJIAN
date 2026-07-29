import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from display_manager import set_window_bounds, window_bounds, window_client_size


class WindowDpiScaler:
    """在固定 Tk 点阵基准上，为单个顶层窗口应用独立 DPI 缩放。"""

    def __init__(self, window, user_factor=1.0, base_min_size=None):
        self.window = window
        self.user_factor = float(user_factor)
        self.base_min_size = base_min_size
        self.current_dpi = None
        self._font_specs = {}
        self._tag_font_specs = {}
        self._manager_specs = {}
        self._option_specs = {}
        self._font_cache = {}
        self._style = ttk.Style(window)
        self._style_names = {}
        self._font_refs = []
        self.capture_tree(window)

    def capture_tree(self, root):
        for widget in self._walk(root):
            self._capture_widget(widget)

    def _walk(self, root):
        yield root
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel) and child is not root:
                continue
            yield from self._walk(child)

    @staticmethod
    def _font_spec(widget, value):
        try:
            actual = tkfont.Font(root=widget, font=value).actual()
        except tk.TclError:
            return None
        size = abs(int(actual.get("size") or 0))
        if not size:
            return None
        return {"family": actual.get("family") or "Microsoft YaHei UI",
                "size": size, "weight": actual.get("weight", "normal"),
                "slant": actual.get("slant", "roman"),
                "underline": actual.get("underline", 0),
                "overstrike": actual.get("overstrike", 0)}

    def _capture_widget(self, widget):
        try:
            keys = widget.keys()
        except (AttributeError, tk.TclError):
            keys = ()
        if "font" in keys:
            spec = self._font_spec(widget, widget.cget("font"))
            if spec:
                self._font_specs[widget] = ("direct", spec)
        elif isinstance(widget, ttk.Widget):
            base_style = widget.cget("style") or widget.winfo_class()
            font_value = self._style.lookup(base_style, "font") or "TkDefaultFont"
            spec = self._font_spec(widget, font_value)
            if spec:
                self._font_specs[widget] = ("style", spec)
                self._style_names[widget] = base_style
        if isinstance(widget, tk.Text):
            for tag in widget.tag_names():
                value = widget.tag_cget(tag, "font")
                if value:
                    spec = self._font_spec(widget, value)
                    if spec:
                        self._tag_font_specs[(widget, tag)] = spec
        manager = widget.winfo_manager()
        try:
            if manager == "pack":
                info = widget.pack_info()
                self._manager_specs[widget] = ("pack", {
                    key: info[key] for key in ("padx", "pady", "ipadx", "ipady")
                    if key in info})
            elif manager == "grid":
                info = widget.grid_info()
                self._manager_specs[widget] = ("grid", {
                    key: info[key] for key in ("padx", "pady", "ipadx", "ipady")
                    if key in info})
            elif manager == "place":
                info = widget.place_info()
                self._manager_specs[widget] = ("place", {
                    key: info[key] for key in ("x", "y", "width", "height")
                    if key in info and str(info[key])})
        except tk.TclError:
            pass
        options = {}
        if isinstance(widget, (tk.Frame, tk.LabelFrame)):
            for key in ("padx", "pady"):
                if key in keys:
                    options[key] = widget.cget(key)
        if isinstance(widget, tk.Label) and "wraplength" in keys:
            value = widget.cget("wraplength")
            if value:
                options["wraplength"] = value
        if options:
            self._option_specs[widget] = options

    @staticmethod
    def _scale_value(value, factor):
        if isinstance(value, (tuple, list)):
            return tuple(round(float(item) * factor) for item in value)
        text = str(value).strip()
        if not text:
            return value
        if " " in text:
            try:
                return tuple(round(float(item) * factor) for item in text.split())
            except ValueError:
                return value
        try:
            return round(float(text) * factor)
        except (TypeError, ValueError):
            return value

    def _scaled_font(self, widget, spec, font_factor):
        key = (spec["family"], max(1, round(spec["size"] * font_factor)),
               spec["weight"], spec["slant"], spec["underline"], spec["overstrike"])
        if key not in self._font_cache:
            self._font_cache[key] = tkfont.Font(
                root=widget, family=key[0], size=key[1], weight=key[2],
                slant=key[3], underline=key[4], overstrike=key[5])
            self._font_refs.append(self._font_cache[key])
        return self._font_cache[key]

    def apply(self, dpi, resize=True, previous_dpi=None):
        dpi = max(72, int(dpi or 96))
        old_dpi = int(previous_dpi or self.current_dpi or dpi)
        geometry_factor = dpi / 96
        font_factor = geometry_factor * self.user_factor
        if resize and old_dpi != dpi:
            x, y = window_bounds(self.window)[:2]
            width, height = window_client_size(self.window)
            ratio = dpi / old_dpi
            set_window_bounds(self.window, x, y, round(width * ratio), round(height * ratio))
        if self.base_min_size:
            self.window.minsize(round(self.base_min_size[0] * geometry_factor),
                                round(self.base_min_size[1] * geometry_factor))
        for widget, (mode, spec) in list(self._font_specs.items()):
            try:
                font = self._scaled_font(widget, spec, font_factor)
                if mode == "direct":
                    widget.configure(font=font)
                else:
                    base_style = self._style_names[widget]
                    style_name = f"Dpi{id(self)}.{base_style}"
                    self._style.configure(style_name, font=font)
                    widget.configure(style=style_name)
            except (tk.TclError, KeyError):
                continue
        for (widget, tag), spec in list(self._tag_font_specs.items()):
            try:
                widget.tag_configure(tag, font=self._scaled_font(widget, spec, font_factor))
            except tk.TclError:
                continue
        for widget, (manager, values) in list(self._manager_specs.items()):
            scaled = {key: self._scale_value(value, geometry_factor)
                      for key, value in values.items()}
            try:
                if manager == "pack":
                    widget.pack_configure(**scaled)
                elif manager == "grid":
                    widget.grid_configure(**scaled)
                else:
                    widget.place_configure(**scaled)
            except tk.TclError:
                continue
        for widget, values in list(self._option_specs.items()):
            try:
                widget.configure(**{key: self._scale_value(value, geometry_factor)
                                    for key, value in values.items()})
            except tk.TclError:
                continue
        self.current_dpi = dpi
        self.window.update_idletasks()
