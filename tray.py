import ctypes
import queue
import threading
from ctypes import wintypes


WM_APP = 0x8000
WM_TRAY = WM_APP + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
TPM_RIGHTBUTTON = 0x0002


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


class TrayManager:
    MENU = ((1001, "显示轻笺", "show"), (1007, "刷新轻笺", "restart"),
            (1002, "新建提醒", "new_reminder"),
            (1003, "新建便签", "new_sticky"), (1004, "新建笔记", "new_journal"),
            (1005, "暂停/恢复提醒", "toggle_pause"), (1006, "退出", "exit"))

    def __init__(self):
        self.events = queue.Queue()
        self.hwnd = None
        self.thread = None
        self._wndproc_ref = WNDPROC(self._wndproc)
        self._nid = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _run(self):
        user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.LoadIconW.restype = wintypes.HICON
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        class_name = "LightNoteTrayWindow"
        instance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = instance
        wc.lpszClassName = class_name
        wc.hIcon = user32.LoadIconW(None, 32512)
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, class_name, "轻笺托盘", 0,
                                           0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd, nid.uID = self.hwnd, 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = user32.LoadIconW(None, 32512)
        nid.szTip = "轻笺"
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        user32 = ctypes.windll.user32
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONDBLCLK:
                self.events.put("show")
            elif lparam == WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if msg == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            action = next((action for item_id, _label, action in self.MENU
                           if item_id == command_id), None)
            if action:
                self.events.put(action)
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self._nid:
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd):
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        for item_id, label, _action in self.MENU:
            user32.AppendMenuW(menu, 0, item_id, label)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, point.x, point.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
