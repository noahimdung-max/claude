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
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
MK_RBUTTON = 0x0002
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

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    found.sort(reverse=True)            # GLFW(게임 창) 우선
    return found[0][1]


def is_foreground(hwnd):
    return IS_WIN and hwnd and user32.GetForegroundWindow() == hwnd


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
        gdi32.GetDIBits(hdc, bmp, 0, h, buf.ctypes.data, ctypes.byref(bmi), 0)
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


def post_shift(hwnd, down):
    if down:
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_SHIFT, (SC_LSHIFT << 16) | 1)
    else:
        user32.PostMessageW(hwnd, WM_KEYUP, VK_SHIFT, (SC_LSHIFT << 16) | 1 | (1 << 30) | (1 << 31))


class WindowScreen:
    """Screen 과 같은 모양(mon, grab, full). 좌표는 기존처럼 '화면 기준'으로 받고 창 캡처에서 잘라냄."""

    def __init__(self, hwnd, cache_sec=0.008):
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
