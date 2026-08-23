import base64
import html
import os
import subprocess
import sys
import ctypes
from ctypes import wintypes
from pathlib import Path


AUTOSTART_NAME = "LightNote"
CREDENTIAL_TARGET = "LightNote.AI.APIKey"
CREDENTIAL_TARGETS = {
    "step_plan": CREDENTIAL_TARGET,
    "llama_cpp": "LightNote.AI.APIKey.llama_cpp",
    "custom": "LightNote.AI.APIKey.custom",
}


def _credential_target(provider: str = "step_plan") -> str:
    return CREDENTIAL_TARGETS.get(provider, CREDENTIAL_TARGETS["custom"])


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def save_ai_token(token: str, provider: str = "step_plan") -> bool:
    """将Token保存到当前用户的Windows凭据管理器。"""
    token = token.strip()
    if not token or os.name != "nt":
        return False
    try:
        encoded = token.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _CREDENTIALW()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = _credential_target(provider)
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "LightNote"
        return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0))
    except (AttributeError, OSError, ValueError):
        return False


def load_ai_token(provider: str = "step_plan") -> str:
    if os.name != "nt":
        return ""
    pointer = ctypes.POINTER(_CREDENTIALW)()
    try:
        if not ctypes.windll.advapi32.CredReadW(
                _credential_target(provider), 1, 0, ctypes.byref(pointer)):
            return ""
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    except (AttributeError, OSError, ValueError, UnicodeDecodeError):
        return ""
    finally:
        if pointer:
            try:
                ctypes.windll.advapi32.CredFree(pointer)
            except (AttributeError, OSError):
                pass


def send_windows_notification(title: str, message: str) -> bool:
    title = html.escape(title[:80])
    message = html.escape(message[:240])
    script = f"""
$ErrorActionPreference='Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml=New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{message}</text></binding></visual></toast>')
$toast=New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('轻笺').Show($toast)
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
        return True
    except (OSError, ImportError):
        return False


def set_autostart(enabled: bool, main_file: Path) -> bool:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                command = f'"{pythonw}" "{Path(main_file).resolve()}"'
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except (OSError, ImportError):
        return False
