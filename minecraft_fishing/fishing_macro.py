"""마인크래프트 낚시 매크로 (콘솔 버전). UI 버전은 app.py.

F8: 시작/일시정지   F9: 종료
낚싯대 내구도 바가 빨간색이 되면 자동 정지 + 알림.
python fishing_macro.py            # 실행
python fishing_macro.py --preview  # 검출 결과 실시간 확인(입력 안 보냄)
python fishing_macro.py --debug    # 실행 + 로그
"""
import argparse
import ctypes
import threading
import time
import traceback

import cv2
import numpy as np
import pydirectinput

import winapi

from common import (Screen, fish_color_name, durability_roi_in_slot, selected_slot, bobber_mask, bracket_runs, color_mask, durability_value, find_bobber, fish_blob_x,
                    gauge_present, load_config, load_subtitle_template, locate_bar, match_score, save_config,
                    split_view, view_roi, load_history, save_history, history_day, find_inventory,
                    inventory_slots, slot_is_empty, read_tooltip_durability, guess_inventory,
                    screen_changed, save_debug_image, read_number, turn_pixels, hotbar_index)

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
        self.state = "대기"
        self.stats = {"bobber_n": None, "bobber_y": None, "zone": None, "fish": None, "active": False,
                      "sub": None, "gauge": None, "dura": None, "dura_max": None, "caught": 0,
                      "casts": 0, "games": 0, "catch_times": [], "colors": {}, "started": None}
        if hotkeys:
            import keyboard
            # add_hotkey 는 Alt+Tab 뒤 Alt 가 눌린 걸로 착각해서 안 먹을 수 있음 -> 키 하나만 보고 반응
            keyboard.on_press_key("f8", lambda e: self.toggle(), suppress=False)
            keyboard.on_press_key("f9", lambda e: self.request_quit(), suppress=False)

    # ---------- 입력 ----------
    def missing_setup(self):
        c = self.cfg
        if c["bite_mode"] in ("subtitle", "both"):
            if not c["subtitle_roi"] or self.subtitle_template() is None:
                return "입질 자막을 먼저 지정해야 함"
        if c["bite_mode"] in ("bobber", "both") and not c["bobber_roi"]:
            return "찌 영역을 먼저 지정해야 함"
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
        self.adapt_gui_scale()

    def adapt_gui_scale(self):
        """마크 GUI 배율이 설정 때와 다르면 (자동 배율은 창 크기 따라 바뀜) 자막 위치·크기를 비율대로 맞추고
        미니게임 바는 다시 자동으로 찾게 함."""
        c = self.cfg
        self.sub_roi, self.sub_scale_ratio = None, 1.0
        try:
            cur = self.hotbar_slot() and self.gui_scale
        except Exception:
            cur = None
        if not cur:
            return
        old = c.get("subtitle_scale")
        if old and old != cur and c["subtitle_roi"]:
            r = cur / old
            W, H = self.screen.mon["width"], self.screen.mon["height"]
            x, y, w, h = c["subtitle_roi"]            # 자막은 화면 오른쪽 아래 기준으로 커짐/작아짐
            self.sub_roi = [int(W - (W - x) * r), int(H - (H - y) * r), max(1, int(w * r)), max(1, int(h * r))]
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
        if method == "post":
            winapi.post_shift(self.hwnd, down)
        else:
            (pydirectinput.keyDown if down else pydirectinput.keyUp)("shift")

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
        w, h = self.screen.mon["width"], self.screen.mon["height"]
        return [int(w * 0.2), int(h * 0.6), int(w * 0.6), int(h * 0.4)]

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
        return self.sub_tmpl

    def subtitle_score(self):
        c = self.cfg
        t = self.subtitle_template()
        if t is None or not c["subtitle_roi"]:
            self.stats["sub"] = None
            return None
        s = match_score(self.screen.grab(getattr(self, "sub_roi", None) or c["subtitle_roi"]), t)
        self.stats["sub"] = s
        return s

    def gauge_ratio(self):
        c = self.cfg
        g = None
        if c["gauge_roi"]:
            img = self.screen.grab(c["gauge_roi"])
            g = color_mask(img, c["gauge_color"], c["gauge_tolerance"]).sum() / c["gauge_full_pixels"]
        self.stats["gauge"] = g
        return g

    def durability_reading(self):
        """(내구도 숫자, 종류) - 종류: color / low(1~2) / full. 영역 미설정이면 None."""
        c = self.cfg
        roi = (None if c["rod_swap"] else c["durability_roi"]) or self.auto_durability_roi()
        d = durability_value(self.screen.grab(roi), c["durability_max"]) if roi else None
        self.stats["dura"], self.stats["dura_max"] = d, c["durability_max"]
        return d

    def auto_durability_roi(self):
        """핫바에서 선택된 칸(밝은 테두리)을 찾아 그 아래 내구도 줄 영역."""
        w, h = self.screen.mon["width"], self.screen.mon["height"]
        sx, sy = int(w * 0.2), int(h * 0.7)
        slot = selected_slot(self.screen.grab([sx, sy, int(w * 0.6), h - sy]))
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
        self.gauge_ratio()
        self.durability_reading()

    # ---------- 단계 ----------
    def wait_bite(self):
        if self.cfg["bite_mode"] == "subtitle":
            return self.wait_bite_subtitle()
        return self.wait_bite_bobber()          # bobber / both

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

    def wait_bite_bobber(self):
        """찌 실시간 감지: 찌 높이를 계속 추적(평소 출렁임 범위를 계속 갱신)해서 푹 꺼지거나,
        찌 주변에 흰 물보라가 갑자기 튀면 입질. 'both' 모드면 자막도 같이 봄."""
        c = self.cfg
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

        hist = []                         # 최근 1.5초 (시각, 빨강 수, y, 물보라)
        trace = self.stats.setdefault("trace", [])
        trace.clear()
        self.state = "입질 기다리는 중 (찌" + (" + 자막)" if both else ")")
        deadline = time.perf_counter() + c["bite_timeout_sec"]
        warm_until = time.perf_counter() + 1.0  # 처음 1초는 평소 상태만 배움
        hits, lost_since = 0, None
        thr = c["subtitle_threshold"]
        while time.perf_counter() < deadline:
            self.check()
            now = time.perf_counter()
            n, y, splash, img = self.bobber_frame(track)
            if both and (self.subtitle_score() or 0) >= thr:
                self.out(f"입질! (자막 {self.stats['sub']:.0%})")
                self.bite_img = img
                return True

            hist = [h for h in hist if now - h[0] <= 1.5]
            ys = [h[2] for h in hist if h[2] is not None]
            ns = [h[1] for h in hist]
            sp = [h[3] for h in hist]
            dip = drop = burst = False
            if ys and now > warm_until:
                med_y, med_n, med_sp = float(np.median(ys)), float(np.median(ns)), float(np.median(sp))
                noise_y = float(np.median(np.abs(np.array(ys) - med_y))) * 1.5 + 1
                noise_sp = float(np.median(np.abs(np.array(sp) - med_sp))) * 1.5 + 0.002
                dip_thr = max(c["bite_dip_px"], 4 * noise_y, 0.35 * self.bobber_h)
                dy = None if y is None else y - med_y
                dip = dy is not None and dy > dip_thr
                drop = n < med_n * c["bite_drop_ratio"]
                burst = splash > med_sp + max(0.02, 6 * noise_sp)
                trace.append((0 if dy is None else dy / max(dip_thr, 1), (splash - med_sp) / max(0.02, 6 * noise_sp)))
                del trace[:-120]
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
                why = "+".join(k for k, v in (("가라앉음", dip or drop), ("물보라", burst)) if v)
                self.out(f"입질! (찌 {why})")
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
        end_reason = "물고기/게이지 사라짐"
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

                g = self.gauge_ratio()
                if g is not None and g >= c["gauge_full_ratio"]:
                    end_reason = "게이지 가득"
                    break

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
                                              f"shift={'O' if self.shift_down else 'X'} 게이지={g}")
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

    def client_img(self):
        return self.screen.grab(list(winapi.client_rect(self.hwnd)))

    def hotbar_slot(self):
        """지금 들고 있는 핫바 칸 (1~9). 못 찾으면 None."""
        w, h = self.screen.mon["width"], self.screen.mon["height"]
        sx, sy = int(w * 0.2), int(h * 0.7)
        slot = selected_slot(self.screen.grab([sx, sy, int(w * 0.6), h - sy]))
        if not slot:
            return None
        cw = w
        if self.hwnd:
            cx, _, cw, _ = winapi.client_rect(self.hwnd)
            sx -= cx
        x, y, sw, sh = slot
        self.gui_scale = max(1, round(sw / 24))          # 선택 칸 테두리 = 24 GUI 픽셀
        self.stats["slot"] = hotbar_index((sx + x, y, sw, sh), cw) + 1
        return self.stats["slot"]

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
                opened = screen_changed(before, img)
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
            if opened:
                self.press("esc")
            time.sleep(0.5)
            self.log("인벤 확인: " + self.inv_note)
            self.out("[인벤] " + self.inv_note)

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

    def read_gold(self):
        roi = self.cfg.get("gold_roi")
        return read_number(self.screen.grab(roi)) if roi else None

    def _gui_click(self, pt, shift=False):
        pydirectinput.moveTo(int(pt[0]), int(pt[1]))
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
        pydirectinput.moveTo(int(pt[0]), int(pt[1]))
        time.sleep(0.08)
        pydirectinput.press(key)
        self.sleep(0.25)

    def _slot_like(self, img, pt, ref):
        """칸(pt) 모양이 기준 이미지(ref)와 비슷한지 (빈 칸인지 확인용)."""
        if ref is None:
            return None
        h, w = ref.shape[:2]
        x, y = int(pt[0]) - w // 2, int(pt[1]) - h // 2
        crop = img[max(0, y):y + h, max(0, x):x + w]
        if crop.shape != ref.shape:
            return None
        return float(np.abs(crop.astype(np.int16) - ref).mean()) < 18

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
        W, H = self.screen.mon["width"], self.screen.mon["height"]
        if pts.get("screen") and list(pts["screen"]) != [W, H]:
            self.stop_with("화면(창) 크기가 수리 창 위치 지정 때와 달라 -> '수리 창 위치 지정'을 다시 해줘")
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
        winapi.send_mouse_move(*turn)
        opened = False
        try:
            self.sleep(0.4)
            face = self.client_img()
            self.right_click()
            end = time.perf_counter() + 2.0
            while time.perf_counter() < end:
                self.sleep(0.1)
                if screen_changed(face, self.client_img(), 10):
                    opened = True
                    break
            if not opened:
                self.out("[수리] 모루 창이 안 열렸어 (모루 방향을 다시 기록해줘)")
                return False
            self.sleep(0.4)
            self.state = "수리 중"
            if not moved(c["repair_rod_slot"]):                          # 낚싯대 -> 수리 칸
                self.out(f"[수리] {c['repair_rod_slot']}번 칸 낚싯대가 안 옮겨졌어 (그 칸에 낚싯대가 있는지 확인)")
                return False
            rod_empty = crop_at(hot(c["repair_rod_slot"]))               # 낚싯대 빠진 빈 칸 모양
            if not moved(c["repair_string_slot"]):                       # 실 -> 재료 칸
                self._hover_key(pts["in1"], rod_key)                     # 낚싯대 되돌려 놓기
                self.out(f"[수리] {c['repair_string_slot']}번 칸 실이 안 옮겨졌어 (실이 떨어졌거나 칸이 다름)")
                return False
            in2_full = crop_at(pts["in2"])                               # 실이 들어간 모양
            self._gui_click(pts["ok"])                                   # ✓ (골드 차감)
            self.sleep(0.8)
            # 여기서는 수리 됐는지 판단하지 않음 (창 모양만으로는 틀릴 수 있음).
            # 무조건 낚싯대를 원래 칸으로 꺼내고 -> 창 닫은 뒤 실제 내구도로 확인.
            self._hover_key(pts["out"], rod_key)                         # 수리됐으면 결과 칸에 있음
            if not differs(crop_at(hot(c["repair_rod_slot"])), rod_empty):
                self._hover_key(pts["in1"], rod_key)                     # 수리 안 됐으면 첫 칸에 그대로
            rod_back = differs(crop_at(hot(c["repair_rod_slot"])), rod_empty)
            if not differs(crop_at(pts["in2"]), in2_full):               # 실이 남아 있으면 원래 칸으로
                self._hover_key(pts["in2"], str(c["repair_string_slot"]))
            if not rod_back:
                self.out(f"[수리] 낚싯대를 {c['repair_rod_slot']}번 칸으로 못 꺼냈어 (모루 창을 확인해줘)")
                return False
            return True
        finally:
            if opened:
                self.press("esc")
                time.sleep(0.4)
            winapi.send_mouse_move(-turn[0], -turn[1])
            time.sleep(0.5)
            self.press(rod_key)                      # 낚싯대를 손에 (다시 낚시할 수 있게)
            time.sleep(0.3)
            if not screen_changed(before, self.client_img(), 14):
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
        if self._hist_t is None:
            self._hist_t = time.time()
        if self.inv_due and (c["exact_durability"] or c["inv_full_stop"]):
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
        if self.cfg["bite_mode"] in ("bobber", "both"):
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
            if self.fails >= self.cfg["max_fails"]:
                self.stop_with(f"{self.fails}번 연속으로 못 낚았어 -> 정지 (물 쪽을 보고 있는지, 설정 확인)")
        self.state = "다시 던지기 대기"
        self.sleep(self.cfg["recast_delay_sec"])

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
                    f"게이지={fmt(s['gauge'], '.0%')} | 내구도={'-' if s['dura'] is None else s['dura'][0]}")
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
