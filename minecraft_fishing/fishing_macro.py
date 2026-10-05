"""마인크래프트 낚시 매크로 (콘솔 버전). UI 버전은 app.py.

F8: 시작/일시정지   F9: 종료
낚싯대 내구도 바가 빨간색이 되면 자동 정지 + 알림.
python fishing_macro.py            # 실행
python fishing_macro.py --preview  # 검출 결과 실시간 확인(입력 안 보냄)
python fishing_macro.py --debug    # 실행 + 로그
"""
import argparse
import ctypes
import math
import threading
import time
import traceback

import cv2
import numpy as np
import pydirectinput

import winapi

from common import (Screen, fish_color_name, durability_roi_in_slot, selected_slot, bobber_mask, bracket_runs, durability_value, find_bobber, fish_blob_x,
                    gauge_present, load_config, load_subtitle_template, locate_bar, match_bin, save_config, scale_template, text_binary, to_gray,
                    split_view, view_roi, load_history, save_history, history_day, find_inventory,
                    inventory_slots, slot_is_empty, read_tooltip_durability, guess_inventory,
                    gui_overlay, save_debug_image, read_number, turn_pixels, hotbar_index, view_shift, view_focal_px, ANVIL_PATH, remap_rect, remap_point)

pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False


class FileLog:
    """세부 탭에서 '로그 남기기'를 켜면 exe 옆 macro.log 에 단계별 기록 (1MB 넘으면 자동 교체, 최대 2개)."""

    def __init__(self):
        import logging
        from logging.handlers import RotatingFileHandler
        from common import DATA_DIR
        self.log = logging.getLogger("fishing_macro")
        self.log.setLevel(logging.DEBUG)
        if not self.log.handlers:
            h = RotatingFileHandler(DATA_DIR / "macro.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", "%H:%M:%S"))
            self.log.addHandler(h)

    def write(self, tag, msg=""):
        import logging
        if tag == "GAME":                # 미니게임 프레임별 기록은 너무 많아서 조작이 느려질 수 있음 -> 요약만
            return
        level = {"ERROR": logging.ERROR, "INFO": logging.INFO, "KEY": logging.INFO}.get(tag, logging.DEBUG)
        self.log.log(level, f"{tag:6} {msg}")

    def snap(self, *a):
        pass

    def config(self, cfg):
        keys = ("bite_mode", "background", "bar_roi", "subtitle_roi", "durability_max", "durability_stop_pct",
                "left_click_cps", "rod_swap", "exact_durability", "inv_full_stop")
        self.write("CONFIG", ", ".join(f"{k}={cfg.get(k)}" for k in keys))


class NullLog:
    """기록 안 함."""
    def write(self, *a):
        pass

    def snap(self, *a):
        pass

    def config(self, *a):
        pass


def notify(webhook, msg):
    """디스코드 웹훅으로 알림 (주소가 있을 때만, 실패해도 무시)."""
    if not webhook:
        return

    def send():
        import json
        import urllib.request
        try:
            req = urllib.request.Request(webhook, data=json.dumps({"content": "🎣 " + msg}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "fishing-macro"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
    threading.Thread(target=send, daemon=True).start()


def alert(msg):
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(1200, 250)
    except Exception:
        pass
    threading.Thread(
        target=lambda: ctypes.windll.user32.MessageBoxW(0, msg, "낚시 매크로", 0x40000 | 0x30),
        daemon=True,
    ).start()


def save_error(tb):
    """오류 내용을 프로그램 옆 error.txt 에 남김 (보내주면 원인 찾기 쉬움)."""
    from common import DATA_DIR
    try:
        with open(DATA_DIR / "error.txt", "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + tb + "\n")
    except OSError:
        pass


class Stop(Exception):
    pass


class Macro:
    def __init__(self, cfg, debug=False, out=print, hotkeys=True, logger=None):
        self.cfg = cfg
        self.debug = debug
        self.logger = logger or (FileLog() if cfg.get("log_file") else NullLog())
        self.err_retries = 0             # 연속 오류 복구 시도 횟수
        self._ui_out = out
        self.last_view = None            # 마지막으로 캡처한 바 화면 (기록용)
        self.screen = Screen(cfg["monitor"])
        self.hwnd = None                 # 마크 창
        self.bg_mode = False             # 백그라운드 모드 사용 중
        self.io_ready = False            # 시작할 때마다 창 찾기/모드 설정
        self.fails = 0                   # 연속으로 못 낚은 횟수
        self.shift_method = "real"
        self.capture_name = "화면"
        self.run_caught = 0              # 이번 시작 후 낚은 수 (목표용)
        self.bite_img = None             # 입질 판정 순간 화면 (헛챔질 분석용)
        self.depleted = set()            # 이번 시작 후 다 쓴 낚싯대 칸 (1~9)
        self.home_ref = None             # 첫 수리 전 낚시 화면 (돌아올 때 시점 보정 기준)
        self.exact = None                # 정밀 내구도 {"cur", "max", "slot", "at"(그때 낚은 수)}
        self.inv_due = True              # 다음 던지기 전에 인벤 확인
        self.inv_empty = None            # 마지막으로 본 인벤 빈칸 수
        self.inv_map = None              # 36칸 빈칸 여부 (True = 빈칸)
        self.gui_scale = None            # 마크 GUI 배율 (핫바 선택 칸 크기로 앎)
        self.inv_note = ""               # 인벤 확인 결과 한 줄
        self.history = load_history()
        self._hist_t = None
        self.logger.write("START", f"화면 {self.screen.mon}")
        self.logger.config(cfg)
        self.running = False
        self.quit = False
        self.shift_down = False
        self.zone_w = 0
        self.start_at = 0.0
        self.prev_zone = None
        self.pre_mask = None
        self.bobber_h = 0
        self.sub_tmpl = None             # 자막 템플릿 (지정 후 None 으로 바꾸면 다시 읽음)
        self._sub_tmpls, self._sub_tmpls_for = None, None   # 배율별 자막 템플릿 [(배율, 템플릿)] 과 그 원본
        self.sub_pref = 1.0              # 마지막으로 잡힌 자막 배율 (넓은 영역은 이 배율부터 봄)
        self._sub_wide_n = self._sub_near_n = 0   # 넓은/근처 영역을 훑은 횟수 (다른 배율은 5번에 한 번만 같이 봄)
        self.sub_pos = None              # 마지막으로 입질 자막이 잡힌 위치 (캡처 좌표, 템플릿 왼쪽 위). 다음엔 이 근처부터 찾음
        self._sub_wide_t = 0.0           # 넓은 영역을 마지막으로 훑은 시각
        self.state = "대기"
        self.stats = {"bobber_n": None, "bobber_y": None, "zone": None, "fish": None, "active": False,
                      "sub": None, "dura": None, "dura_max": None, "caught": 0,
                      "casts": 0, "games": 0, "catch_times": [], "colors": {}, "started": None}
        if hotkeys:
            import keyboard
            # add_hotkey 는 Alt+Tab 뒤 Alt 가 눌린 걸로 착각해서 안 먹을 수 있음 -> 키 하나만 보고 반응
            keyboard.on_press_key("f8", lambda e: self.toggle(), suppress=False)
            keyboard.on_press_key("f9", lambda e: self.request_quit(), suppress=False)

    # ---------- 입력 ----------
    def missing_setup(self):
        c = self.cfg
        has_sub = bool(c["subtitle_roi"]) and self.subtitle_template() is not None
        if c["bite_mode"] == "subtitle" and not has_sub:
            return "입질 자막을 먼저 지정해야 함"
        if c["bite_mode"] == "bobber" and not c["bobber_roi"]:
            return "찌 영역을 먼저 지정해야 함"
        if c["bite_mode"] == "both" and not has_sub and not c["bobber_roi"]:
            return "입질 자막이나 찌 영역 중 하나는 지정해야 함"
        return None

    def toggle(self):
        self.logger.write("KEY", "시작/정지 요청")
        if not self.running and self.missing_setup():
            self.out(self.missing_setup())
            return
        self.running = not self.running
        if self.running:
            self.io_ready = False
            self.fails = 0
            self.stats["started"] = time.time()
            self.run_caught = 0
            self.depleted = set()
            self.home_ref = None
            self.inv_off, self.inv_fails = False, 0
            self.inv_empty, self.inv_map = None, None
            self.err_retries = 0
            if not isinstance(self.logger, FileLog) and self.cfg.get("log_file"):
                self.logger = FileLog()
            elif isinstance(self.logger, FileLog) and not self.cfg.get("log_file"):
                self.logger = NullLog()
            self.logger.config(self.cfg)
            self.exact = None
            self.inv_due = True
            self._hist_t = None
            self.start_at = time.perf_counter() + self.cfg["start_delay_sec"]
            self.out("[시작] " + ("백그라운드 모드로 시작" if self.cfg["background"] else "마크 창으로 전환해서 시작"))
        else:
            self.out("[정지]")

    def request_quit(self):
        self.quit = True

    def out(self, msg):
        self.logger.write("INFO", msg)
        self._ui_out(msg)

    def log(self, *a):
        msg = " ".join(str(x) for x in a)
        self.logger.write("DEBUG", msg)          # 파일엔 항상 기록
        if self.debug:
            self._ui_out(msg)

    def stop_with(self, msg):
        """알림 띄우고(+디스코드) 멈춤."""
        self.running = False
        self.out("[알림] " + msg)
        alert(msg)
        notify(self.cfg["discord_webhook"], msg + f" (이번에 {self.run_caught}마리)")
        raise Stop

    def close_screen(self):
        if hasattr(self.screen, "stop"):
            self.screen.stop()

    def setup_io(self):
        """시작할 때: 마크 창 찾기 + (백그라운드 모드면) 창 캡처 확인 / (일반이면) 창을 앞으로."""
        c = self.cfg
        self.hwnd = winapi.find_minecraft()
        self.bg_mode = False
        if c["background"]:
            if not self.hwnd:
                self.running = False
                self.out("[정지] 마크 창을 못 찾았어 (마크를 먼저 켜줘)")
                raise Stop
            if winapi.is_minimized(self.hwnd):
                self.running = False
                self.out("[정지] 백그라운드 모드는 마크 창을 최소화하면 안 돼 (다른 창 뒤에 두기만)")
                raise Stop
            self.close_screen()
            ws, how = winapi.open_window_screen(self.hwnd)
            self.capture_name = how
            if ws.is_black():
                self.running = False
                self.out("[정지] 이 PC에선 가려진 마크 화면을 캡처할 수 없어 -> 백그라운드 모드 끄고 써줘")
                raise Stop
            self.screen, self.bg_mode = ws, True
            prio, throttle = winapi.keep_awake(self.hwnd)
            self.out(f"백그라운드 모드({how}): 다른 창 써도 돼 (마크 F3+P 켜져 있어야 함)"
                     + ("" if throttle else " / 마크 절전 제한 끄기 실패: 가이드 참고"))
        else:
            self.close_screen()
            self.screen = Screen(c["monitor"])
            if self.hwnd and not winapi.is_foreground(self.hwnd):
                winapi.bring_to_front(self.hwnd)
                time.sleep(0.3)
        self.io_ready = True
        self.follow_window()
        self.adapt_gui_scale()

    def adapt_gui_scale(self):
        """마크 GUI 배율이 설정 때와 다르면 (자동 배율은 창 크기 따라 바뀜) 자막 위치·크기를 비율대로 맞추고
        미니게임 바는 다시 자동으로 찾게 함."""
        c = self.cfg
        self.sub_roi, self.sub_scale_ratio = None, 1.0
        self.sub_tmpl = None                         # 지난번 배율로 줄이거나 늘린 템플릿이 남지 않게
        try:
            cur = self.hotbar_slot() and self.gui_scale
        except Exception:
            cur = None
        if not cur:
            return
        old = c.get("subtitle_scale")
        if old and old != cur and c["subtitle_roi"]:
            r = cur / old
            gx, gy, gw, gh = self.game_rect()
            R, B = gx + gw, gy + gh
            x, y, w, h = c["subtitle_roi"]            # 자막은 게임 화면 오른쪽 아래 기준으로 커짐/작아짐
            self.sub_roi = [int(R - (R - x) * r), int(B - (B - y) * r), max(1, int(w * r)), max(1, int(h * r))]
            self.sub_scale_ratio = r
            self.sub_tmpl = None
            self.out(f"[알림] 마크 GUI 배율이 자막 지정 때({old})와 달라({cur}) -> 자동으로 맞춤. "
                     "입질을 못 잡으면 자막을 다시 지정해줘")
        if c.get("bar_scale") and c["bar_scale"] != cur and c["bar_roi"]:
            c["bar_roi"] = None                     # 바 위치는 배율 따라 달라짐 -> 다음 미니게임 때 다시 찾음
            self.out(f"[알림] GUI 배율이 바뀌어서({c['bar_scale']} -> {cur}) 미니게임 바를 다시 찾을게")
        c["bar_scale"] = cur

    def right_click(self):
        self.logger.write("KEY", "우클릭")
        if self.bg_mode:
            winapi.post_right_click(self.hwnd)
            return
        pydirectinput.mouseDown(button="right")
        time.sleep(0.05)
        pydirectinput.mouseUp(button="right")

    def _shift_method(self):
        """백그라운드 모드라도 마크 창이 앞에 있으면 진짜 키 입력을 써야 함.
        (마크(GLFW)는 창이 앞에 있을 때 실제 키보드에 Shift 가 안 눌려 있으면 바로 떼버림)"""
        if self.bg_mode and not winapi.is_foreground(self.hwnd):
            return "post"
        return "real"

    def _clicker(self, stop_ev):
        """미니게임 중 좌클릭 연타 (물고기가 빨리 올라옴). 조작 루프가 안 느려지게 따로 돔."""
        gap = 1.0 / self.cfg["left_click_cps"]
        nxt = time.perf_counter()
        while not stop_ev.is_set():
            front = not self.hwnd or winapi.is_foreground(self.hwnd)
            try:
                if front:
                    pydirectinput.mouseDown(button="left")
                    time.sleep(0.015)
                    pydirectinput.mouseUp(button="left")
                elif self.bg_mode:
                    winapi.post_left_click(self.hwnd)
                # 일반 모드에서 마크가 뒤에 있으면 다른 창을 누르지 않게 건너뜀
            except Exception:
                return
            nxt = max(nxt + gap, time.perf_counter())
            stop_ev.wait(nxt - time.perf_counter())

    def _send_shift(self, method, down):
        # 웅크리기 키 (설정: Shift/Ctrl). 누른 키로 떼야 하니 누를 때 기억
        if down:
            self.sneak_key = "ctrl" if self.cfg.get("sneak_key") == "ctrl" else "shift"
        key = getattr(self, "sneak_key", "shift")
        if method == "post":
            winapi.post_shift(self.hwnd, down, key)
        else:
            (pydirectinput.keyDown if down else pydirectinput.keyUp)(key)

    def set_shift(self, down):
        method = self._shift_method()
        if down == self.shift_down and method == self.shift_method:
            return
        if self.shift_down and method != self.shift_method:
            # 창 전환됨: 예전 방식으로 누른 Shift 를 확실히 뗌 (다른 창에 Shift 가 남지 않게)
            self._send_shift(self.shift_method, False)
            if down:
                self._send_shift(method, True)
        else:
            self._send_shift(method, down)
        self.shift_down, self.shift_method = down, method

    def check(self):
        if self.quit or not self.running:
            raise Stop
        if self.bg_mode and not winapi.window_alive(self.hwnd):
            self.set_shift(False)
            self.stop_with("마크 창이 닫혔어 -> 정지")
        # 일반 모드: 마크 창이 앞에 없으면 다른 창에 키가 들어가니 기다림
        if not self.bg_mode and self.hwnd and not winapi.is_foreground(self.hwnd):
            self.set_shift(False)
            prev = self.state
            self.state = "마크 창이 앞에 없어서 일시정지"
            while not winapi.is_foreground(self.hwnd):
                if self.quit or not self.running:
                    raise Stop
                time.sleep(0.1)
            self.state = prev

    def sleep(self, sec):
        end = time.perf_counter() + sec
        while time.perf_counter() < end:
            self.check()
            time.sleep(0.01)

    # ---------- 검출 ----------
    def bobber(self, roi=None):
        """roi(기본: 찌 탐색 영역 전체) 안의 찌 픽셀 수와 세로 위치."""
        c = self.cfg
        roi = roi or c["bobber_roi"]
        if not roi:
            return 0, None
        m = bobber_mask(self.screen.grab(roi), c)
        n = int(m.sum())
        y = float(np.nonzero(m)[0].mean()) if n >= c["min_pixels"] else None
        self.stats["bobber_n"], self.stats["bobber_y"] = n, y
        return n, y

    def search_roi(self):
        if self.cfg["bar_search_roi"]:
            return self.cfg["bar_search_roi"]
        gx, gy, gw, gh = self.game_rect()
        return [gx + int(gw * 0.2), gy + int(gh * 0.6), int(gw * 0.6), gh - int(gh * 0.6)]

    def find_bar(self, save_debug=False):
        """바 자동 탐색. 찾으면 config.json에 저장. 못 찾으면 save_debug 시 탐색 화면을 저장."""
        sx, sy, _, _ = roi = self.search_roi()
        img = self.screen.grab(roi)
        found = locate_bar(img, self.cfg)
        if found is None:
            if save_debug:
                self.save_debug(img)
            return False
        x, y, w, h = found
        self.cfg["bar_roi"] = [sx + x, sy + y, w, h]
        if self.gui_scale:
            self.cfg["bar_scale"] = self.gui_scale
        save_config(self.cfg)
        self.out(f"[바 위치 자동 감지] {self.cfg['bar_roi']} 저장됨")
        return True

    def bobber_search_mask(self):
        img = self.screen.grab(self.cfg["bobber_roi"])
        return img, bobber_mask(img, self.cfg)

    def locate_bobber(self):
        """던진 뒤 탐색 영역에서 새로 나타난 찌('빨간 덩어리 + 흰 부분')를 조준점 가까이에서 찾아 추적 영역 반환."""
        c = self.cfg
        sx, sy, sw, sh = c["bobber_roi"]
        mon = self.screen.mon
        center = (mon["width"] / 2 - sx, mon["height"] / 2 - sy)       # 조준점 (탐색 영역 기준)
        max_side = max(40, int(0.075 * mon["height"]))
        deadline = time.perf_counter() + 3.0
        img = None
        while time.perf_counter() < deadline:
            self.check()
            img = self.screen.grab(c["bobber_roi"])
            found = find_bobber(img, center, self.pre_mask, c["min_pixels"], max_side)
            if found:
                x, y, w, h = found
                self.bobber_h = h
                mx, my = max(10, w), max(10, 2 * h)
                x0, y0 = max(0, x - mx), max(0, y - my)
                x1, y1 = min(sw, x + w + mx), min(sh, y + h + 2 * my)
                return [sx + x0, sy + y0, x1 - x0, y1 - y0]
            time.sleep(0.05)
        if img is not None:
            self.save_debug(img, "debug_bobber.png", "찌 못 찾음")
        return None

    def save_debug(self, img, name=None, what=None):
        if what:
            self.out(f"[{what}]")
            return
        self.out("[바 못 찾음] 미니게임이 떠 있을 때 '직접'으로 바를 지정해줘")

    def bar_state(self):
        """(미니게임 중인지, 잡는 구간 중심 x, 물고기 x). 바 좌표 기준."""
        active, zone, fish = self._bar_state()
        self.stats.update(active=active, zone=zone, fish=fish)
        return active, zone, fish

    def _bar_state(self):
        c = self.cfg
        if not c["bar_roi"] and not self.find_bar():
            return False, None, None
        vr, bar_row = view_roi(c["bar_roi"])
        self.last_view = self.screen.grab(vr)
        bar, above = split_view(self.last_view, bar_row)
        fish_x = fish_blob_x(bar, c)
        br = bracket_runs(bar, c)
        # 미니게임 판정: 파란 트랙 위 물고기 + (게이지 또는 괄호). 게이지/물고기 색은 판마다 다름
        active = fish_x is not None and (bool(br) or gauge_present(above, c["bar_roi"][3]))
        if not active:
            return False, None, None

        centers = [(a + b) / 2 for a, b in br]
        zone_x = None
        if len(centers) >= 2 and centers[-1] - centers[0] > 2:
            zone_x = (centers[0] + centers[-1]) / 2
            self.zone_w = centers[-1] - centers[0]
        elif len(centers) == 1 and self.zone_w > 0 and self.prev_zone is not None:
            # 괄호가 하나만 보임(물고기에 가림 등) -> 이전 위치 기준으로 어느 쪽인지 판단
            x = centers[0]
            zone_x = x + self.zone_w / 2 if x < self.prev_zone else x - self.zone_w / 2
        if zone_x is not None:
            self.prev_zone = zone_x
        return True, zone_x, fish_x

    # ---------- 자막 ----------
    def subtitle_template(self):
        if self.sub_tmpl is None:
            t = load_subtitle_template()
            r = getattr(self, "sub_scale_ratio", 1.0)
            if t is not None and abs(r - 1) > 0.01:
                t = cv2.resize(t, None, fx=r, fy=r, interpolation=cv2.INTER_NEAREST)
            self.sub_tmpl = t
            self.sub_pos = None                      # 템플릿·영역이 바뀌었으니 예전 위치는 버림
        return self.sub_tmpl

    SUB_WIDE_EVERY = 0.05      # 마지막 위치 근처에서 못 찾았을 때 넓은 영역을 다시 훑는 간격(초)
    SUB_SCALES = (0.9, 1.0, 1.1)   # 자막 크기가 조금 달라도 잡도록 이 배율들로 비교해서 가장 높은 점수를 씀
    SUB_ALT_EVERY = 5          # 마지막으로 잡힌 배율만 매번 보고, 나머지 배율은 이 횟수에 한 번만 같이 봄 (계산량을 늘리지 않으려고)

    def subtitle_templates(self):
        """[(배율, 템플릿)]. 1.0 은 지금까지 쓰던 것(GUI 배율 변화에 맞춘 크기) 그대로, 나머지는 그것의 0.9·1.1배."""
        base = self.subtitle_template()
        if base is None:
            return []
        if self._sub_tmpls is None or self._sub_tmpls_for is not base:
            lst = []
            for sc in self.SUB_SCALES:
                t = base if sc == 1.0 else scale_template(base, sc)
                if t.shape[0] < 3 or t.shape[1] < 3 or any(t.shape == u.shape for _, u in lst):
                    continue                                 # 너무 작거나 크기가 같으면 의미 없음
                lst.append((sc, t))
            self._sub_tmpls, self._sub_tmpls_for, self.sub_pref = lst, base, 1.0
        return self._sub_tmpls

    def _match_roi(self, roi, tmpls):
        """roi 를 한 번 캡처해서 배율별 템플릿과 비교 -> (최고 점수, 절대좌표 (x, y), 그 배율)."""
        g = text_binary(to_gray(self.screen.grab(roi)))
        bl = getattr(self, "bite_log", None)
        best_s, best_loc, best_sc = 0.0, None, tmpls[0][0]
        for sc, t in tmpls:
            s, loc = match_bin(g, t)
            if bl is not None:
                bl["sub_scale_max"][sc] = max(bl["sub_scale_max"].get(sc, 0.0), s)
            if loc is not None and (best_loc is None or s > best_s):
                best_s, best_loc, best_sc = s, (roi[0] + loc[0], roi[1] + loc[1]), sc
        return best_s, best_loc, best_sc

    def subtitle_score(self):
        """자막 일치도 (배율 0.9/1.0/1.1 중 최고 점수).
        2단계 탐색: ① 마지막으로 잡힌 위치 근처(작은 영역) -> ② 못 찾으면 넓은 영역(subtitle_search_roi).
        넓은 영역은 0.05초에 한 번만 훑음. 두 단계 모두 마지막으로 잡힌 배율만 매번, 다른 배율은 5번에 한 번만 같이 봄.
        넓은 영역에서 잡히면 그 위치가 새 '마지막 위치'가 돼서 바로 다음 확인은 ①에서 됨.
        근처에서 잡히면 넓은 영역은 안 훑음 (자막은 줄이 쌓이면 위아래로, 다른 자막 폭에 따라 좌우로 조금씩 움직임)."""
        c = self.cfg
        tmpls = self.subtitle_templates()
        if not tmpls or not c["subtitle_roi"]:
            self.stats["sub"] = None
            return None
        thr = c["subtitle_threshold"]
        wide = getattr(self, "sub_roi", None) or c["subtitle_roi"]
        tw, th = max(t.shape[1] for _, t in tmpls), max(t.shape[0] for _, t in tmpls)
        bl = getattr(self, "bite_log", None)
        now = time.perf_counter()
        score, stage, where, hit_sc = 0.0, "근처", None, self.sub_pref
        if self.sub_pos is not None:
            px, py = self.sub_pos
            mx, my = int(tw * 0.6), int(th * 4)            # 좌우로 글자 폭의 60%, 위아래로 글자 높이의 4배
            x0, y0 = max(wide[0], px - mx), max(wide[1], py - my)
            x1, y1 = min(wide[0] + wide[2], px + tw + mx), min(wide[1] + wide[3], py + th + my)
            if x1 - x0 >= tw and y1 - y0 >= th:
                alt = self._sub_near_n % self.SUB_ALT_EVERY == 0
                self._sub_near_n += 1
                use = tmpls if alt else [x for x in tmpls if x[0] == self.sub_pref] or tmpls
                score, where, hit_sc = self._match_roi([x0, y0, x1 - x0, y1 - y0], use)
                if bl is not None:
                    bl["sub_near"] += 1
                    bl["sub_alt"] += alt
        if score < thr and (self.sub_pos is None or now - self._sub_wide_t >= self.SUB_WIDE_EVERY):
            self._sub_wide_t = now
            alt = self._sub_wide_n % self.SUB_ALT_EVERY == 0
            self._sub_wide_n += 1
            use = tmpls if alt else [x for x in tmpls if x[0] == self.sub_pref] or tmpls
            s, loc, sc = self._match_roi(wide, use)
            if bl is not None:
                bl["sub_wide"] += 1
                bl["sub_alt"] += alt
            if s >= score:
                score, stage, where, hit_sc = s, "넓게", loc, sc
        if score >= thr and where is not None:
            self.sub_pos, self.sub_pref = where, hit_sc
            if bl is not None:
                if bl["sub_hit"] is None:                  # 이번 입질에서 처음 기준을 넘은 단계/위치/배율
                    bl["sub_hit"] = f"{stage}@{where[0]},{where[1]} 배율 {hit_sc}"
                bl["sub_hits_" + ("near" if stage == "근처" else "wide")] += 1
        self.stats["sub"] = score
        return score

    def durability_reading(self):
        """(내구도 숫자, 종류) - 종류: color / low(1~2) / full. 영역 미설정이면 None."""
        c = self.cfg
        roi = (None if c["rod_swap"] else c["durability_roi"]) or self.auto_durability_roi()
        d = durability_value(self.screen.grab(roi), c["durability_max"]) if roi else None
        self.stats["dura"], self.stats["dura_max"] = d, c["durability_max"]
        return d

    def auto_durability_roi(self):
        """핫바에서 선택된 칸(밝은 테두리)을 찾아 그 아래 내구도 줄 영역."""
        sx, sy, aw, ah = self.hotbar_area()
        slot = selected_slot(self.screen.grab([sx, sy, aw, ah]))
        if not slot:
            return None
        x, y, sw, sh = slot
        return durability_roi_in_slot((sx + x, sy + y, sw, sh))

    def durability_limit(self):
        c = self.cfg
        return c["durability_max"] * c["durability_stop_pct"] / 100

    def durability_ok(self):
        if self.cfg["durability_ignore"]:
            return True
        ex = self.exact_now() if self.cfg["exact_durability"] else None
        if ex:
            cur, mx, _ = ex
            self.stats["dura"], self.stats["dura_max"] = (cur, "exact"), mx
            return cur > mx * self.cfg["durability_stop_pct"] / 100
        d = self.durability_reading()
        if d is None:
            return True
        val, kind = d
        self.log(f"내구도 {val}/{self.cfg['durability_max']} ({kind})")
        if kind == "low":                # 1~2 는 화면으로 구분이 안 됨 -> 무조건 멈춤
            return False
        return val > self.durability_limit()

    def sample(self):
        """대기 중 상태 표시용."""
        if self.cfg["bobber_roi"]:
            self.bobber()
        self.subtitle_score()
        self.bar_state()
        self.durability_reading()

    # ---------- 단계 ----------
    def wait_bite(self):
        """입질 기다리기. both(기본) = 자막과 찌를 같이 보고 먼저 잡힌 쪽으로.
        both 인데 한쪽만 지정돼 있으면 지정된 쪽만 봄."""
        c = self.cfg
        mode = c["bite_mode"]
        if mode == "both":
            has_sub = bool(c["subtitle_roi"]) and self.subtitle_template() is not None
            if not c["bobber_roi"]:
                mode = "subtitle"
            elif not has_sub:
                mode = "bobber"
        self.bite_log = {"mode": mode, "sub_max": None, "dip_max": None, "sub_near": 0, "sub_wide": 0,
                         "sub_hits_near": 0, "sub_hits_wide": 0, "sub_hit": None, "sub_alt": 0, "sub_scale_max": {}}
        self.logger.write("BITE", f"입질 대기 시작: 모드={mode} (설정 {c['bite_mode']})")
        if mode == "subtitle":
            ok = self.wait_bite_subtitle()
        else:
            ok = self.wait_bite_bobber(both=mode == "both")
        bl = self.bite_log
        tr = (self.stats.get("trace") or []) if mode != "subtitle" else []
        f = lambda v, fmt=".2f": "-" if v is None else format(v, fmt)
        self.logger.write("BITE", f"결과={'입질' if ok else '실패'} 모드={mode} 판정=v2(속도+픽셀감소 0.12초) "
                                  f"사유={bl.get('reason') or '-'} 예전판정도반응={'예' if bl.get('old_same') else '아니오'} "
                                  f"자막최고={f(bl['sub_max'])} 자막탐색=v3(멀티스케일 {'/'.join(str(x) for x in self.SUB_SCALES)}, 배율별최고 "
                                  + ' '.join(f'{k}={v:.2f}' for k, v in sorted(bl['sub_scale_max'].items())) +
                                  f", 근처 {bl['sub_near']}회·넓게 {bl['sub_wide']}회 훑음(그중 모든 배율을 본 횟수 {bl['sub_alt']}), "
                                  f"기준 넘은 것 근처 {bl['sub_hits_near']}·넓게 {bl['sub_hits_wide']}, 처음 잡힌 곳={bl['sub_hit'] or '-'}) "
                                  f"dip진행최고={f(bl['dip_max'])}(1=기준) 하강속도최고={f(bl.get('speed_max'), '.1f')}h/s "
                                  f"픽셀감소기각={bl.get('drop_rej', 0)}프레임 예전판정만반응={bl.get('old_only', 0)}프레임 "
                                  f"마지막값[{bl.get('last', '-')}] "
                                  f"trace(가라앉음,물보라 / 최근 120프레임 6칸마다)={[(round(a, 2), round(b, 2)) for a, b in tr[-120:][::6]]}")
        return ok

    def _note_sub(self, s):
        """실패 판 분석용: 이번 대기 중 자막 점수 최고값."""
        bl = getattr(self, "bite_log", None)
        if bl is not None and s is not None and (bl["sub_max"] is None or s > bl["sub_max"]):
            bl["sub_max"] = s

    def wait_bite_subtitle(self, settled=False):
        """자막 '낚시찌 첨벙'이 뜨면 입질. (기존 마크 자동낚시 프로그램들이 쓰는 방식)"""
        c = self.cfg
        thr = c["subtitle_threshold"]
        if not settled:
            self.state = "찌 자리잡는 중"
            self.sleep(c["cast_settle_sec"])

        # 던질 때/이전 입질 때 뜬 자막이 사라질 때까지 기다린 뒤 감시 시작
        t_end = time.perf_counter() + 5.0
        while (self.subtitle_score() or 0) >= thr:
            self.check()
            if time.perf_counter() > t_end:
                self.running = False
                self.out("[정지] 입질 자막이 5초 넘게 계속 보임 -> 자막을 다시 지정해줘")
                raise Stop
            time.sleep(0.05)

        self.state = "입질 기다리는 중 (자막)"
        deadline = time.perf_counter() + c["bite_timeout_sec"]
        hits, next_log = 0, 0.0
        while time.perf_counter() < deadline:
            self.check()
            s = self.subtitle_score() or 0
            self._note_sub(s)
            if time.perf_counter() > next_log:
                self.log(f"자막 일치 {s:.0%} (기준 {thr:.0%})")
                next_log = time.perf_counter() + 0.5
            hits = hits + 1 if s >= thr else 0
            if hits >= c["bite_confirm_frames"]:
                self.bite_img = self.screen.grab(c["subtitle_roi"])
                self.out(f"입질! (자막 일치 {s:.0%})")
                return True
            time.sleep(0.03)
        self.out("입질 시간초과 -> 다시 던짐")
        return False

    def bobber_frame(self, track):
        """추적 영역에서 (빨강 픽셀 수, 찌 중심 y, 흰 물보라 비율, 원본 이미지)."""
        img = self.screen.grab(track)
        red = bobber_mask(img)
        n = int(red.sum())
        y = float(np.nonzero(red)[0].mean()) if n >= self.cfg["min_pixels"] else None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        white = (hsv[..., 1] <= 40) & (hsv[..., 2] >= 200)
        self.stats["bobber_n"], self.stats["bobber_y"] = n, y
        return n, y, float(white.mean()), img

    def wait_bite_bobber(self, both=None):
        """찌 실시간 감지: 찌 높이를 계속 추적(평소 출렁임 범위를 계속 갱신)해서 푹 꺼지거나,
        찌 주변에 흰 물보라가 갑자기 튀면 입질. both 면 자막도 같이 봄."""
        c = self.cfg
        if both is None:
            both = c["bite_mode"] == "both"
        self.state = "찌 자리잡는 중"
        self.sleep(c["cast_settle_sec"])
        track = self.locate_bobber()
        if track is None:
            if not both:
                self.out("찌를 못 찾음 -> 다시 던짐 (물 쪽을 보고 있는지, 찌 영역이 물을 덮는지 확인)")
                return False
            self.out("찌를 못 찾음 -> 자막으로만 감지")
            return self.wait_bite_subtitle(settled=True)

        hist = []                         # 최근 1.5초 (시각, 빨강 수, y, 물보라) - 입질 아닌 프레임만
        recent = []                       # 최근 0.3초 (시각, y) - 하강 속도용 (모든 프레임)
        trace = self.stats.setdefault("trace", [])
        trace.clear()
        self.state = "입질 기다리는 중 (찌" + (" + 자막)" if both else ")")
        deadline = time.perf_counter() + c["bite_timeout_sec"]
        warm_until = time.perf_counter() + 1.0  # 처음 1초는 평소 상태만 배움
        hits, lost_since, drop_since = 0, None, None
        thr = c["subtitle_threshold"]
        bl = getattr(self, "bite_log", None)
        while time.perf_counter() < deadline:
            self.check()
            now = time.perf_counter()
            n, y, splash, img = self.bobber_frame(track)
            if both:
                self._note_sub(self.subtitle_score())
            if both and (self.stats["sub"] or 0) >= thr:
                self.out(f"입질! (자막 {self.stats['sub']:.0%})")
                self.bite_img = img
                return True

            h = max(self.bobber_h, 4)     # 찌 높이(px): 창 크기·GUI 배율에 따라 달라서 기준을 이걸로 맞춤
            if y is not None:
                recent.append((now, y))
            recent = [r for r in recent if now - r[0] <= 0.3]
            hist = [x for x in hist if now - x[0] <= 1.5]
            ys = [x[2] for x in hist if x[2] is not None]
            ns = [x[1] for x in hist]
            sp = [x[3] for x in hist]
            dip = drop = burst = False
            old_dip = old_drop = False    # 예전(v1.6.1 이전) 판정이었다면 (로그 비교용)
            why = ""
            if ys and now > warm_until:
                med_y, med_n, med_sp = float(np.median(ys)), float(np.median(ns)), float(np.median(sp))
                noise_y = float(np.median(np.abs(np.array(ys) - med_y))) * 1.5 + 1
                noise_sp = float(np.median(np.abs(np.array(sp) - med_sp))) * 1.5 + 0.002
                dy = None if y is None else y - med_y
                # (1) 크게 내려감: 예전과 같은 기준
                dip_thr = max(c["bite_dip_px"], 4 * noise_y, 0.35 * h)
                dip_size = dy is not None and dy > dip_thr
                # (2) 작게 내려가도 빠르면: 작은 찌·작은 창에서 놓치던 것. 0.3초 안에 찌 높이의 2배/초 이상으로 하강
                fast_thr = max(2.0, 2.5 * noise_y, 0.2 * h)
                # 최근 0.3초 안의 아무 시점 대비 '충분히(2px·찌높이 20% 이상) 내려갔고, 그 속도가 빠른' 가장 센 값.
                # (1px 흔들림이 짧은 간격에 찍혀 빨라 보이는 것은 d 조건으로 제외)
                speed, raw_speed = None, None
                if y is not None:
                    for t_i, y_i in recent:
                        dt, d = now - t_i, y - y_i
                        if dt < 0.05:
                            continue
                        raw_speed = d / dt if raw_speed is None else max(raw_speed, d / dt)
                        if d >= max(2.0, 0.2 * h):
                            speed = d / dt if speed is None else max(speed, d / dt)
                dip_fast = dy is not None and dy > fast_thr and speed is not None and speed >= 2.0 * h
                dip = dip_size or dip_fast
                # (3) 찌 픽셀이 줄어듦: 파티클이 한순간 가린 것과 구분하려고 0.12초 이상 계속 줄어 있어야 하고,
                #     찌가 위로 튄 게 아니어야 함 (가라앉으면 보이는 부분의 중심은 아래로 감)
                inst = n < med_n * c["bite_drop_ratio"]
                drop_since = (drop_since or now) if inst else None
                drop = inst and now - drop_since >= 0.12 and (dy is None or dy >= -0.15 * h)
                burst = splash > med_sp + max(0.02, 6 * noise_sp)
                old_dip, old_drop = dy is not None and dy > dip_thr, inst
                prog = 0.0 if dy is None else max(dy / max(dip_thr, 1), dy / fast_thr if dip_fast else 0.0)
                trace.append((prog, (splash - med_sp) / max(0.02, 6 * noise_sp)))
                del trace[:-120]
                why = "+".join(k for k, v in (("가라앉음(크기)", dip_size), ("가라앉음(속도)", dip_fast and not dip_size),
                                              ("픽셀감소", drop), ("물보라", burst)) if v)
                if bl is not None:
                    bl["dip_max"] = prog if bl["dip_max"] is None else max(bl["dip_max"], prog)
                    if raw_speed is not None:
                        bl["speed_max"] = max(bl.get("speed_max") or 0.0, raw_speed / h)
                    if inst and not drop and not (old_dip or burst):
                        bl["drop_rej"] = bl.get("drop_rej", 0) + 1       # 예전엔 입질로 봤을 짧은/위로 튄 감소
                    if (old_dip or inst or burst) and not (dip or drop or burst):
                        bl["old_only"] = bl.get("old_only", 0) + 1
                    bl["last"] = f"dy={dy if dy is None else round(dy, 1)} 기준={dip_thr:.1f}/{fast_thr:.1f} 속도={'-' if speed is None else round(speed / h, 1)}h/s n={n}/{med_n:.0f}"
            if y is None:
                lost_since = lost_since or now
                if now - lost_since > 2.0 and not (dip or drop):
                    self.out("찌가 화면에서 사라짐 -> 다시 던짐")
                    return False
            else:
                lost_since = None
            self.stats["bobber_view"] = img
            bite = dip or drop or burst
            hits = hits + 1 if bite else 0
            if hits >= c["bite_confirm_frames"]:
                self.out(f"입질! (찌 {why})")
                if bl is not None:
                    bl["reason"] = why
                    bl["old_same"] = bool(old_dip or old_drop or burst)
                self.bite_img = img
                return True
            if not bite:
                hist.append((now, n, y, splash))
            time.sleep(0.01)
        self.out("입질 시간초과 -> 다시 던짐")
        return False

    def minigame(self):
        c = self.cfg
        self.state = "미니게임 기다리는 중"
        deadline = time.perf_counter() + c["minigame_start_timeout_sec"]
        while True:
            self.check()
            active, zone, fish = self.bar_state()
            if active:
                break
            if time.perf_counter() > deadline:
                if not c["bar_roi"]:
                    self.find_bar(save_debug=True)
                else:
                    self.logger.snap(self.last_view, "미니게임_안뜸")
                    self.logger.snap(self.bite_img, "헛챔질_입질순간")
                    self.out("미니게임 안 뜸 (헛챔질이었거나, 바 위치가 틀렸으면 '자동'으로 다시 찾기)")
                return
            time.sleep(0.01)
        self.state = "미니게임 중"
        self.stats["games"] += 1
        self.record(games=1)
        color = None
        if self.last_view is not None and fish is not None:
            color = fish_color_name(split_view(self.last_view, view_roi(c["bar_roi"])[1])[1])
        self.out("미니게임 시작" + (f" ({color} 물고기)" if color else ""))
        self.logger.snap(self.last_view, "미니게임_시작")

        t0 = last_active = time.perf_counter()
        prev_zone, prev_t, vel = zone, t0, 0.0
        prev_fish, prev_ft, fvel = fish, t0, 0.0
        frame_dt, last_frame = 0.01, t0
        n = n_inactive = n_nozone = n_inside = n_toggle = 0
        snapped_lost = snapped_nozone = False
        lost_img, lost_n = None, 0
        nozone_since = None
        end_reason = "미니게임 사라짐"
        clicking = threading.Event()
        if c["left_click_cps"] > 0:
            threading.Thread(target=self._clicker, args=(clicking,), daemon=True).start()
        try:
            while True:
                self.check()
                now = time.perf_counter()
                active, zone, fish = self.bar_state()
                n += 1
                frame_dt = 0.9 * frame_dt + 0.1 * (now - last_frame)
                last_frame = now
                self.set_shift(self.shift_down)   # 창이 앞/뒤로 바뀌었으면 Shift 입력 방식 갈아탐

                if not active:
                    if lost_img is None:
                        lost_img = self.last_view
                        self.logger.write("GAME", f"t={now - t0:.2f} 미니게임 안 보임 시작")
                    lost_n += 1
                    if now - last_active > c["minigame_end_missing_sec"]:
                        break           # 끝 (마지막 안 보임은 정상 종료라 집계 안 함)
                    continue
                if lost_img is not None:  # 잠깐 놓쳤다가 다시 잡음 -> 문제 상황이라 기록
                    n_inactive += lost_n
                    self.logger.write("GAME", f"t={now - t0:.2f} 미니게임 다시 보임 ({now - last_active:.2f}s 놓침)")
                    if not snapped_lost:
                        self.logger.snap(lost_img, "미니게임_잠깐놓침")
                        snapped_lost = True
                    lost_img, lost_n = None, 0
                last_active = now

                raw_zone = zone
                if zone is None:
                    n_nozone += 1
                    nozone_since = nozone_since or now
                    if not snapped_nozone and now - nozone_since > 0.3:
                        self.logger.snap(self.last_view, "구간_못찾음")
                        snapped_nozone = True
                    if prev_zone is None:
                        self.logger.write("GAME", f"t={now - t0:.2f} 구간(괄호) 못 찾음, 물고기={fish:.0f} -> 조작 안 함")
                        continue
                    zone = prev_zone
                else:
                    nozone_since = None
                    if prev_zone is not None:
                        dt = now - prev_t
                        if dt > 0:
                            vel = 0.7 * vel + 0.3 * (zone - prev_zone) / dt
                    prev_zone, prev_t = zone, now

                if prev_fish is not None and now > prev_ft:
                    fvel = 0.7 * fvel + 0.3 * (fish - prev_fish) / (now - prev_ft)
                prev_fish, prev_ft = fish, now
                # 화면 확인이 느릴수록(백그라운드 모드) 더 앞을 내다봄
                lead = max(c["lead_sec"], 1.5 * frame_dt)
                err = (fish + fvel * lead) - (zone + vel * lead)
                before = self.shift_down
                if err < -c["deadzone_px"]:
                    self.set_shift(True)    # 왼쪽으로
                elif err > c["deadzone_px"]:
                    self.set_shift(False)   # 오른쪽으로
                toggled = before != self.shift_down
                n_toggle += toggled
                if self.zone_w and abs(fish - zone) < self.zone_w / 2:
                    n_inside += 1
                if toggled or raw_zone is None or n % 10 == 0:
                    self.logger.write("GAME", f"t={now - t0:.2f} 구간={'예전값 ' if raw_zone is None else ''}{zone:.0f} "
                                              f"폭={self.zone_w:.0f} 물고기={fish:.0f} 오차={err:.0f} 속도={vel:.0f} "
                                              f"shift={'O' if self.shift_down else 'X'}")
                time.sleep(0.005)
        finally:
            clicking.set()
            self.set_shift(False)
        dur = time.perf_counter() - t0
        self.stats["caught"] += 1
        self.run_caught += 1
        self.stats["catch_times"].append(time.time())
        if color:
            self.stats["colors"][color] = self.stats["colors"].get(color, 0) + 1
        self.cfg["total_caught"] = self.cfg.get("total_caught", 0) + 1
        save_config(self.cfg)
        self.record(caught=1, color=color)
        if (c["exact_durability"] or c["inv_full_stop"]) and self.run_caught % max(1, c["inv_check_every"]) == 0:
            self.inv_due = True
        if c["notify_each_catch"]:
            notify(c["discord_webhook"], f"{color or ''} 물고기 낚음 (이번 {self.run_caught}마리)")
        self.logger.write("SUMMARY", f"미니게임 {dur:.1f}초, 끝난 이유: {end_reason}, 프레임 {n}, "
                                     f"물고기가 구간 안 {n_inside}/{n}, 구간 못찾음 {n_nozone}, 중간에 놓친 프레임 {n_inactive}, "
                                     f"Shift 전환 {n_toggle}회")
        self.out(f"미니게임 끝 (총 {self.stats['caught']}회, {dur:.1f}초, 초당 {n / max(dur, 0.1):.0f}번 확인)")
        self.fails = 0

        if c["reel_click_after_game"]:
            self.right_click()

    # ---------- 기록 ----------
    def record(self, caught=0, casts=0, games=0, color=None):
        """오늘 날짜 기록에 더하고 history.json 저장. 낚시한 시간도 같이 누적."""
        now = time.time()
        d = history_day(self.history, time.strftime("%Y-%m-%d"))
        if self._hist_t is not None:
            d["seconds"] += min(now - self._hist_t, 120)     # 멈췄다 켠 사이 시간은 안 셈
        self._hist_t = now
        d["caught"] += caught
        d["casts"] += casts
        d["games"] += games
        if color:
            d["colors"][color] = d["colors"].get(color, 0) + 1
        save_history(self.history)

    # ---------- 키/마우스 ----------
    def _front(self):
        return not self.hwnd or winapi.is_foreground(self.hwnd)

    def press(self, key):
        if self.bg_mode and not self._front():
            winapi.post_key(self.hwnd, key)
        else:
            pydirectinput.press(key)

    def move_mouse(self, x, y):
        """창 안쪽 좌표로 마우스 이동."""
        if self.bg_mode and not self._front():
            winapi.post_mouse_move(self.hwnd, x, y)
        else:
            ox, oy, _, _ = winapi.client_rect(self.hwnd)
            pydirectinput.moveTo(int(ox + x), int(oy + y))

    def _mon_origin(self):
        """화면 캡처 좌표(모니터 기준)의 원점 = 실제 화면 좌표. 보조 모니터면 (1920, 0) 처럼."""
        m = self.screen.mon
        return m.get("left", 0), m.get("top", 0)

    def client_img(self):
        x, y, w, h = winapi.client_rect(self.hwnd)
        ox, oy = self._mon_origin()
        return self.screen.grab([x - ox, y - oy, w, h])

    def hotbar_slot(self):
        """지금 들고 있는 핫바 칸 (1~9). 못 찾으면 None. (한 바퀴 안에서 여러 번 불려서 0.3초 동안은 저장값)"""
        now = time.perf_counter()
        cache = getattr(self, "_slot_cache", None)
        if cache and now - cache[0] < 0.3:
            return cache[1]
        val = self._hotbar_slot()
        self._slot_cache = (now, val)
        return val

    def game_rect(self):
        """마크 게임 화면(창 안쪽)의 [x, y, w, h] (캡처 좌표). 창을 못 찾으면 화면 전체."""
        W, H = self.screen.mon["width"], self.screen.mon["height"]
        if self.hwnd:
            try:
                x, y, w, h = winapi.client_rect(self.hwnd)
                ox, oy = self._mon_origin()
                if w >= 200 and h >= 150:
                    return [x - ox, y - oy, w, h]
            except Exception:
                pass
        return [0, 0, W, H]

    def hotbar_area(self):
        """핫바가 있을 만한 곳: 게임 화면 아래쪽 가운데."""
        gx, gy, gw, gh = self.game_rect()
        sx, sy = gx + int(gw * 0.2), gy + int(gh * 0.7)
        return [sx, sy, int(gw * 0.6), gy + gh - sy]

    def _hotbar_slot(self):
        sx, sy, aw, ah = self.hotbar_area()
        slot = selected_slot(self.screen.grab([sx, sy, aw, ah]))
        if not slot:
            return None
        gx, _, gw, _ = self.game_rect()
        x, y, sw, sh = slot
        self.gui_scale = max(1, round(sw / 24))          # 선택 칸 테두리 = 24 GUI 픽셀
        self.stats["slot"] = hotbar_index((sx - gx + x, y, sw, sh), gw) + 1
        return self.stats["slot"]

    def window_changed(self):
        """마크 창 크기·위치가 설정 때와 다르면 True (최대화/이전 크기로 등)."""
        ref = self.cfg.get("ref_client")
        return bool(ref) and self.hwnd is not None and self.game_rect() != list(ref)

    def follow_window(self):
        """마크 창이 바뀌었으면 지정해 둔 영역·수리 위치를 새 창에 맞게 옮김. 옮겼으면 True.
        HUD 는 창의 가까운 끝(아래 가운데 핫바, 오른쪽 아래 자막 등)에 붙어 있고, 수리 창은 가운데 기준."""
        c = self.cfg
        if not self.hwnd:
            self.hwnd = winapi.find_minecraft()
        if not self.hwnd or winapi.is_minimized(self.hwnd):
            return False
        cur = self.game_rect()
        ref = c.get("ref_client")
        self._slot_cache = None
        try:
            now_gui = self._hotbar_slot() and self.gui_scale
        except Exception:
            now_gui = None
        if cur[2] < 200 or cur[3] < 150 or not winapi.client_rect(self.hwnd)[2]:
            return False
        if not ref:
            c["ref_client"], c["ref_gui"] = cur, now_gui
            save_config(c)
            return False
        if list(ref) == cur:
            if now_gui and not c.get("ref_gui"):
                c["ref_gui"] = now_gui
                save_config(c)
            return False
        old_gui = c.get("ref_gui")
        r = now_gui / old_gui if now_gui and old_gui else 1.0
        for k in ("durability_roi", "gold_roi", "bar_search_roi"):
            if c.get(k):
                c[k] = remap_rect(c[k], ref, cur, r)
        if c.get("subtitle_roi"):                         # 자막 크기는 adapt_gui_scale 이 배율대로 맞춤
            c["subtitle_roi"] = remap_rect(c["subtitle_roi"], ref, cur, 1.0)
        if c.get("bobber_roi"):                           # 게임 속 화면: 가운데 기준, 창 높이에 비례
            c["bobber_roi"] = remap_rect(c["bobber_roi"], ref, cur, cur[3] / ref[3], "mid")
        c["bar_roi"] = None                               # 미니게임 바는 다음 판에 다시 찾음
        pts = c.get("repair_points")
        if pts:                                           # 수리 창(GUI)은 창 가운데 기준
            for k in ("in1", "in2", "out", "ok", "hot1", "hot9"):
                if pts.get(k):
                    pts[k] = remap_point(pts[k], ref, cur, r, "mid")
            if pts.get("hot"):
                pts["hot"] = [remap_point(p, ref, cur, r, "mid") for p in pts["hot"]]
            pts["screen"] = [self.screen.mon["width"], self.screen.mon["height"]]
        c["ref_client"], c["ref_gui"] = cur, now_gui or old_gui
        save_config(c)
        self.out(f"[알림] 마크 창 크기가 바뀌어서 ({ref[2]}x{ref[3]} -> {cur[2]}x{cur[3]}) 지정한 위치들을 새 창에 맞춤")
        return True

    # ---------- 인벤 확인 (정밀 내구도 / 빈칸) ----------
    def inventory_check(self):
        """E 로 인벤 열고: 빈칸 세기 + 낚싯대 칸에 마우스 올려 툴팁(F3+H) 내구도 읽기 -> 닫기.
        게임 화면일 땐 마우스를 절대 안 움직임 (움직이면 시점이 돌아가서 물을 못 봄)."""
        c = self.cfg
        self.inv_due = False
        if not self.hwnd:
            self.inv_note = "마크 창을 못 찾아서 인벤 확인 못 함"
            return
        slot = self.rod_slot()
        self.state = "인벤 확인 중"
        self.set_shift(False)
        before = self.client_img()
        self.press("e")
        inv, img, opened, verified = None, None, False, False
        try:
            end = time.perf_counter() + 2.0
            while time.perf_counter() < end:
                self.check()
                time.sleep(0.1)
                img = self.client_img()
                inv = find_inventory(img)
                if inv:
                    opened = verified = True
                    break
            if not verified:
                opened = gui_overlay(before, img)
                if not opened:
                    self.inv_note = "인벤이 안 열림 (E 키가 인벤이 맞는지 확인)"
                    return
                save_debug_image(img, "inv_debug.png")
                if not self.gui_scale:
                    self.inv_note = "인벤 창 모양을 못 찾음 (inv_debug.png 를 보내줘)"
                    return
                inv = guess_inventory(img.shape[1], img.shape[0], self.gui_scale)    # 화면 가운데라고 보고 진행
            x0, y0, s = inv
            note = []
            if verified:
                self.move_mouse(max(0, x0 - 20 * s), y0 + 20 * s)  # 칸 위에 마우스가 있으면 밝아져서 빈칸 오판
                self.sleep(0.25)
                img = self.client_img()
                self.inv_map = [slot_is_empty(img, sl) for sl in inventory_slots(inv)]
                self.inv_empty = sum(self.inv_map)
                note.append(f"빈칸 {self.inv_empty}개")
            else:
                self.inv_empty, self.inv_map = None, None   # 예전 값으로 '가득 참' 판단하지 않게
                note.append("인벤 창 모양이 달라서 빈칸은 못 셈 (inv_debug.png 를 보내줘)")
            if c["exact_durability"]:
                if not slot:
                    note.append("들고 있는 칸을 못 찾음")
                else:
                    sx, sy, size = inventory_slots(inv)[27 + slot - 1]
                    self.move_mouse(sx + size // 2, sy + size // 2)
                    d, end = None, time.perf_counter() + 1.5
                    while d is None and time.perf_counter() < end:
                        time.sleep(0.15)
                        img = self.client_img()
                        d = read_tooltip_durability(img)
                    if d:
                        self.exact = {"cur": d[0], "max": d[1], "slot": slot, "at": self.run_caught}
                        if c["durability_max"] != d[1]:         # 최대 내구도도 정확히 알게 됨 -> 색 추정에도 사용
                            c["durability_max"] = d[1]
                            save_config(c)
                        note.append(f"{slot}번 칸 내구도 {d[0]}/{d[1]} (정확)")
                    else:
                        self.exact = None
                        save_debug_image(img, "tooltip_debug.png")
                        note.append("툴팁 숫자 못 읽음 (F3+H 켰는지 확인, 안 되면 tooltip_debug.png 를 보내줘)")
            self.inv_note = " / ".join(note)
        finally:
            if opened or gui_overlay(before, self.view()):   # 열렸다고 판단하기 전에 정지돼도 닫음
                self.close_gui(before)
            time.sleep(0.3)
            # 계속 못 읽으면 (서버 커스텀 인벤 등) 괜히 인벤을 열었다 닫지 않게 이번 낚시 동안 끔
            useful = (c["exact_durability"] and self.exact is not None) or (c["inv_full_stop"] and verified)
            self.inv_fails = 0 if useful else getattr(self, "inv_fails", 0) + 1
            if self.inv_fails >= 2:
                self.inv_off = True
                self.inv_note += " -> 2번 연속 못 읽어서 이번 낚시 동안 인벤 확인 끔 (내구도는 색 막대로)"
            self.log("인벤 확인: " + self.inv_note)
            self.out("[인벤] " + self.inv_note)

    def view(self):
        return self.client_img() if self.hwnd else self.screen.full()

    def recover(self):
        """연속으로 못 낚을 때: 마크에 창(일시정지 메뉴·채팅 등)이 떠 있으면 닫음.
        잘 낚였을 때 화면보다 확실히 어두울 때만 (밤이 되는 정도로는 안 누름)."""
        self.set_shift(False)
        ref = getattr(self, "game_ref", None)
        if ref is None:
            return
        try:
            now = self.view()
        except Exception:
            return
        if gui_overlay(ref, now, ratio=0.55):
            self.out("[복구] 마크에 창(메뉴·채팅 등)이 떠 있는 것 같아서 닫았어")
            self.close_gui(ref)

    def watch_fps(self):
        """다른 창 모드: 마크 화면이 초당 몇 번 새로 그려지는지. 너무 낮으면 입질·미니게임을 놓치니 알림."""
        scr = self.screen
        if not self.bg_mode or not hasattr(scr, "frames"):
            return
        now = time.perf_counter()
        last = getattr(self, "_fps_mark", None)
        self._fps_mark = (now, scr.frames)
        if not last or now - last[0] < 2:
            return
        fps = (scr.frames - last[1]) / (now - last[0])
        self.stats["fps"] = fps
        if fps < 12 and now - getattr(self, "_fps_warned", -1e9) > 300:
            self._fps_warned = now
            self.out(f"[알림] 마크가 뒤에 있을 때 초당 {fps:.0f}번만 그려져서 입질·미니게임을 놓칠 수 있어. "
                     "마크 비디오 설정 '비활성 FPS 제한'을 '최소화'로, Dynamic FPS 같은 모드·클라이언트의 "
                     "'포커스 없을 때 FPS' 를 올려줘 (가이드 탭 참고)")

    def close_gui(self, game_img):
        """연 창 닫기: ESC 한 번. 그 뒤에도 화면이 어두우면(창이 남았거나 일시정지 메뉴) 한 번 더.
        게임 화면이 이미 보이면 절대 더 안 누름 (그러면 일시정지 메뉴가 뜸)."""
        self.press("esc")
        for _ in range(2):
            time.sleep(0.4)
            if not gui_overlay(game_img, self.view()):
                return True
            self.press("esc")
        time.sleep(0.4)
        if gui_overlay(game_img, self.view()):
            self.out("[알림] 마크 창(메뉴)이 안 닫혀 - 확인해줘")
            return False
        return True

    def rod_slot(self):
        """정밀 내구도로 읽을 칸. 설정에서 고른 칸, 아니면(자동·교체 켬) 지금 들고 있는 칸."""
        fixed = self.cfg.get("exact_slot", 0)
        if fixed and not self.cfg["rod_swap"]:
            self.hotbar_slot()                       # GUI 배율 갱신용
            return fixed
        return self.hotbar_slot()

    def exact_now(self):
        """정밀 내구도 추정 (마지막 툴팁 값 - 그 뒤로 낚은 수). 다른 칸이면 None."""
        e = self.exact
        if not e or e["slot"] != self.rod_slot():
            return None
        return max(0, e["cur"] - (self.run_caught - e["at"])), e["max"], self.run_caught == e["at"]

    # ---------- 모루 자동 수리 ----------
    def turn_amount(self):
        """물 -> 모루 마우스 이동량 (dx, dy). 기록한 값, 없으면 각도+감도로 계산."""
        c = self.cfg
        if c.get("repair_turn"):
            return tuple(c["repair_turn"])
        if c.get("repair_yaw") is not None and c.get("mouse_sens_pct"):
            return turn_pixels(c["repair_yaw"], c.get("repair_pitch", 0), c["mouse_sens_pct"])
        return None

    def align_view(self, ref, tries=5, tag="[수리]"):
        """화면을 ref(정확한 시점일 때 화면)와 비교해서 어긋난 만큼 마우스로 조금씩 맞춤. 맞으면 True.
        마우스를 왔다 갔다 하면 조금씩 밀릴 수 있어서 (수리할 때마다 쌓임) 매번 기준 화면에 맞춤."""
        cur = self.client_img()
        if ref is None or cur is None or ref.shape != cur.shape:
            return False
        h, w = cur.shape[:2]
        sens = self.cfg.get("mouse_sens_pct") or (winapi.read_mouse_sensitivity()[0] or 0.5) * 200
        s = sens / 200
        deg = 0.15 * ((s * 0.6 + 0.2) ** 3 * 8)                # 마우스 1칸 = deg 도
        cpp = 1 / (view_focal_px(h) * math.radians(deg))      # 화면 1px = 마우스 몇 칸 (FOV 70 기준, 아래서 실측으로 고침)
        tol = max(2.0, h / 500)
        r = view_shift(ref, cur)
        for i in range(tries):
            if r is None:
                return False
            dx, dy, resp = r
            if resp < 0.1 or abs(dx) > w * 0.3 or abs(dy) > h * 0.3:
                self.out(f"{tag} 기준 화면과 너무 달라서 시점 맞추기는 건너뜀 (일치 {resp:.2f})")
                return False
            if abs(dx) <= tol and abs(dy) <= tol:
                return True
            mx, my = round(dx * cpp), round(dy * cpp)
            if mx == 0 and my == 0:
                return True
            self.logger.write("REPAIR", f"시점 맞춤 {i + 1}: 화면 {dx:.1f},{dy:.1f}px -> 마우스 {mx},{my}")
            winapi.send_mouse_move(mx, my, duration=0.15)
            time.sleep(0.3)
            cur = self.client_img()
            r2 = view_shift(ref, cur)
            if r2 and r2[2] >= 0.1:
                moved = math.hypot(dx - r2[0], dy - r2[1])
                if moved > 3:                                    # 실제로 움직인 양으로 비율 고침
                    k = math.hypot(mx, my) / moved
                    if 0.3 * cpp < k < 3 * cpp:
                        cpp = k
            r = r2
        return bool(r and r[2] >= 0.1 and abs(r[0]) <= tol * 2 and abs(r[1]) <= tol * 2)

    def anvil_ref(self):
        """모루를 정확히 바라본 화면 (방향 기록 때 저장). 없거나 화면 크기가 다르면 None."""
        if not ANVIL_PATH.exists():
            return None
        img = cv2.imdecode(np.fromfile(str(ANVIL_PATH), np.uint8), cv2.IMREAD_COLOR)
        return img

    def read_gold(self):
        roi = self.cfg.get("gold_roi")
        return read_number(self.screen.grab(roi)) if roi else None

    def _gui_click(self, pt, shift=False):
        ox, oy = self._mon_origin()                  # 지정한 위치는 모니터 기준 -> 실제 화면 좌표
        pydirectinput.moveTo(int(pt[0]) + ox, int(pt[1]) + oy)
        time.sleep(0.08)
        if shift:
            pydirectinput.keyDown("shift")
            time.sleep(0.03)
        pydirectinput.click()
        if shift:
            time.sleep(0.03)
            pydirectinput.keyUp("shift")
        self.sleep(0.25)

    def _hover_key(self, pt, key):
        """칸 위에 마우스 올리고 숫자키 = 그 칸 아이템을 핫바 그 번호 칸으로 (마크 기본 기능)."""
        ox, oy = self._mon_origin()
        pydirectinput.moveTo(int(pt[0]) + ox, int(pt[1]) + oy)
        time.sleep(0.08)
        pydirectinput.press(key)
        self.sleep(0.25)

    def repair_rod(self):
        """모루 자동 수리: 시점 돌려 모루 열기 -> 낚싯대·실 Shift+클릭 -> ✓ -> 수리된 낚싯대를 원래 칸으로 -> 닫고 되돌아옴.
        반환 True = 수리 성공. 실패하면 알림 + 정지."""
        c = self.cfg
        pts, turn = c.get("repair_points"), self.turn_amount()
        if self.bg_mode or not self._front():
            self.stop_with("자동 수리는 일반 모드(마크 창이 앞에 있을 때)에서만 돼 -> 정지")
        if not pts or not turn:
            self.stop_with("자동 수리 설정이 덜 됐어 (낚싯대 탭: 모루 방향, 수리 창 위치) -> 정지")
        gold = self.read_gold()
        if gold is not None and gold < c["repair_cost"]:
            self.stop_with(f"골드가 모자라서 수리 못 해 ({gold:,} < {c['repair_cost']:,}) -> 정지")
        rod_key = str(c["repair_rod_slot"])
        h1, h9 = pts["hot1"], pts["hot9"]
        if pts.get("hot"):
            hot = lambda n: pts["hot"][n - 1]
        else:
            hot = lambda n: (h1[0] + (h9[0] - h1[0]) * (n - 1) / 8, h1[1] + (h9[1] - h1[1]) * (n - 1) / 8)
        pitch = abs(h9[0] - h1[0]) / 8
        if self.hotbar_slot() and self.gui_scale and abs(self.gui_scale * 18 - pitch) > 0.2 * pitch:
            self.stop_with(f"마크 GUI 배율이 수리 창 위치 지정 때와 달라 (지금 {self.gui_scale}) -> 다시 지정해줘")

        half = max(4, int(pitch * 0.35))

        def crop_at(pt):
            x, y = int(pt[0]), int(pt[1])
            return self.screen.full()[y - half:y + half, x - half:x + half].astype(np.int16)

        def differs(a, b):
            return a.shape != b.shape or float(np.abs(a - b).mean()) > 6

        def moved(n, shift=True):
            """n번 칸 아이템을 Shift+클릭. 칸 모양이 바뀌었는지 확인하고 안 바뀌면 한 번 더."""
            x, y = hot(n)
            half = max(4, int(pitch * 0.35))
            for attempt in range(2):
                before_c = self.screen.full()[int(y) - half:int(y) + half, int(x) - half:int(x) + half].astype(np.int16)
                self._gui_click((x, y), shift=shift)
                after_c = self.screen.full()[int(y) - half:int(y) + half, int(x) - half:int(x) + half]
                if before_c.shape == after_c.shape and np.abs(before_c - after_c).mean() > 6:
                    return True
                self.sleep(0.3)
            return False

        self.state = "모루로 수리하러 가는 중"
        self.set_shift(False)
        before = self.client_img()
        if self.home_ref is None or self.home_ref.shape != before.shape:
            self.home_ref = before                   # 이번 시작 후 첫 수리 때 낚시 시점 = 항상 여기로 돌아옴
        winapi.send_mouse_move(*turn)
        opened, face = False, None
        try:
            self.sleep(0.3)
            anvil = self.anvil_ref()
            if anvil is not None:
                self.align_view(anvil)               # 모루 화면에 딱 맞춤
            face = self.client_img()
            self.right_click()
            end = time.perf_counter() + 2.0
            while time.perf_counter() < end:
                self.sleep(0.1)
                if gui_overlay(face, self.client_img()):
                    opened = True
                    if anvil is None or anvil.shape != face.shape:   # 처음이거나 창 크기가 바뀜: 열린 모루 화면을 기준으로
                        cv2.imencode(".png", face)[1].tofile(str(ANVIL_PATH))
                    break
            if not opened:
                self.out("[수리] 모루 창이 안 열렸어 (모루 방향을 다시 기록해줘)")
                return False
            self.sleep(0.4)
            self.state = "수리 중"
            in2_empty = crop_at(pts["in2"])                              # 실 넣기 전 빈 재료 칸
            if not moved(c["repair_rod_slot"]):                          # 낚싯대 -> 수리 칸
                self.out(f"[수리] {c['repair_rod_slot']}번 칸 낚싯대가 안 옮겨졌어 (그 칸에 낚싯대가 있는지 확인)")
                return False
            rod_empty = crop_at(hot(c["repair_rod_slot"]))               # 낚싯대 빠진 빈 칸 모양
            if not moved(c["repair_string_slot"]):                       # 실 -> 재료 칸
                self._hover_key(pts["in1"], rod_key)                     # 낚싯대 되돌려 놓기
                self.out(f"[수리] {c['repair_string_slot']}번 칸 실이 안 옮겨졌어 (실이 떨어졌거나 칸이 다름)")
                return False
            self._gui_click(pts["ok"])                                   # ✓ (골드 차감)
            self.sleep(0.8)
            # 여기서는 수리 됐는지 판단하지 않음 (창 모양만으로는 틀릴 수 있음).
            # 무조건 낚싯대를 원래 칸으로 꺼내고 -> 창 닫은 뒤 실제 내구도로 확인.
            self._hover_key(pts["out"], rod_key)                         # 수리됐으면 결과 칸에 있음
            if not differs(crop_at(hot(c["repair_rod_slot"])), rod_empty):
                self._hover_key(pts["in1"], rod_key)                     # 수리 안 됐으면 첫 칸에 그대로
            rod_back = differs(crop_at(hot(c["repair_rod_slot"])), rod_empty)
            if differs(crop_at(pts["in2"]), in2_empty):                  # 실이 남아 있으면(빈 칸이 아니면) 원래 칸으로
                self._hover_key(pts["in2"], str(c["repair_string_slot"]))
            if not rod_back:
                self.out(f"[수리] 낚싯대를 {c['repair_rod_slot']}번 칸으로 못 꺼냈어 (모루 창을 확인해줘)")
                return False
            return True
        finally:
            if face is not None and (opened or gui_overlay(face, self.view())):
                # 닫기 전에 커서를 창 한가운데로 (창 열 때 마크가 둔 자리). 클릭하던 칸 위치에 두고 닫으면
                # 마크가 마우스를 다시 잡을 때 그 거리만큼 시점이 돌아가서 매번 조금씩 더 밀림
                x, y, w, h = winapi.client_rect(self.hwnd)
                pydirectinput.moveTo(x + w // 2, y + h // 2)
                time.sleep(0.1)
                self.close_gui(face)                 # 열렸다고 판단하기 전에 정지돼도 닫음
            time.sleep(0.2)
            winapi.send_mouse_move(-turn[0], -turn[1])
            time.sleep(0.5)
            self.press(rod_key)                      # 낚싯대를 손에 (다시 낚시할 수 있게)
            time.sleep(0.3)
            if self.align_view(self.home_ref):
                self.out("[수리] 낚시 자리로 돌아옴")
            elif self.running:
                self.out("[수리] 원래 시점과 화면이 달라 보여 (확인해줘)")
            self.exact = None
            self.inv_due = True

    # ---------- 낚싯대 교체 ----------
    def swap_rod(self):
        """다음 낚싯대 칸으로. 남은 게 없으면 False."""
        cur = self.hotbar_slot()
        if cur:
            self.depleted.add(cur)
        slots = [s for s in self.cfg["rod_slots"] if 1 <= s <= 9]
        order = [s for s in slots if cur is None or s > cur] + [s for s in slots if cur is not None and s < cur]
        for nxt in order:
            if nxt in self.depleted:
                continue
            self.press(str(nxt))
            self.exact = None
            self.sleep(0.4)
            self.out(f"[교체] 낚싯대 {cur or '?'}번 칸 -> {nxt}번 칸")
            notify(self.cfg["discord_webhook"], f"낚싯대 교체: {cur or '?'}번 -> {nxt}번 칸")
            if self.cfg["exact_durability"]:
                self.inventory_check()
            if self.durability_ok():
                return True
            self.depleted.add(nxt)
        return False

    def cycle(self):
        c = self.cfg
        if self.window_changed():                     # 최대화/이전 크기로 -> 지정한 위치들을 새 창에 맞춤
            if self.bg_mode:
                self.setup_io()                       # 창 캡처도 새 크기로 다시 잡음 (안에서 follow_window)
            elif self.follow_window():
                self.adapt_gui_scale()
        if self._hist_t is None:
            self._hist_t = time.time()
        if self.inv_due and (c["exact_durability"] or c["inv_full_stop"]) and not getattr(self, "inv_off", False):
            self.inventory_check()
        if c["inv_full_stop"] and self.inv_empty is not None and self.inv_empty <= c["inv_min_empty"]:
            self.stop_with(f"인벤 빈칸 {self.inv_empty}개 -> 가득 차서 정지")
        if c["goal_count"] and self.run_caught >= c["goal_count"]:
            self.stop_with(f"목표 {c['goal_count']}마리 달성! -> 정지")
        if c["goal_minutes"] and self.stats["started"] and time.time() - self.stats["started"] >= c["goal_minutes"] * 60:
            self.stop_with(f"{c['goal_minutes']}분 지남 -> 정지")
        if not self.durability_ok() and c.get("repair_on"):
            gold0 = self.read_gold()
            if not self.repair_rod():
                self.stop_with("자동 수리를 못 했어 (위 알림 참고) -> 정지")
            self.sleep(0.3)
            gold1 = self.read_gold()
            paid = f" (골드 {gold0:,} -> {gold1:,})" if gold0 is not None and gold1 is not None else ""
            if not self.durability_ok():
                self.stop_with("수리 후에도 내구도가 낮아: 실이나 골드가 모자랐던 듯" + paid + " -> 정지")
            self.out("[수리] 수리 완료!" + paid)
            notify(c["discord_webhook"], "낚싯대 자동 수리 완료" + paid)
        if not self.durability_ok() and not (c["rod_swap"] and self.swap_rod()):
            if c["rod_swap"]:
                self.stop_with("교체할 낚싯대가 더 없어 (모든 칸 내구도 부족) -> 정지")
            val, kind = self.stats["dura"]
            now = "1~2" if kind == "low" else str(val)
            self.stop_with(f"낚싯대 내구도 {now}/{self.stats.get('dura_max') or c['durability_max']} (멈춤 기준 {c['durability_stop_pct']}% 이하) -> 정지")
        self.state = "던지는 중"
        if self.cfg["bite_mode"] in ("bobber", "both") and self.cfg["bobber_roi"]:
            _, m = self.bobber_search_mask()
            self.pre_mask = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        self.right_click()               # 던지기
        self.stats["casts"] += 1
        self.record(casts=1)
        caught_before = self.stats["caught"]
        if self.wait_bite():
            self.right_click()           # 낚기
            self.minigame()
        else:
            self.right_click()           # 회수
        if self.stats["caught"] == caught_before:
            self.fails += 1
            if self.fails >= 2:
                self.recover()
            if self.fails >= self.cfg["max_fails"]:
                fps = self.stats.get("fps")
                hint = (f" / 마크 화면이 초당 {fps:.0f}번만 그려짐: 뒤에 있을 때 FPS 제한(Dynamic FPS 등) 확인"
                        if self.bg_mode and fps is not None and fps < 12 else "")
                self.stop_with(f"{self.fails}번 연속으로 못 낚았어 -> 정지 (물 쪽을 보고 있는지, 설정 확인){hint}")
        else:
            self.game_ref = self.view()          # 잘 낚인 순간의 게임 화면 (복구 때 비교용)
        self.state = "다시 던지기 대기"
        self.sleep(self.cfg["recast_delay_sec"])
        self.watch_fps()

    def run(self):
        while not self.quit:
            if not self.running or time.perf_counter() < self.start_at:
                self.state = "시작 대기" if self.running else "정지됨"
                try:
                    self.sample()
                except Exception:
                    pass
                time.sleep(0.1)
                continue
            try:
                if not self.io_ready:
                    self.setup_io()
                self.cycle()
                self.err_retries = 0         # 한 바퀴 무사히 돌면 복구 횟수 초기화
            except Stop:
                pass
            except Exception:
                tb = traceback.format_exc()
                self.logger.write("ERROR", tb)
                save_error(tb)
                last = tb.strip().splitlines()[-1]
                if self.running and self.err_retries < 3:
                    # 랙·캡처 끊김 같은 일시적 오류: Shift 떼고 창/캡처를 다시 잡은 뒤 이어서
                    self.err_retries += 1
                    self.out(f"오류 -> 복구 시도 {self.err_retries}/3: {last}")
                    self.set_shift(False)
                    self.io_ready = False
                    self.state = "오류 복구 중"
                    end = time.perf_counter() + 1.5
                    while self.running and not self.quit and time.perf_counter() < end:
                        time.sleep(0.05)
                    continue
                self.running = False
                notify(self.cfg["discord_webhook"], "오류로 정지: " + tb.strip().splitlines()[-1])
                self.out("오류로 정지: " + tb.strip().splitlines()[-1] + "  (error.txt 에 자세히)")
            finally:
                self.set_shift(False)
        self.set_shift(False)


def preview(cfg):
    """입력 없이 감지값만 출력. 창을 띄우지 않으니 게임 화면을 가리지 않음."""
    m = Macro(cfg)
    print("미리보기 (F9 또는 Ctrl+C 종료). 게임 창을 띄워두고 값 변화를 봐")
    fmt = lambda v, f: "-" if v is None else format(v, f)
    try:
        while not m.quit:
            m.sample()
            s = m.stats
            info = (f"자막 일치={fmt(s['sub'], '.0%')} | 찌 px={s['bobber_n']} | "
                    f"미니게임={'O' if s['active'] else 'X'} 구간={fmt(s['zone'], '.0f')} 물고기={fmt(s['fish'], '.0f')} | "
                    f"내구도={'-' if s['dura'] is None else s['dura'][0]}")
            print("\r" + info + "    ", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.preview:
        preview(cfg)
        return
    m = Macro(cfg, args.debug)
    if m.missing_setup():
        raise SystemExit(m.missing_setup() + " -> app.py 에서 지정")
    print("F8: 시작/일시정지, F9: 종료")
    m.run()


if __name__ == "__main__":
    main()
