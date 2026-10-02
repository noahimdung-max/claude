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

from pathlib import Path

from common import (Screen, bobber_mask, bracket_mask, bracket_runs, color_mask, durability_value, fish_blob_x, fish_mask,
                    gauge_present, load_config, load_subtitle_template, locate_bar, match_score, save_config,
                    split_view, view_roi)

pydirectinput.PAUSE = 0
pydirectinput.FAILSAFE = False


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


class Stop(Exception):
    pass


class Macro:
    def __init__(self, cfg, debug=False, out=print, hotkeys=True):
        self.cfg = cfg
        self.debug = debug
        self.out = out
        self.screen = Screen(cfg["monitor"])
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
                      "sub": None, "gauge": None, "dura": None, "caught": 0}
        if hotkeys:
            import keyboard
            keyboard.add_hotkey("f8", self.toggle)
            keyboard.add_hotkey("f9", self.request_quit)

    # ---------- 입력 ----------
    def missing_setup(self):
        c = self.cfg
        if c["bite_mode"] == "subtitle":
            if not c["subtitle_roi"] or self.subtitle_template() is None:
                return "입질 자막을 먼저 지정해야 함"
        elif not c["bobber_roi"]:
            return "찌 영역을 먼저 지정해야 함"
        return None

    def toggle(self):
        if not self.running and self.missing_setup():
            self.out(self.missing_setup())
            return
        self.running = not self.running
        if self.running:
            self.start_at = time.perf_counter() + self.cfg["start_delay_sec"]
            self.out(f"[시작] {self.cfg['start_delay_sec']:.0f}초 뒤 동작. 게임 창 클릭해둬")
        else:
            self.out("[정지]")

    def request_quit(self):
        self.quit = True

    def log(self, *a):
        if self.debug:
            self.out(" ".join(str(x) for x in a))

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
        save_config(self.cfg)
        self.out(f"[바 위치 자동 감지] {self.cfg['bar_roi']} 저장됨")
        return True

    def bobber_search_mask(self):
        img = self.screen.grab(self.cfg["bobber_roi"])
        return img, bobber_mask(img, self.cfg)

    def locate_bobber(self):
        """던진 뒤 탐색 영역에서 새로 나타난 빨간 덩어리(찌)를 찾아 추적 영역 반환."""
        c = self.cfg
        sx, sy, sw, sh = c["bobber_roi"]
        deadline = time.perf_counter() + 3.0
        img = None
        while time.perf_counter() < deadline:
            self.check()
            img, m = self.bobber_search_mask()
            if self.pre_mask is not None and self.pre_mask.shape == m.shape:
                m = m & ~self.pre_mask          # 던지기 전부터 있던 빨간 물체 제외
            n, _, st, _ = cv2.connectedComponentsWithStats(
                cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)))
            if n > 1:
                i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
                x, y, w, h, area = (int(v) for v in st[i])
                if area >= c["min_pixels"]:
                    self.bobber_h = h
                    mx, my = max(10, w), max(10, 2 * h)
                    x0, y0 = max(0, x - mx), max(0, y - my)
                    x1, y1 = min(sw, x + w + mx), min(sh, y + h + 2 * my)
                    return [sx + x0, sy + y0, x1 - x0, y1 - y0]
            time.sleep(0.05)
        if img is not None:
            self.save_debug(img, "debug_bobber.png", "찌 못 찾음")
        return None

    def save_debug(self, img, name="debug_bar.png", what=None):
        from PIL import Image
        path = Path(__file__).with_name(name)
        Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(path)
        if what:
            self.out(f"[{what}] 탐색 화면을 {path.name} 로 저장했어 -> 이 파일 보내줘")
            return
        f, b = fish_mask(img, self.cfg), bracket_mask(img, self.cfg)
        self.out(f"[바 못 찾음] 물고기색 {int(f.sum())}px, 괄호색 {int(b.sum())}px 감지. "
                 f"탐색 화면을 {path.name} 로 저장했어 -> 이 파일 보내줘")

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
        bar, above = split_view(self.screen.grab(vr), bar_row)
        fish_x = fish_blob_x(bar, c)
        # 미니게임 판정: 바 위 가운데 초록 게이지 + 바 안의 물고기 (평소 경험치 바/핫바 아이템과 구분)
        active = fish_x is not None and gauge_present(above, c)
        if not active:
            return False, None, None

        br = bracket_runs(bar, c)
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
            self.sub_tmpl = load_subtitle_template()
        return self.sub_tmpl

    def subtitle_score(self):
        c = self.cfg
        t = self.subtitle_template()
        if t is None or not c["subtitle_roi"]:
            self.stats["sub"] = None
            return None
        s = match_score(self.screen.grab(c["subtitle_roi"]), t)
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
        d = durability_value(self.screen.grab(c["durability_roi"]), c["durability_max"]) if c["durability_roi"] else None
        self.stats["dura"] = d
        return d

    def durability_ok(self):
        d = self.durability_reading()
        if d is None:
            return True
        val, kind = d
        self.log(f"내구도 {val}/{self.cfg['durability_max']} ({kind})")
        if kind == "low":                # 1~2 는 화면으로 구분이 안 됨 -> 무조건 멈춤
            return False
        return val > self.cfg["durability_stop"]

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
        return self.wait_bite_bobber()

    def wait_bite_subtitle(self):
        """자막 '낚시찌 첨벙'이 뜨면 입질. (기존 마크 자동낚시 프로그램들이 쓰는 방식)"""
        c = self.cfg
        thr = c["subtitle_threshold"]
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
                self.out(f"입질! (자막 일치 {s:.0%})")
                return True
            time.sleep(0.03)
        self.out("입질 시간초과 -> 다시 던짐")
        return False

    def wait_bite_bobber(self):
        """(예비) 찌 화면 감시. 찌의 평소 흔들림을 재서 그보다 확실히 크게 변할 때만 입질."""
        c = self.cfg
        self.state = "찌 자리잡는 중"
        self.sleep(c["cast_settle_sec"])
        track = self.locate_bobber()
        if track is None:
            self.out("찌를 못 찾음 -> 다시 던짐 (물 쪽을 보고 있는지, 찌 영역이 물을 덮는지 확인)")
            return False
        self.log(f"찌 추적 영역 {track}")
        counts, ys = [], []
        t_end = time.perf_counter() + 1.0
        while time.perf_counter() < t_end:
            self.check()
            n, y = self.bobber(track)
            if y is not None:
                counts.append(n)
                ys.append(y)
            time.sleep(0.02)
        if len(counts) < 10:
            self.out("찌가 계속 안 보임 -> 다시 던짐")
            return False
        base_n, base_y = float(np.median(counts)), float(np.median(ys))
        noise_y, noise_n = max(ys) - min(ys), max(counts) - min(counts)
        dip_thr = max(c["bite_dip_px"], 2 * noise_y + 2, 0.35 * self.bobber_h)
        drop_thr = min(base_n * c["bite_drop_ratio"], base_n - 3 * noise_n)
        self.log(f"기준 찌 px={base_n:.0f} (입질<{drop_thr:.0f}), 흔들림 {noise_y:.1f}px (입질>{dip_thr:.1f}px)")

        self.state = "입질 기다리는 중 (찌)"
        deadline = time.perf_counter() + c["bite_timeout_sec"]
        hits, next_log = 0, 0.0
        while time.perf_counter() < deadline:
            self.check()
            n, y = self.bobber(track)
            dip = None if y is None else y - base_y
            if time.perf_counter() > next_log:
                self.log(f"찌 px={n} 내려감={'-' if dip is None else f'{dip:+.1f}'}")
                next_log = time.perf_counter() + 0.25
            bite = n < drop_thr or (dip is not None and dip > dip_thr)
            hits = hits + 1 if bite else 0
            if hits >= c["bite_confirm_frames"]:
                self.out(f"입질! (찌 px {base_n:.0f}->{n}, 내려감 {'-' if dip is None else f'{dip:.1f}'}px)")
                return True
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
                    self.out("미니게임 안 뜸 (헛챔질이었거나, 바 위치가 틀렸으면 '자동'으로 다시 찾기)")
                return
            time.sleep(0.01)
        self.state = "미니게임 중"
        self.out("미니게임 시작")

        last_active = time.perf_counter()
        prev_zone, prev_t, vel = zone, time.perf_counter(), 0.0
        try:
            while True:
                self.check()
                now = time.perf_counter()
                active, zone, fish = self.bar_state()

                g = self.gauge_ratio()
                if g is not None and g >= c["gauge_full_ratio"]:
                    self.log("게이지 가득 -> 낚음")
                    break

                if not active:
                    if now - last_active > c["minigame_end_missing_sec"]:
                        break
                    continue
                last_active = now

                if zone is None:
                    if prev_zone is None:
                        continue
                    zone = prev_zone
                elif prev_zone is not None:
                    dt = now - prev_t
                    if dt > 0:
                        vel = 0.7 * vel + 0.3 * (zone - prev_zone) / dt
                    prev_zone, prev_t = zone, now
                else:
                    prev_zone, prev_t = zone, now

                err = fish - (zone + vel * c["lead_sec"])
                if err < -c["deadzone_px"]:
                    self.set_shift(True)    # 왼쪽으로
                elif err > c["deadzone_px"]:
                    self.set_shift(False)   # 오른쪽으로
                self.log(f"zone={zone:.0f} fish={fish:.0f} err={err:.0f} shift={self.shift_down} gauge={g}")
                time.sleep(0.005)
        finally:
            self.set_shift(False)
        self.stats["caught"] += 1
        self.out(f"미니게임 끝 (총 {self.stats['caught']}회)")

        if c["reel_click_after_game"]:
            self.right_click()

    def cycle(self):
        if not self.durability_ok():
            self.running = False
            val, kind = self.stats["dura"]
            now = "1~2" if kind == "low" else str(val)
            msg = f"낚싯대 내구도 {now}/{self.cfg['durability_max']} (멈춤 기준 {self.cfg['durability_stop']} 이하) -> 정지"
            self.out("[알림] " + msg)
            alert(msg)
            raise Stop
        self.state = "던지는 중"
        if self.cfg["bite_mode"] == "bobber":
            _, m = self.bobber_search_mask()
            self.pre_mask = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        self.right_click()               # 던지기
        if self.wait_bite():
            self.right_click()           # 낚기
            self.minigame()
        else:
            self.right_click()           # 회수
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
                self.cycle()
            except Stop:
                pass
            except Exception:
                self.running = False
                self.out("오류로 정지:\n" + traceback.format_exc())
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
