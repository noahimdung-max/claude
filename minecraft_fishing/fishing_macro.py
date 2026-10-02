"""마인크래프트 낚시 매크로.

F8: 시작/일시정지   F9: 종료
python fishing_macro.py            # 실행
python fishing_macro.py --preview  # 검출 결과 실시간 확인(입력 안 보냄)
python fishing_macro.py --debug    # 실행 + 로그
"""
import argparse
import time

import cv2
import keyboard
import numpy as np
import pydirectinput

from common import Screen, color_mask, load_config

pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False


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
        keyboard.add_hotkey("f8", self.toggle)
        keyboard.add_hotkey("f9", self.request_quit)

    # ---------- 입력 ----------
    def toggle(self):
        self.running = not self.running
        print("[시작]" if self.running else "[일시정지]")

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

    def bar_state(self):
        img = self.screen.grab(self.cfg["bar_roi"])
        return self.find_x(img, self.cfg["bar_color"]), self.find_x(img, self.cfg["fish_color"])

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
        while time.perf_counter() < deadline:
            self.check()
            n, y = self.bobber()
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
                self.log(f"bar={bar_x:.0f} fish={fish_x:.0f} err={err:.0f} shift={self.shift_down}")
                time.sleep(0.005)
        finally:
            self.set_shift(False)
        self.log("미니게임 종료")

        if c["reel_click_after_game"]:
            self.right_click()

    def cycle(self):
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
            if not self.running:
                time.sleep(0.05)
                continue
            try:
                self.cycle()
            except Stop:
                self.set_shift(False)
        self.set_shift(False)


def preview(cfg):
    screen = Screen(cfg["monitor"])
    tol = cfg["tolerance"]
    print("미리보기: q 종료")
    while True:
        b = screen.grab(cfg["bobber_roi"])
        bm = color_mask(b, cfg["bobber_color"], tol)
        bv = b.copy()
        bv[bm] = (0, 255, 0)

        g = screen.grab(cfg["bar_roi"])
        gv = g.copy()
        for color, mark in ((cfg["bar_color"], (255, 0, 0)), (cfg["fish_color"], (0, 0, 255))):
            m = color_mask(g, color, tol)
            gv[m] = mark
            xs = np.nonzero(m)[1]
            if xs.size >= cfg["min_pixels"]:
                cv2.line(gv, (int(xs.mean()), 0), (int(xs.mean()), gv.shape[0] - 1), mark, 1)

        cv2.imshow("bobber (green=detected)", cv2.resize(bv, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
        cv2.imshow("bar (blue=bar, red=fish)", cv2.resize(gv, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
        print(f"\rbobber px={int(bm.sum()):5d}", end="")
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    missing = [k for k in ("bobber_roi", "bobber_color", "bar_roi", "bar_color", "fish_color") if not cfg[k]]
    if missing:
        raise SystemExit(f"캘리브레이션 필요: {missing} -> python calibrate.py 먼저 실행")

    if args.preview:
        preview(cfg)
    else:
        Macro(cfg, args.debug).run()


if __name__ == "__main__":
    main()
