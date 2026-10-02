"""마인크래프트 창 찾기 / 창만 캡처 / 창에만 입력 보내기 (Windows 전용).

백그라운드 모드: 마크 창이 다른 창 뒤에 있어도
  - 화면은 PrintWindow 로 마크 창 안쪽만 캡처
  - 우클릭/Shift 는 PostMessage 로 마크 창에만 보냄 (지금 쓰는 다른 창엔 영향 없음)
마크에서 F3+P (포커스 잃어도 일시정지 안 함) 필요, 창 최소화하면 안 됨.
"""
import ctypes
import sys
import time

import numpy as np

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # 64비트 윈도우에서 핸들/포인터가 잘리지 않게 인자 형식을 전부 지정
    def _sig(dll, name, res, *args):
        f = getattr(dll, name)
        f.restype, f.argtypes = res, list(args)

    H, HDC, HBMP, HGDI = wintypes.HWND, wintypes.HDC, wintypes.HBITMAP, wintypes.HGDIOBJ
    _sig(user32, "IsWindowVisible", wintypes.BOOL, H)
    _sig(user32, "GetWindowTextLengthW", ctypes.c_int, H)
    _sig(user32, "GetWindowTextW", ctypes.c_int, H, wintypes.LPWSTR, ctypes.c_int)
    _sig(user32, "GetClassNameW", ctypes.c_int, H, wintypes.LPWSTR, ctypes.c_int)
    _sig(user32, "GetForegroundWindow", H)
    _sig(user32, "IsIconic", wintypes.BOOL, H)
    _sig(user32, "IsWindow", wintypes.BOOL, H)
    _sig(user32, "ShowWindow", wintypes.BOOL, H, ctypes.c_int)
    _sig(user32, "SetForegroundWindow", wintypes.BOOL, H)
    _sig(user32, "keybd_event", None, wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
    _sig(user32, "GetClientRect", wintypes.BOOL, H, ctypes.POINTER(wintypes.RECT))
    _sig(user32, "ClientToScreen", wintypes.BOOL, H, ctypes.POINTER(wintypes.POINT))
    _sig(user32, "GetDC", HDC, H)
    _sig(user32, "ReleaseDC", ctypes.c_int, H, HDC)
    _sig(user32, "PrintWindow", wintypes.BOOL, H, HDC, wintypes.UINT)
    _sig(user32, "PostMessageW", wintypes.BOOL, H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _sig(user32, "GetWindowThreadProcessId", wintypes.DWORD, H, ctypes.POINTER(wintypes.DWORD))
    _sig(kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _sig(kernel32, "SetPriorityClass", wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD)
    _sig(kernel32, "SetProcessInformation", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
         wintypes.DWORD)
    _sig(kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _sig(gdi32, "CreateCompatibleDC", HDC, HDC)
    _sig(gdi32, "CreateCompatibleBitmap", HBMP, HDC, ctypes.c_int, ctypes.c_int)
    _sig(gdi32, "SelectObject", HGDI, HDC, HGDI)
    _sig(gdi32, "DeleteObject", wintypes.BOOL, HGDI)
    _sig(gdi32, "DeleteDC", wintypes.BOOL, HDC)
    _sig(gdi32, "GetDIBits", ctypes.c_int, HDC, HBMP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
         ctypes.c_void_p, wintypes.UINT)

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
MK_RBUTTON = 0x0002
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
MK_LBUTTON = 0x0001
VK_SHIFT, SC_LSHIFT = 0x10, 0x2A
PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENTONLY = 0x00000001


def find_minecraft():
    """제목에 'Minecraft' 가 들어간 보이는 창 (런처 제외). 반환 hwnd 또는 None."""
    if not IS_WIN:
        return None
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if "Minecraft" in title and "Launcher" not in title:
            found.append((cls.value.startswith("GLFW"), hwnd))
        return True

    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                                   wintypes.LPARAM]
    user32.EnumWindows(cb, 0)
    if not found:
        return None
    found.sort(reverse=True)            # GLFW(게임 창) 우선
    return found[0][1]


def is_foreground(hwnd):
    return bool(IS_WIN and hwnd and user32.GetForegroundWindow() == hwnd)


def window_alive(hwnd):
    return (not IS_WIN) or bool(hwnd and user32.IsWindow(hwnd))


def is_minimized(hwnd):
    return IS_WIN and bool(user32.IsIconic(hwnd))


def bring_to_front(hwnd):
    """마크 창을 앞으로 (일반 모드에서 '게임 창 클릭' 대신)."""
    if not IS_WIN or not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)      # SW_RESTORE
    # 다른 앱이 포커스를 갖고 있으면 SetForegroundWindow 가 거부될 수 있어 Alt 를 한 번 눌렀다 뗌
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    return bool(user32.SetForegroundWindow(hwnd))


class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def keep_awake(hwnd):
    """마크가 뒤에 있어도 느려지지 않게: 윈도우 절전 제한(EcoQoS) 끄기 + 우선순위 '높음 아래'.
    반환 (우선순위 성공, 절전 제한 끄기 성공)"""
    if not IS_WIN or not hwnd:
        return False, False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x0200 | 0x1000, False, pid.value)   # SET_INFORMATION | QUERY_LIMITED_INFORMATION
    if not h:
        return False, False
    try:
        prio = bool(kernel32.SetPriorityClass(h, 0x00008000))      # ABOVE_NORMAL_PRIORITY_CLASS
        st = _PowerThrottling(1, 0x1 | 0x4, 0)                     # 실행 속도/타이머 제한 둘 다 끔
        throttle = bool(kernel32.SetProcessInformation(h, 4, ctypes.byref(st), ctypes.sizeof(st)))
        return prio, throttle
    finally:
        kernel32.CloseHandle(h)


def client_rect(hwnd):
    """창 안쪽(게임 화면)의 화면 기준 (x, y, w, h)."""
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


class _BMI(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def capture_client(hwnd):
    """가려져 있어도 마크 창 안쪽을 캡처 (BGR). 실패하면 None."""
    _, _, w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        return None
    hdc_win = user32.GetDC(hwnd)
    hdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(hdc, bmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        if not ok:
            return None
        bmi = _BMI()
        bmi.biSize, bmi.biWidth, bmi.biHeight = ctypes.sizeof(_BMI), w, -h
        bmi.biPlanes, bmi.biBitCount = 1, 32
        buf = np.empty((h, w, 4), np.uint8)
        gdi32.GetDIBits(hdc, bmp, 0, h, ctypes.c_void_p(buf.ctypes.data), ctypes.byref(bmi), 0)
        return np.ascontiguousarray(buf[:, :, :3])
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(hwnd, hdc_win)


def _lparam_xy(hwnd):
    _, _, w, h = client_rect(hwnd)
    return ((h // 2) << 16) | (w // 2)


def post_right_click(hwnd):
    lp = _lparam_xy(hwnd)
    user32.PostMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, lp)


def post_left_click(hwnd):
    lp = _lparam_xy(hwnd)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.015)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


WM_MOUSEMOVE = 0x0200
KEYS = {"e": (0x45, 0x12), "esc": (0x1B, 0x01), **{str(i): (0x30 + i, 0x01 + i) for i in range(1, 10)}}


def post_key(hwnd, name):
    """키 한 번 누르고 떼기 (마크는 스캔코드로 키를 구분)."""
    vk, sc = KEYS[name]
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, (sc << 16) | 1)
    time.sleep(0.04)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, (sc << 16) | 1 | (1 << 30) | (1 << 31))


def post_mouse_move(hwnd, x, y):
    """창 안쪽 좌표 (x, y) 로 마우스 이동 (인벤 화면용)."""
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF))


def post_shift(hwnd, down):
    if down:
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_SHIFT, (SC_LSHIFT << 16) | 1)
    else:
        user32.PostMessageW(hwnd, WM_KEYUP, VK_SHIFT, (SC_LSHIFT << 16) | 1 | (1 << 30) | (1 << 31))


class WindowScreen:
    """Screen 과 같은 모양(mon, grab, full). 좌표는 기존처럼 '화면 기준'으로 받고 창 캡처에서 잘라냄."""

    def __init__(self, hwnd, cache_sec=0.015):
        self.hwnd = hwnd
        self.cache_sec = cache_sec
        self._img, self._t, self._origin = None, 0.0, (0, 0)
        x, y, w, h = client_rect(hwnd)
        self.mon = {"left": 0, "top": 0, "width": x + w, "height": y + h}

    def _frame(self):
        now = time.perf_counter()
        if self._img is None or now - self._t > self.cache_sec:
            img = capture_client(self.hwnd)
            if img is not None:
                x, y, w, h = client_rect(self.hwnd)
                self._img, self._origin, self._t = img, (x, y), now
                self.mon = {"left": 0, "top": 0, "width": x + w, "height": y + h}
        return self._img

    def is_black(self):
        img = self._frame()
        return img is None or float(img.mean()) < 2.0

    def grab(self, roi):
        img = self._frame()
        x, y, w, h = roi
        out = np.zeros((h, w, 3), np.uint8)
        if img is None:
            return out
        ox, oy = self._origin
        x0, y0 = x - ox, y - oy
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(img.shape[1], x0 + w), min(img.shape[0], y0 + h)
        if sx1 > sx0 and sy1 > sy0:
            out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
        return out

    def full(self):
        return self.grab([0, 0, self.mon["width"], self.mon["height"]])


def frame_origin(hwnd):
    """WGC 가 캡처하는 창 이미지의 화면 기준 왼쪽 위 (보이지 않는 테두리 제외한 창 영역)."""
    r = wintypes.RECT()
    dwm = ctypes.WinDLL("dwmapi")
    if dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return r.left, r.top
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top


class WGCScreen:
    """Windows Graphics Capture (OBS·디스코드 화면공유 방식).
    게임에 '다시 그려줘' 요청을 안 해서 PrintWindow 보다 게임 부담이 적고 빠름. 가려져 있어도 됨(최소화는 X)."""

    def __init__(self, hwnd, first_frame_timeout=3.0):
        import threading
        from windows_capture import WindowsCapture
        self.hwnd = hwnd
        self._img, self._lock, self._stop = None, threading.Lock(), False
        self.frames = 0
        self.closed = False
        kw = dict(cursor_capture=False, window_hwnd=int(hwnd), minimum_update_interval=12)
        try:
            cap = WindowsCapture(draw_border=False, **kw)     # 노란 테두리 끔 (윈도우 11)
        except Exception:
            cap = WindowsCapture(**kw)

        @cap.event
        def on_frame_arrived(frame, control):
            if self._stop:
                control.stop()
                return
            img = np.array(frame.frame_buffer[:, :, :3])       # 콜백 밖에서 쓰려면 복사 필요
            with self._lock:
                self._img = img
                self.frames += 1

        @cap.event
        def on_closed():
            self.closed = True

        self.control = cap.start_free_threaded()
        end = time.perf_counter() + first_frame_timeout
        while self._img is None and time.perf_counter() < end:
            time.sleep(0.02)
        if self._img is None:
            self.stop()
            raise RuntimeError("WGC 첫 화면이 안 옴")
        self._update_geom()

    def _update_geom(self):
        x, y, w, h = client_rect(self.hwnd)
        self.mon = {"left": 0, "top": 0, "width": x + w, "height": y + h}
        self._origin = frame_origin(self.hwnd)

    def stop(self):
        self._stop = True
        try:
            self.control.stop()
        except Exception:
            pass

    def is_black(self):
        with self._lock:
            img = self._img
        return img is None or float(img.mean()) < 2.0

    def grab(self, roi):
        with self._lock:
            img = self._img
        x, y, w, h = roi
        out = np.zeros((h, w, 3), np.uint8)
        if img is None:
            return out
        ox, oy = self._origin
        x0, y0 = x - ox, y - oy
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(img.shape[1], x0 + w), min(img.shape[0], y0 + h)
        if sx1 > sx0 and sy1 > sy0:
            out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
        return out

    def full(self):
        return self.grab([0, 0, self.mon["width"], self.mon["height"]])


def open_window_screen(hwnd):
    """가려진 마크 창 캡처: WGC 먼저, 안 되면 PrintWindow. 반환 (screen, 방식 이름)"""
    try:
        s = WGCScreen(hwnd)
        if not s.is_black():
            return s, "WGC"
        s.stop()
    except Exception:
        pass
    return WindowScreen(hwnd), "PrintWindow"
