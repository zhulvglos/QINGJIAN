"""轻笺 (LightNote) 调色板工具与轻量现代控件。

- 颜色算法：HSL 转换、WCAG AA 对比度、调和派生
- 控件：ModernButton（圆角 + hover + click 动画）、ModernEntry（focus ring）、ModernToggle
- 图片取色：image_palette_v2（5 点调色板 + 自动 accent）

所有控件都通过 `apply_palette(palette)` 响应主题切换，主程序在
`StickyNotesApp.apply_theme` 中集中调用。
"""

from __future__ import annotations

import colorsys
import tkinter as tk
from collections import Counter
from typing import Dict, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# 基础颜色工具
# ---------------------------------------------------------------------------

def parse_hex(value: str) -> RGB:
    """将 `#rrggbb` 或 `#rgb` 解析为 (r, g, b)。"""
    s = value.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError(f"无法解析颜色：{value!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def to_hex(rgb: RGB) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def with_alpha(hex_color: str, alpha: float) -> str:
    """图片皮肤面板半透明：通过 PIL 预合成实现（Tkinter 自身不支持 8 位色）。当前仅做透传。"""
    return hex_color


def composite_skin_overlay(image, panel_color: str, alpha: float = 0.18) -> "Image.Image":
    """在图片上叠加一层 panel_color 的半透明白色遮罩，模拟 QQ 聊天背景的半透明面板。

    alpha=0.18 → 遮罩较薄，背景图清晰可辨；alpha=0.30 → 稍浓，适合文字密集区。
    返回处理后的 RGB Image，可直接用于 PhotoImage。
    """
    from PIL import Image as PILImage
    rgb = image.convert("RGB")
    overlay = PILImage.new("RGBA", rgb.size, panel_color + f"{round(alpha * 255):02x}")
    result = PILImage.alpha_composite(rgb.convert("RGBA"), overlay)
    return result.convert("RGB")


def blend(c1: RGB, c2: RGB, ratio: float) -> RGB:
    """线性混合两个颜色，ratio=0 全部为 c1，ratio=1 全部为 c2。"""
    ratio = max(0.0, min(1.0, ratio))
    return tuple(round(a + (b - a) * ratio) for a, b in zip(c1, c2))


def hex_blend(hex1: str, hex2: str, ratio: float) -> str:
    return to_hex(blend(parse_hex(hex1), parse_hex(hex2), ratio))


def relative_luminance(rgb: RGB) -> float:
    """WCAG 2.1 相对亮度公式。"""
    def chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(c1: RGB, c2: RGB) -> float:
    """两个颜色之间的对比度（1.0 ~ 21.0），WCAG AA 文字要求 4.5:1。"""
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def best_text_color(bg: RGB, prefer_dark: bool = False) -> str:
    """根据背景颜色自动选择文字色（黑或白），保证 WCAG AA。"""
    light_ratio = contrast_ratio(bg, (255, 255, 255))
    dark_ratio = contrast_ratio(bg, (0, 0, 0))
    if prefer_dark:
        return "#1a1a1a" if dark_ratio >= 4.5 else ("#ffffff" if light_ratio >= 4.5 else "#1a1a1a")
    return "#ffffff" if light_ratio >= dark_ratio else "#1a1a1a"


def rgb_to_hls(rgb: RGB) -> Tuple[float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    return colorsys.rgb_to_hls(r, g, b)


def hls_to_rgb(h: float, l: float, s: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return round(r * 255), round(g * 255), round(b * 255)


def saturation(rgb: RGB) -> float:
    _, _, s = rgb_to_hls(rgb)
    return s


def luminance_bt601(rgb: RGB) -> float:
    """ITU-R BT.601 亮度（0-255），用于旧 image_skin_palette 兼容。"""
    r, g, b = rgb
    return (r * 299 + g * 587 + b * 114) / 1000


def lighten(rgb: RGB, amount: float) -> RGB:
    h, l, s = rgb_to_hls(rgb)
    return hls_to_rgb(h, min(1.0, l + amount), s)


def darken(rgb: RGB, amount: float) -> RGB:
    h, l, s = rgb_to_hls(rgb)
    return hls_to_rgb(h, max(0.0, l - amount), s)


def adjust_saturation(rgb: RGB, factor: float) -> RGB:
    h, l, s = rgb_to_hls(rgb)
    return hls_to_rgb(h, l, max(0.0, min(1.0, s * factor)))


def shade_for_background(bg: RGB) -> RGB:
    """根据背景明度返回对应的"次要色"，深色用浅灰、浅色用深灰。"""
    h, l, s = rgb_to_hls(bg)
    if l < 0.5:
        return hls_to_rgb(h, min(1.0, l + 0.4), s * 0.6)
    return hls_to_rgb(h, max(0.0, l - 0.4), s * 0.6)


# ---------------------------------------------------------------------------
# 图片取色算法
# ---------------------------------------------------------------------------

def extract_top_colors(image, k: int = 5) -> Sequence[RGB]:
    """用 median-cut 量化从图片中提取 k 个主色，按出现频次降序。"""
    small = image.resize((100, 100)).convert("RGB")
    # Pillow 9+ 用字符串方法名；老版本用 Image.MEDIANCUT 数字常量
    try:
        quant = small.quantize(colors=k, method="MEDIANCUT")
    except (TypeError, ValueError, AttributeError):
        try:
            from PIL import Image as _Img
            quant = small.quantize(colors=k, method=_Img.Quantize.MEDIANCUT)
        except Exception:
            quant = small.quantize(colors=k)
    palette = quant.getpalette() or []
    counts = Counter(quant.getdata())
    out = []
    for index, _ in counts.most_common(k):
        base = index * 3
        if base + 3 > len(palette):
            continue
        out.append((palette[base], palette[base + 1], palette[base + 2]))
    return out or [(128, 128, 128)]


def image_palette_v2(image, accent_seed: Optional[RGB] = None) -> Dict[str, str]:
    """5 点调色板：背景取低饱和主色，accent 取高饱和主色或种子色。

    返回的字典键与 THEMES 兼容：bg / panel / input / accent / text / muted。
    """
    top5 = list(extract_top_colors(image, k=5))
    if not top5:
        return {
            "bg": "#3a3a3a", "panel": "#2a2a2a", "input": "#1f1f1f",
            "accent": "#58a6ff", "text": "#f0f0f0", "muted": "#888888",
        }

    bg = min(top5, key=lambda c: saturation(c) * 0.6 + abs(luminance_bt601(c) - 128) / 255 * 0.4)

    if accent_seed:
        accent = accent_seed
    else:
        accent = max(
            top5,
            key=lambda c: saturation(c) * 0.6 + (1 - abs(luminance_bt601(c) - 128) / 128) * 0.4,
        )
    # 保证 accent 与背景至少 3:1 对比度（WCAG UI 组件要求）
    if contrast_ratio(accent, bg) < 3.0:
        accent = adjust_saturation(accent, 1.6)
        accent = lighten(accent, 0.1) if rgb_to_hls(bg)[1] < 0.5 else darken(accent, 0.1)
    # 再次确保
    if contrast_ratio(accent, bg) < 3.0:
        accent = (255, 255, 255) if rgb_to_hls(bg)[1] < 0.5 else (40, 40, 40)

    bg_l = rgb_to_hls(bg)[1]
    panel_base = lighten(bg, 0.03) if bg_l < 0.5 else darken(bg, 0.03)
    input_base = lighten(bg, 0.01) if bg_l < 0.5 else darken(bg, 0.01)
    text = best_text_color(bg)
    muted = shade_for_background(bg)

    return {
        "bg": to_hex(bg),
        "panel": to_hex(panel_base),
        "input": to_hex(input_base),
        "accent": to_hex(accent),
        "text": text,
        "muted": to_hex(muted),
    }


def image_skin_palette_legacy(image) -> Dict[str, str]:
    """旧版取色函数（保留为兜底，新代码应使用 image_palette_v2）。"""
    sample = image.resize((80, 80)).quantize(colors=8).convert("RGB")
    colors = sample.getcolors(sample.width * sample.height) or []
    red, green, blue = max(colors, key=lambda item: item[0])[1]

    def mix(color, target, ratio):
        return tuple(round(value * (1 - ratio) + goal * ratio)
                     for value, goal in zip(color, target))

    def as_hex(color):
        return to_hex(color)

    luminance = (red * 299 + green * 587 + blue * 114) / 1000
    dark_text = luminance > 145
    base = (red, green, blue)
    return {
        "bg": as_hex(mix(base, (255, 255, 255) if dark_text else (0, 0, 0), 0.38)),
        "panel": as_hex(mix(base, (255, 255, 255) if dark_text else (0, 0, 0), 0.55)),
        "input": as_hex(mix(base, (255, 255, 255) if dark_text else (0, 0, 0), 0.25)),
        "accent": as_hex(mix(base, (40, 160, 255) if dark_text else (110, 205, 255), 0.48)),
        "text": "#1f2428" if dark_text else "#f7fbff",
        "muted": "#53616d" if dark_text else "#c6d5e1",
    }


# ---------------------------------------------------------------------------
# ModernButton —— 圆角 + 悬停 + 点击动画
# ---------------------------------------------------------------------------

_PALETTE_INSTANCES: list = []


def apply_palette_to_all(palette: Dict[str, str]) -> None:
    """所有已创建的 ModernButton / ModernEntry / ModernToggle 同步更新颜色。"""
    for inst in _PALETTE_INSTANCES:
        try:
            inst.apply_palette(palette)
        except tk.TclError:
            pass


class ModernButton(tk.Canvas):
    """圆角按钮：支持 primary / danger / ghost 三种语义，hover & click 动画。"""

    def __init__(self, parent, text: str = "", command=None,
                 style: str = "primary", width: int = 120, height: int = 32,
                 radius: int = 8, font=None, palette: Optional[Dict[str, str]] = None,
                 disabled: bool = False, attached_side: Optional[str] = None,
                 canvas_bg: Optional[str] = None, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, **kwargs)
        self._text = text
        self._command = command
        self._style = style
        self._bwidth = width
        self._bheight = height
        self._radius = radius
        self._attached_side = attached_side
        self._canvas_bg = canvas_bg
        self._font = font or ("Microsoft YaHei UI", 11)
        self._disabled = disabled
        self._pressed = False
        self._hover = False
        self._focused = False
        self._selected = False
        self._palette = palette or {
            "bg": "#f3e7a5", "panel": "#d9c978", "accent": "#c88b22",
            "text": "#2f2a20", "muted": "#665e4d", "input": "#fff8d5",
        }
        _PALETTE_INSTANCES.append(self)
        self.after(10, self._draw)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if "state" in kwargs:
            self._disabled = (str(kwargs.pop("state")) == "disabled")
            self._draw()
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self._text_var = None
            self._draw()
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        super().configure(cnf, **kwargs)

    def set_text(self, text: str) -> None:
        """动态更新按钮文字（替代 ttk.Button 的 textvariable 行为）。"""
        self._text = text
        self._text_var = None
        self._draw()

    def config(self, cnf=None, **kwargs):  # ttk.Button 兼容
        return self.configure(cnf, **kwargs)

    def state(self, states):  # ttk.Button 兼容
        """接受 ['selected'] / ['!selected'] 列表，切换 ghost 按钮的选中态。"""
        for s in states:
            if s == "selected":
                self._selected = True
            elif s == "!selected":
                self._selected = False
        self._draw()

    def _current_colors(self) -> Tuple[str, str, str, str]:
        c = self._palette
        accent = c.get("accent", "#888888")
        bg = c.get("panel", "#cccccc")
        text = c.get("text", "#000000")
        muted = c.get("muted", "#888888")
        if self._style == "primary":
            base_bg, base_fg = accent, "#ffffff"
        elif self._style == "danger":
            base_bg, base_fg = "#d94545", "#ffffff"
        elif self._style == "ghost":
            if getattr(self, "_selected", False):
                base_bg, base_fg = c.get("accent", "#ffffff"), "#ffffff"
            else:
                base_bg, base_fg = c.get("bg", "#ffffff"), text
        else:
            base_bg, base_fg = bg, text
        if self._disabled:
            base_bg = hex_blend(base_bg, c.get("bg", "#ffffff"), 0.5)
            base_fg = muted
        elif self._pressed:
            base_bg = hex_blend(base_bg, "#000000", 0.15)
        elif self._hover and self._style != "ghost":
            base_bg = hex_blend(base_bg, "#ffffff", 0.12)
        return base_bg, base_fg, accent, c.get("bg", "#ffffff")

    def _draw(self) -> None:
        self.delete("all")
        w, h, r = self._bwidth, self._bheight, self._radius
        bg, fg, accent, frame_bg = self._current_colors()
        self.configure(bg=self._canvas_bg or frame_bg)
        if r > min(w, h) // 2:
            r = min(w, h) // 2
        # 阴影（仅 primary 风格且非禁用）
        if self._style == "primary" and not self._disabled:
            shadow = hex_blend(bg, "#000000", 0.25)
            self._draw_button_shape(2, 3, w - 1, h, r, fill=shadow, outline="")
        self._draw_button_shape(0, 0, w - 3, h - 3, r, fill=bg, outline="")
        # focus 边框
        if getattr(self, "_focused", False):
            self._round_rect(1, 1, w - 4, h - 4, r, fill="", outline=accent, width=2)
        self.create_text((w - 3) / 2, (h - 3) / 2, text=self._text, fill=fg,
                         font=self._font, anchor="center")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kw)

    def _draw_button_shape(self, x1, y1, x2, y2, radius, **kwargs):
        """绘制普通四角圆角或贴边单侧圆角按钮。"""
        if self._attached_side != "right":
            return self._round_rect(x1, y1, x2, y2, radius, **kwargs)
        # 快捷标签靠近主窗口的一侧为直角，外侧左边保留上下圆角。
        radius = min(radius, max(1, int((y2 - y1) / 2)))
        fill = kwargs.pop("fill", "")
        outline = kwargs.pop("outline", "")
        self.create_rectangle(x1 + radius, y1, x2, y2,
                              fill=fill, outline=outline, **kwargs)
        self.create_rectangle(x1, y1 + radius, x1 + radius, y2 - radius,
                              fill=fill, outline=outline, **kwargs)
        self.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2,
                         fill=fill, outline=outline, **kwargs)
        self.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2,
                         fill=fill, outline=outline, **kwargs)

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self._draw()

    def _on_press(self, _event=None) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _event=None) -> None:
        if self._disabled:
            return
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and self._command:
            try:
                self._command()
            except Exception:
                pass

    def apply_palette(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self._draw()

    def set_focus_state(self, focused: bool) -> None:
        self._focused = focused
        self._draw()


# ---------------------------------------------------------------------------
# ModernEntry —— 带 focus ring 的输入框
# ---------------------------------------------------------------------------

class ModernEntry(tk.Frame):
    def __init__(self, parent, textvariable=None, palette: Optional[Dict[str, str]] = None,
                 font=None, show: str = "", **kwargs):
        super().__init__(parent, bd=0, highlightthickness=0, **kwargs)
        self._palette = palette or {
            "bg": "#ffffff", "panel": "#dddddd", "accent": "#3a8df0",
            "text": "#000000", "muted": "#888888", "input": "#ffffff",
        }
        self._font = font or ("Microsoft YaHei UI", 11)
        self._show = show
        self._focused = False
        self._border = tk.Frame(self, height=2, bg=self._palette.get("panel", "#dddddd"))
        self._border.pack(side="bottom", fill="x")
        self._entry = tk.Entry(
            self, textvariable=textvariable, relief="flat", bd=0,
            bg=self._palette.get("input", "#ffffff"),
            fg=self._palette.get("text", "#000000"),
            insertbackground=self._palette.get("text", "#000000"),
            font=self._font, show=show,
        )
        self._entry.pack(fill="x", padx=2, pady=(2, 4), ipady=2)
        self._entry.bind("<FocusIn>", self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)
        _PALETTE_INSTANCES.append(self)

    def _on_focus_in(self, _event=None) -> None:
        self._focused = True
        self._border.configure(bg=self._palette.get("accent", "#3a8df0"))

    def _on_focus_out(self, _event=None) -> None:
        self._focused = False
        self._border.configure(bg=self._palette.get("panel", "#dddddd"))

    def apply_palette(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self._entry.configure(
            bg=palette.get("input", "#ffffff"),
            fg=palette.get("text", "#000000"),
            insertbackground=palette.get("text", "#000000"),
        )
        self._border.configure(bg=self._palette.get("accent", "#3a8df0") if self._focused
                                else palette.get("panel", "#dddddd"))

    def focus_set(self):
        self._entry.focus_set()


# ---------------------------------------------------------------------------
# ModernToggle —— 圆角开关
# ---------------------------------------------------------------------------

class ModernToggle(tk.Canvas):
    def __init__(self, parent, variable: tk.BooleanVar, palette: Optional[Dict[str, str]] = None,
                 width: int = 42, height: int = 22, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, **kwargs)
        self._var = variable
        self._palette = palette or {
            "bg": "#ffffff", "panel": "#dddddd", "accent": "#3a8df0",
            "text": "#000000", "muted": "#888888", "input": "#ffffff",
        }
        self._bwidth, self._bheight = width, height
        self.bind("<Button-1>", self._toggle)
        _PALETTE_INSTANCES.append(self)
        self.after(10, self._draw)

    def _toggle(self, _event=None) -> None:
        self._var.set(not self._var.get())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        c = self._palette
        on = bool(self._var.get())
        track = c.get("accent", "#3a8df0") if on else c.get("panel", "#dddddd")
        self._round_rect(0, 0, self._bwidth, self._bheight, self._bheight // 2, fill=track, outline="")
        knob_r = (self._bheight - 4) // 2
        cx = self._bwidth - knob_r - 2 if on else knob_r + 2
        self.create_oval(cx - knob_r, 2, cx + knob_r, self._bheight - 2,
                         fill="#ffffff", outline="")

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kw)

    def apply_palette(self, palette: Dict[str, str]) -> None:
        self._palette = palette
        self._draw()


# 延迟导入 Image（避免 palette.py 单独被 import 时强制依赖 Pillow）
try:
    from PIL import Image  # noqa: F401
except ImportError:  # pragma: no cover
    Image = None
