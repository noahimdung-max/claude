"""마인크래프트 낚시 매크로.

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

import keyboard
import numpy as np
import pydirectinput

from common import Screen, color_mask, durability_hue, load_config, locate_bar, save_config

pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False


def alert(msg):
    print(f"\n[알림] {msg}")
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


class Stop(Exception):
    pass


class Macro:
    def __init__(self, cfg, debug=False):
        self.cfg = cfg
        self.debug = debug
        self.screen = Screen(cfg["monitor"])
        self.running = False
        self.quit = False
        self.shift_down = False
        self.zone_w = 0
        self.start_at = 0.0
        self.prev_zone = None
        keyboard.add_hotkey("f8", self.toggle)
        keyboard.add_hotkey("f9", self.request_quit)

    # ---------- 입력 ----------
    def toggle(self):
        self.running = not self.running
        if self.running:
            self.start_at = time.perf_counter() + self.cfg["start_delay_sec"]
            print(f"[시작] {self.cfg['start_delay_sec']:.0f}초 뒤 동작. 게임 창 클릭해둬")
        else:
            print("[일시정지]")

    def request_quit(self):
        self.quit = True

    def log(self, *a):
        if self.debug:
            print(f"{time.perf_counter():.2f}", *a)

    def right_click(self):
        pydirectinput.mouseDown(button="right")
        time.sleep(0.05)
        pydirectinput.mouseUp(button="right")

    def set_shift(self, down):
        if down == self.shift_down:
            return
        (pydirectinput.keyDown if down else pydirectinput.keyUp)("shift")
        self.shift_down = down

    def check(self):
        if self.quit or not self.running:
            raise Stop

    def sleep(self, sec):
        end = time.perf_counter() + sec
        while time.perf_counter() < end:
            self.check()
            time.sleep(0.01)

    # ---------- 검출 ----------
    def bobber(self):
        img = self.screen.grab(self.cfg["bobber_roi"])
        m = color_mask(img, self.cfg["bobber_color"], self.cfg["tolerance"])
        n = int(m.sum())
        if n < self.cfg["min_pixels"]:
            return n, None
        return n, float(np.nonzero(m)[0].mean())

    def find_x(self, img, color):
        m = color_mask(img, color, self.cfg["tolerance"])
        xs = np.nonzero(m)[1]
        if xs.size < self.cfg["min_pixels"]:
            return None
        return float(xs.mean())

    def search_roi(self):
        if self.cfg["bar_search_roi"]:
            return self.cfg["bar_search_roi"]
        w, h = self.screen.mon["width"], self.screen.mon["height"]
        return [int(w * 0.2), int(h * 0.6), int(w * 0.6), int(h * 0.4)]

    def find_bar(self):
        """바 자동 탐색. 찾으면 config.json에 저장."""
        sx, sy, _, _ = roi = self.search_roi()
        found = locate_bar(self.screen.grab(roi), self.cfg)
        if found is None:
            return False
        x, y, w, h = found
        self.cfg["bar_roi"] = [sx + x, sy + y, w, h]
        save_config(self.cfg)
        print(f"\n[바 위치 자동 감지] {self.cfg['bar_roi']} -> config.json 저장")
        return True

    def bar_state(self):
        """(잡는 구간 중심 x, 물고기 x). 못 찾으면 None."""
        c = self.cfg
        if not c["bar_roi"] and not self.find_bar():
            return None, None
        img = self.screen.grab(c["bar_roi"])
        fish_x = self.find_x(img, c["fish_color"])

        cols = np.nonzero(color_mask(img, c["bar_color"], c["bar_tolerance"]).any(axis=0))[0]
        if cols.size == 0:
            return None, fish_x
        left, right = int(cols.min()), int(cols.max())
        span = right - left
        if span > self.zone_w * 0.6:
            self.zone_w = max(self.zone_w, span)
            zone_x = (left + right) / 2
        elif self.zone_w > 0 and self.prev_zone is not None:
            # 괄호가 하나만 보임(물고기에 가림 등) -> 이전 위치 기준으로 어느 쪽인지 판단
            x = (left + right) / 2
            zone_x = x + self.zone_w / 2 if x < self.prev_zone else x - self.zone_w / 2
        else:
            return None, fish_x
        self.prev_zone = zone_x
        return zone_x, fish_x

    def gauge_ratio(self):
        c = self.cfg
        if not c["gauge_roi"]:
            return None
        img = self.screen.grab(c["gauge_roi"])
        return color_mask(img, c["gauge_color"], c["gauge_tolerance"]).sum() / c["gauge_full_pixels"]

    def durability_ok(self):
        c = self.cfg
        if not c["durability_roi"]:
            return True
        hue = durability_hue(self.screen.grab(c["durability_roi"]))
        self.log(f"내구도 hue={hue}")
        # hue 0 근처 = 빨강. 330 이상도 빨강 계열
        return hue is None or c["durability_red_hue"] < hue < 330

    # ---------- 단계 ----------
    def wait_bite(self):
        c = self.cfg
        self.sleep(c["cast_settle_sec"])
        counts, ys = [], []
        t_end = time.perf_counter() + 0.5
        while time.perf_counter() < t_end:
            self.check()
            n, y = self.bobber()
            if y is not None:
                counts.append(n)
                ys.append(y)
            time.sleep(0.02)
        if len(counts) < 5:
            self.log("찌 못 찾음")
            return False
        base_n, base_y = float(np.median(counts)), float(np.median(ys))
        self.log(f"기준 찌 픽셀={base_n:.0f} y={base_y:.1f}")

        deadline = time.perf_counter() + c["bite_timeout_sec"]
        next_log = 0.0
        while time.perf_counter() < deadline:
            self.check()
            n, y = self.bobber()
            if time.perf_counter() > next_log:
                self.log(f"찌 px={n} (기준 {base_n:.0f}, 입질<{base_n * c['bite_drop_ratio']:.0f})  "
                         f"y={'없음' if y is None else f'{y - base_y:+.1f}'} (입질>{c['bite_dip_px']})")
                next_log = time.perf_counter() + 0.25
            if n < base_n * c["bite_drop_ratio"] or (y is not None and y - base_y > c["bite_dip_px"]):
                self.log(f"입질! n={n} y={y}")
                return True
            time.sleep(0.01)
        self.log("입질 시간초과")
        return False

    def minigame(self):
        c = self.cfg
        deadline = time.perf_counter() + c["minigame_start_timeout_sec"]
        while True:
            self.check()
            bar_x, fish_x = self.bar_state()
            if fish_x is not None and bar_x is not None:
                break
            if time.perf_counter() > deadline:
                self.log("미니게임 안 뜸")
                return
            time.sleep(0.01)
        self.log("미니게임 시작")

        last_seen = time.perf_counter()
        prev_bar, prev_t, vel = bar_x, time.perf_counter(), 0.0
        try:
            while True:
                self.check()
                now = time.perf_counter()
                bar_x, fish_x = self.bar_state()

                g = self.gauge_ratio()
                if g is not None and g >= c["gauge_full_ratio"]:
                    self.log("게이지 가득 -> 낚음")
                    break

                if fish_x is None:
                    if now - last_seen > c["minigame_end_missing_sec"]:
                        break
                    continue
                last_seen = now

                if bar_x is None:
                    bar_x = prev_bar
                else:
                    dt = now - prev_t
                    if dt > 0:
                        vel = 0.7 * vel + 0.3 * (bar_x - prev_bar) / dt
                    prev_bar, prev_t = bar_x, now

                err = fish_x - (bar_x + vel * c["lead_sec"])
                if err < -c["deadzone_px"]:
                    self.set_shift(True)    # 왼쪽으로
                elif err > c["deadzone_px"]:
                    self.set_shift(False)   # 오른쪽으로
                self.log(f"zone={bar_x:.0f} fish={fish_x:.0f} err={err:.0f} shift={self.shift_down} gauge={g}")
                time.sleep(0.005)
        finally:
            self.set_shift(False)
        self.log("미니게임 종료")

        if c["reel_click_after_game"]:
            self.right_click()

    def cycle(self):
        if not self.durability_ok():
            self.running = False
            alert("낚싯대 내구도가 빨간색. 매크로 정지함.")
            raise Stop
        self.right_click()               # 던지기
        if self.wait_bite():
            self.right_click()           # 낚기
            self.minigame()
        else:
            self.right_click()           # 회수
        self.sleep(self.cfg["recast_delay_sec"])

    def run(self):
        print("F8: 시작/일시정지, F9: 종료")
        while not self.quit:
            if not self.running or time.perf_counter() < self.start_at:
                time.sleep(0.05)
                continue
            try:
                self.cycle()
            except Stop:
                self.set_shift(False)
        self.set_shift(False)


def preview(cfg):
    """입력 없이 감지값만 출력. 창을 띄우지 않으니 게임 화면을 가리지 않음."""
    m = Macro(cfg)
    print("미리보기 (F9 또는 Ctrl+C 종료). 게임 창을 띄워두고 값 변화를 봐")
    try:
        while not m.quit:
            n, y = m.bobber()
            info = f"찌 px={n:4d} y={'-' if y is None else f'{y:5.1f}'}"
            zone, fish = m.bar_state()
            if not cfg["bar_roi"]:
                info += " | 바: 미니게임 뜨면 자동 감지"
            info += f" | 구간={'-' if zone is None else f'{zone:5.0f}'} 물고기={'-' if fish is None else f'{fish:5.0f}'}"
            g = m.gauge_ratio()
            if g is not None:
                info += f" | 게이지={g:4.0%}"
            if cfg["durability_roi"]:
                hue = durability_hue(m.screen.grab(cfg["durability_roi"]))
                info += f" | 내구도 hue={'-' if hue is None else f'{hue:3.0f}'}"
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
    missing = [k for k in ("bobber_roi", "bobber_color") if not cfg[k]]
    for k in ("gauge_roi", "durability_roi"):
        if not cfg[k]:
            print(f"경고: {k} 미설정 -> 해당 기능 꺼짐")
    if missing:
        raise SystemExit(f"캘리브레이션 필요: {missing} -> python calibrate.py 먼저 실행")

    if args.preview:
        preview(cfg)
    else:
        Macro(cfg, args.debug).run()


if __name__ == "__main__":
    main()
