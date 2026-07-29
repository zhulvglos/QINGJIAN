import ctypes


ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0


class SingleInstance:
    MUTEX_NAME = "Local\\LightNote.SingleInstance.v1"
    EVENT_NAME = "Local\\LightNote.ShowWindow.v1"

    def __init__(self):
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateEventW.restype = ctypes.c_void_p
        self.mutex = kernel32.CreateMutexW(None, False, self.MUTEX_NAME)
        self.is_primary = kernel32.GetLastError() != ERROR_ALREADY_EXISTS
        self.event = kernel32.CreateEventW(None, False, False, self.EVENT_NAME) if self.is_primary else None

    def signal_existing(self):
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = ctypes.c_void_p
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, self.EVENT_NAME)
        if handle:
            kernel32.SetEvent(handle)
            kernel32.CloseHandle(handle)

    def consume_show_request(self) -> bool:
        if not self.event:
            return False
        return ctypes.windll.kernel32.WaitForSingleObject(self.event, 0) == WAIT_OBJECT_0

    def close(self):
        kernel32 = ctypes.windll.kernel32
        for handle in (self.event, self.mutex):
            if handle:
                kernel32.CloseHandle(handle)
        self.event = self.mutex = None
