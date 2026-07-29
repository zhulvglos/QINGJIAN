import ctypes
from dataclasses import dataclass
from ctypes import wintypes


@dataclass(frozen=True)
class DisplayArea:
    handle: int
    left: int
    top: int
    right: int
    bottom: int
    work_left: int
    work_top: int
    work_right: int
    work_bottom: int
    primary: bool = False
    dpi: int = 96

    @property
    def work(self):
        return (self.work_left, self.work_top, self.work_right, self.work_bottom)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def enable_per_monitor_dpi_awareness():
    """在创建首个 Tk 窗口前启用 Windows Per-Monitor V2 DPI。"""
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):
            return True
    except (AttributeError, OSError):
        pass
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, -2147024891)
    except (AttributeError, OSError):
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except (AttributeError, OSError):
            return False


def enumerate_displays():
    displays = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def collect(handle, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            monitor, work = info.rcMonitor, info.rcWork
            dpi = monitor_dpi(handle)
            displays.append(DisplayArea(
                int(handle), monitor.left, monitor.top, monitor.right, monitor.bottom,
                work.left, work.top, work.right, work.bottom,
                bool(info.dwFlags & 1), dpi))
        return True

    callback = callback_type(collect)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    if not displays:
        width = ctypes.windll.user32.GetSystemMetrics(0)
        height = ctypes.windll.user32.GetSystemMetrics(1)
        displays.append(DisplayArea(0, 0, 0, width, height, 0, 0, width, height, True))
    return displays


def monitor_dpi(handle):
    try:
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        result = ctypes.windll.shcore.GetDpiForMonitor(
            handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if result == 0 and dpi_x.value:
            return int(dpi_x.value)
    except (AttributeError, OSError):
        pass
    return 96


def display_signature(displays):
    return tuple(sorted((item.handle, item.left, item.top, item.right, item.bottom,
                         item.work_left, item.work_top, item.work_right, item.work_bottom,
                         item.dpi)
                        for item in displays))


def intersection_area(bounds, display):
    x, y, width, height = bounds
    return max(0, min(x + width, display.right) - max(x, display.left)) * max(
        0, min(y + height, display.bottom) - max(y, display.top))


def sufficiently_visible(bounds, display, minimum=80):
    x, y, width, height = bounds
    visible_width = max(0, min(x + width, display.right) - max(x, display.left))
    visible_height = max(0, min(y + height, display.bottom) - max(y, display.top))
    return (visible_width >= min(minimum, width) and
            visible_height >= min(minimum, height))


def display_for_bounds(bounds, displays):
    if not displays:
        return None
    areas = [(intersection_area(bounds, display), display) for display in displays]
    best_area, best = max(areas, key=lambda item: item[0])
    if best_area:
        return best
    x, y, width, height = bounds
    center_x, center_y = x + width / 2, y + height / 2
    def distance(display):
        display_x = (display.left + display.right) / 2
        display_y = (display.top + display.bottom) / 2
        return (center_x - display_x) ** 2 + (center_y - display_y) ** 2

    return min(displays, key=distance)


def display_for_handle(handle, displays):
    return next((item for item in displays if item.handle == handle), None)


def detect_docked_edge(bounds, display, gap):
    x, y, width, height = bounds
    if x <= display.work_left + gap and x + width > display.work_left:
        return "left"
    if x + width >= display.work_right - gap and x < display.work_right:
        return "right"
    if y <= display.work_top + gap and y + height > display.work_top:
        return "top"
    return None


def hidden_position(edge, bounds, display, visible_size):
    x, y, width, height = bounds
    if edge == "left":
        return display.work_left - width + visible_size, y
    if edge == "right":
        return display.work_right - visible_size, y
    return x, display.work_top - height + visible_size


def revealed_position(edge, bounds, display):
    x, y, width, height = bounds
    if edge == "left":
        x = display.work_left
    elif edge == "right":
        x = display.work_right - width
    else:
        y = display.work_top
    x = min(max(x, display.work_left), max(display.work_left, display.work_right - width))
    y = min(max(y, display.work_top), max(display.work_top, display.work_bottom - height))
    return x, y


def ensure_visible_position(bounds, displays):
    """显示器移除后，把窗口完整放入距离最近的可用工作区。"""
    display = display_for_bounds(bounds, displays)
    if not display:
        return bounds[0], bounds[1]
    if any(sufficiently_visible(bounds, item) for item in displays):
        return bounds[0], bounds[1]
    x, y, width, height = bounds
    x = min(max(x, display.work_left), max(display.work_left, display.work_right - width))
    y = min(max(y, display.work_top), max(display.work_top, display.work_bottom - height))
    return x, y


def top_level_handle(widget):
    widget.update_idletasks()
    child = int(widget.winfo_id())
    user32 = ctypes.windll.user32
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    parent = user32.GetParent(child)
    return parent or child


def set_window_position(widget, x, y):
    """使用虚拟桌面绝对坐标，正确支持主屏左侧的负坐标。"""
    hwnd = top_level_handle(widget)
    user32 = ctypes.windll.user32
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.UINT]
    user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0,
                        0x0001 | 0x0004 | 0x0010)


def set_window_bounds(widget, x, y, width, height):
    widget.geometry(f"{max(1, int(width))}x{max(1, int(height))}")
    widget.update_idletasks()
    set_window_position(widget, x, y)


def window_bounds(widget):
    widget.update_idletasks()
    return (widget.winfo_x(), widget.winfo_y(),
            widget.winfo_width(), widget.winfo_height())


def window_client_size(widget):
    widget.update_idletasks()
    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    if user32.GetClientRect(int(widget.winfo_id()), ctypes.byref(rect)):
        return max(1, rect.right - rect.left), max(1, rect.bottom - rect.top)
    return widget.winfo_width(), widget.winfo_height()


class EdgeHideController:
    def __init__(self, widget, enabled, gap=12, visible_size=7, blocked=None,
                 on_hide=None, on_reveal=None, on_inside=None,
                 on_displays_changed=None, on_display_enter=None, interval=180):
        self.widget = widget
        self.enabled = enabled
        self.gap = gap
        self.visible_size = visible_size
        self.blocked = blocked or (lambda: False)
        self.on_hide = on_hide
        self.on_reveal = on_reveal
        self.on_inside = on_inside
        self.on_displays_changed = on_displays_changed
        self.on_display_enter = on_display_enter
        self.interval = interval
        self.hidden_edge = None
        self.hidden_display_handle = None
        self.displays = enumerate_displays()
        self.signature = display_signature(self.displays)
        self.current_display_handle = None
        self.job = None
        self.stopped = False

    def start(self):
        self.stopped = False
        self.job = self.widget.after(self.interval, self._tick)

    def stop(self, reveal=True):
        self.stopped = True
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if reveal:
            self.reveal()

    def _tick(self):
        self.job = None
        if self.stopped:
            return
        try:
            if not self.widget.winfo_exists():
                return
            self.check()
            self.job = self.widget.after(self.interval, self._tick)
        except Exception:
            if not self.stopped:
                try:
                    self.job = self.widget.after(self.interval, self._tick)
                except Exception:
                    pass

    def check(self):
        latest = enumerate_displays()
        latest_signature = display_signature(latest)
        if latest_signature != self.signature:
            self._handle_display_change(latest)
            self.signature = latest_signature
        self.displays = latest
        if self.widget.state() != "normal":
            return
        bounds = window_bounds(self.widget)
        current_display = display_for_bounds(bounds, self.displays)
        if current_display and current_display.handle != self.current_display_handle:
            self.current_display_handle = current_display.handle
            if self.on_display_enter:
                self.on_display_enter(current_display)
            bounds = window_bounds(self.widget)
        pointer_x, pointer_y = self.widget.winfo_pointerx(), self.widget.winfo_pointery()
        inside = (bounds[0] <= pointer_x <= bounds[0] + bounds[2] and
                  bounds[1] <= pointer_y <= bounds[1] + bounds[3])
        if self.on_inside:
            self.on_inside(inside)
        if self.hidden_edge:
            if not self.enabled() or inside:
                self.reveal()
            return
        if self.enabled() and not self.blocked() and not inside:
            display = display_for_bounds(bounds, self.displays)
            if display:
                edge = detect_docked_edge(bounds, display, self.gap)
                if edge:
                    self.hide(edge, display)

    def _handle_display_change(self, displays):
        if self.hidden_edge:
            self.displays = displays
            self.reveal()
        bounds = window_bounds(self.widget)
        x, y = ensure_visible_position(bounds, displays)
        if (x, y) != bounds[:2]:
            set_window_position(self.widget, x, y)
        if self.on_displays_changed:
            self.on_displays_changed(displays)

    def hide(self, edge, display=None):
        if self.hidden_edge:
            return
        bounds = window_bounds(self.widget)
        display = display or display_for_bounds(bounds, self.displays)
        if not display:
            return
        self.hidden_edge = edge
        self.hidden_display_handle = display.handle
        x, y = hidden_position(edge, bounds, display, self.visible_size)
        if self.on_hide:
            self.on_hide(edge)
        set_window_position(self.widget, x, y)

    def reveal(self):
        if not self.hidden_edge:
            return
        edge = self.hidden_edge
        bounds = window_bounds(self.widget)
        display = display_for_handle(self.hidden_display_handle, self.displays)
        if not display:
            display = display_for_bounds(bounds, self.displays)
        if display:
            x, y = revealed_position(edge, bounds, display)
        self.hidden_edge = None
        self.hidden_display_handle = None
        if self.on_reveal:
            self.on_reveal()
        if display:
            set_window_position(self.widget, x, y)
