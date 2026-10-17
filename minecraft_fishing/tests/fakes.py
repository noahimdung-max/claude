"""테스트용 가짜 마크 화면: 실제 화면·키보드 없이 낚시 로직을 돌려봄 (윈도우가 아니어도 됨).
이 파일을 먼저 import 해야 winapi·pydirectinput·keyboard 가 가짜로 바뀐 채로 fishing_macro 가 불러와짐."""
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

W, H = 1920, 1080
EVENTS = []                                   # 가짜 입력 기록


def _install():
    pdi = types.ModuleType("pydirectinput")
    for n in ("mouseDown", "mouseUp", "keyDown", "keyUp", "moveTo", "click", "press"):
        setattr(pdi, n, (lambda n: lambda *a, **k: EVENTS.append((n, a, k)))(n))
    sys.modules["pydirectinput"] = pdi
    kb = types.ModuleType("keyboard")
    kb.on_press_key = lambda *a, **k: None
    kb.unhook_all = lambda: None
    sys.modules["keyboard"] = kb

    class FakeWin(types.ModuleType):
        rect = [0, 0, W, H]

        def __getattr__(self, n):
            return lambda *a, **k: EVENTS.append(("win." + n, a, k))

    win = FakeWin("winapi")
    win.find_minecraft = lambda: 1
    win.is_foreground = lambda h: True
    win.is_minimized = lambda h: False
    win.window_alive = lambda h: True
    win.client_rect = lambda h: tuple(FakeWin.rect)
    win.read_mouse_sensitivity = lambda: (0.5, True)
    win.send_mouse_move = lambda dx, dy, **k: None
    sys.modules["winapi"] = win


_install()

import common                                  # noqa: E402
import fishing_macro as fm                     # noqa: E402

fm.save_config = lambda c: None
fm.save_history = lambda *a, **k: None
fm.alert = lambda m: EVENTS.append(("alert", m))
fm.notify = lambda *a: None
SAVED = []                                    # 진단용으로 저장하려던 그림 이름 (실제 파일은 안 씀)
fm.save_debug_image = lambda img, name: SAVED.append(name)
common.save_config = lambda c: None


class Scene:
    """물 풍경 + 찌 한 개. 찌 모양/밝기/출렁임/잠김/가림을 바꿔가며 입질 판정을 시험."""
    RGB = {"magenta": (255, 0, 255), "lime": (0, 255, 0)}

    def __init__(self):
        rng = np.random.default_rng(3)
        big = (rng.random((H // 8 + 4, W // 8 + 4, 3)) * 255).astype(np.uint8)
        bg = cv2.resize(cv2.GaussianBlur(big, (0, 0), 1.5), (W + 32, H + 32), interpolation=cv2.INTER_LINEAR)[:H, :W]
        bg[int(H * 0.55):, :] = (180, 90, 40)                 # 물
        self.bg = bg
        self.style, self.k, self.pos = "vanilla", 9, (950, 640)
        self.on = False                                      # 찌가 떠 있음
        self.wob = 0.0                                       # 위아래 출렁임(px)
        self.vanish = False                                  # 입질: 찌가 물에 잠겨 안 보임
        self.occ = False                                     # 파티클이 찌를 가림
        self.dim = 1.0                                       # 화면 밝기
        self.sub = None                                      # (그림, x, y) 자막

    def frame(self):
        img = self.bg.copy()
        if self.on and not self.vanish:
            x, y = self.pos[0], self.pos[1] + int(round(self.wob))
            k = self.k
            if self.style == "vanilla":                      # 흰/빨강/흰 3x3 칸 + 낚싯줄
                cv2.rectangle(img, (x, y), (x + 3 * k - 1, y + k - 1), (240, 240, 240), -1)
                cv2.rectangle(img, (x, y + k), (x + 3 * k - 1, y + 2 * k - 1), (42, 42, 211), -1)
                cv2.rectangle(img, (x, y + 2 * k), (x + 3 * k - 1, y + 3 * k - 1), (240, 240, 240), -1)
                cx0 = x + k
            else:                                            # 형광 5x3 칸 머리
                r, g, b = self.RGB[self.style]
                cv2.rectangle(img, (x, y), (x + 5 * k - 1, y + 3 * k - 1), (b, g, r), -1)
                cx0 = x + 2 * k
            cv2.rectangle(img, (cx0, y + 3 * k), (cx0 + k - 1, y + 6 * k), (0, 0, 0), -1)
            if self.occ:                                     # 옅은 청색 파티클 (흰색 아님)
                cv2.rectangle(img, (x - 2, y - 2), (x + 5 * k + 2, y + 3 * k + 2), (255, 170, 110), -1)
        if self.sub is not None:
            a, sx, sy = self.sub
            img[sy:sy + a.shape[0], sx:sx + a.shape[1]][a > 0] = 255
        if self.dim != 1.0:
            img = (img.astype(np.float32) * self.dim).astype(np.uint8)
        return img


class FakeScreen:
    mon = {"left": 0, "top": 0, "width": W, "height": H}

    def __init__(self, scene):
        self.scene = scene

    def full(self):
        return self.scene.frame()

    def grab(self, roi):
        x, y, w, h = roi
        return np.ascontiguousarray(self.scene.frame()[y:y + h, x:x + w])


class CapLog:
    def __init__(self):
        self.lines = []

    def write(self, tag, msg=""):
        self.lines.append((tag, msg))

    def snap(self, *a):
        pass

    def config(self, *a):
        pass


def make_macro(scene, **over):
    cfg = dict(common.DEFAULTS)
    cfg.update({"bite_mode": "bobber", "bobber_roi": [560, 560, 800, 400], "start_delay_sec": 0, "cast_settle_sec": 0.2,
                "bite_timeout_sec": 4.5, "discord_webhook": ""})
    cfg.update(over)
    fm.Screen = lambda *a, **k: FakeScreen(scene)
    m = fm.Macro(cfg, out=lambda s: None, hotkeys=False)
    m.screen = FakeScreen(scene)
    m.hwnd = 1
    m.running = True
    m.logger = CapLog()
    return m


def run_bite(scene, event, style=None, **over):
    """찌를 띄우고 wait_bite_bobber 를 돌림. event: bite(잠김) / none(출렁임만) / particle(0.06초 가림).
    반환: (입질로 판정했나, 걸린 시간)"""
    scene.on = False
    scene.vanish = scene.occ = False
    scene.wob = 0.0
    m = make_macro(scene, bobber_style=style or "auto", **over)
    m.snapshot_pre_masks()
    stop = threading.Event()
    wob = getattr(scene, "wobble", None)

    def driver():
        time.sleep(0.3)
        scene.on = True
        t0 = time.perf_counter()
        while not stop.is_set():
            t = time.perf_counter() - t0
            if wob:
                scene.wob = wob(t)
            if event == "bite" and t > 2.6:
                scene.vanish = True
            if event == "particle":
                scene.occ = 2.6 < t < 2.66
            time.sleep(0.004)

    threading.Thread(target=driver, daemon=True).start()
    t = time.perf_counter()
    try:
        r = m.wait_bite_bobber(both=False)
    finally:
        stop.set()
        scene.on = False
    return bool(r), time.perf_counter() - t
