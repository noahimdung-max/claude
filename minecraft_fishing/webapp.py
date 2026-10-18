"""마인크래프트 낚시 매크로 - 웹 화면 버전 (pywebview + Edge WebView2).

화면은 webui/ 의 HTML/CSS/JS. 매크로 동작(fishing_macro.Macro)은 tk 버전과 똑같이 씀.
화면 -> 파이썬: Bridge (js_api) 메서드.  파이썬 -> 화면: window.App.push(종류, 데이터).
실행: python webapp.py
"""
import base64
import ctypes
import datetime as dt
import json
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

try:  # 고해상도 모니터에서 좌표 맞추기 (tk 버전과 같게, 창 만들기 전에)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import keyboard
import numpy as np
import webview

from common import (BOBBER_PACK_VERSIONS, BOBBER_STYLES, ANVIL_PATH, SUBTITLE_PATH, bobber_candidates, bobber_style,
                    write_bobber_pack, Screen, find_bobber, bracket_mask, durability_value, fish_mask, gauge_present,
                    load_config, make_subtitle_template, save_config, save_subtitle_template, split_view,
                    subtitle_search_roi, view_roi, load_history, read_number, hotbar_points, snap_slot,
                    detect_gui_scale, DATA_DIR)
import analysis
from fishing_macro import MEMLOG, Macro, notify, save_error
import winapi
from winapi import IS_WIN

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def app_version():
    """exe 이름에서 버전 (MinecraftFishingMacro-v1.9.0.exe -> 1.9.0). 소스 실행이면 dev."""
    import re
    m = re.search(r"-v([\w.]+)\.exe$", sys.executable) if getattr(sys, "frozen", False) else None
    return m.group(1) if m else "dev"

SIZES = {"small": (900, 660), "mid": (1060, 780), "large": (1280, 900)}
LAYOUT = 2                                # 화면 배치 버전: 바뀌면 예전에 기억한 창 크기는 안 씀 (세로로 긴 창 -> 가로 창)
MINI_SIZE = (400, 230)

ITEM_SCENES = {
    "subtitle": "직접 낚시하다 입질 와서 자막 '낚시찌 ... 첨벙'이 떴을 때",
    "bobber": "물을 바라보고 찌가 떠 있을 때",
    "rod": "핫바에 낚싯대 내구도 줄이 보일 때",
    "bar": "미니게임 바가 떠 있을 때 (직접 낚시하면서)",
    "repair": "모루 수리 창을 연 상태 (낚싯대·실 넣기 전, 빈 창)",
    "gold": "골드 숫자가 보이는 게임 화면",
}

ADV_KEYS = ["subtitle_threshold", "bite_confirm_frames", "bite_drop_ratio", "bite_dip_px", "tolerance", "deadzone_px",
            "left_click_cps", "lead_sec", "cast_settle_sec", "bite_timeout_sec", "recast_delay_sec",
            "start_delay_sec", "max_fails"]

_POLLER = None


def hotkey(key, fn, gap=0.4):
    """F7/F8/F12 단축키 (tk 버전과 같은 방식: 윈도우에선 키 상태를 직접 물어봄)."""
    if IS_WIN:
        global _POLLER
        if _POLLER is None:
            _POLLER = winapi.KeyPoller(gap=gap).start()
        _POLLER.add(key, fn)
        return
    last = [0.0]

    def on(e):
        now = time.perf_counter()
        if now - last[0] >= gap:
            last[0] = now
            fn()
    keyboard.on_press_key(key, on, suppress=False)


def virtual_screen():
    """모든 모니터를 합친 영역 (x, y, w, h). 예전엔 주 모니터만 봐서 왼쪽 모니터에 둔 창을 '화면 밖'으로 보고 가운데로 옮겼음."""
    try:
        m = ctypes.windll.user32.GetSystemMetrics
        return m(76), m(77), m(78), m(79)
    except Exception:
        return 0, 0, 1920, 1080


def png_b64(img, max_size=None, nearest=False):
    """BGR numpy -> data URL (max_size 안에 맞게 줄이거나 늘림)."""
    h, w = img.shape[:2]
    if max_size:
        s = min(max_size[0] / w, max_size[1] / h)
        vw, vh = max(1, round(w * s)), max(1, round(h * s))
        if (vw, vh) != (w, h):
            img = cv2.resize(img, (vw, vh), interpolation=cv2.INTER_NEAREST if (s >= 1 or nearest) else cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(img))
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def anim_key(m, recent_catch):
    """매크로 상태 -> 캐릭터 애니메이션 (대기/던지기/기다리기/입질/끌어올리기/낚음)."""
    if not m or not m.running:
        return "idle"
    if recent_catch:
        return "caught"
    st = m.state
    if "던지는" in st:
        return "cast"
    if "자리잡는" in st or "입질 기다리는" in st:
        return "wait"
    if "미니게임 기다리는" in st:
        return "bite"
    if "미니게임 중" in st:
        return "reel"
    return "idle"


class Bridge:
    """화면(JS)에서 부르는 함수들. 이름이 _ 로 시작하는 건 화면에 안 보임."""

    def __init__(self, app):
        self._app = app

    def ready(self):
        return self._app.initial()

    def toggle(self):
        self._app.toggle()

    def set_page(self, page):
        self._app.page = page
        self._app.push_page(page)

    def set_cfg(self, key, value):
        return self._app.set_cfg(key, value)

    def save_adv(self, values):
        return self._app.save_adv(values)

    def begin_set(self, item, capture="live"):
        self._app.begin_set(item, capture)

    def cancel_set(self):
        self._app.waiting_item = None
        self._app.push("guide", None)

    def reset_bar(self):
        self._app.reset_bar()

    def make_pack(self):
        threading.Thread(target=self._app.guard(self._app.make_bobber_pack), daemon=True).start()

    def save_hook(self, url, each):
        self._app.save_hook(url, each)

    def test_hook(self, url, each):
        self._app.test_hook(url, each)

    def run_analysis(self):
        return self._app.run_analysis()

    def history(self):
        return self._app.history()

    def set_top(self, on):
        self._app.set_top(bool(on))

    def set_size(self, preset):
        self._app.set_size(preset)

    def set_mini(self, on):
        self._app.set_mini(bool(on))

    def pick_result(self, token, result):
        self._app.answer(token, result)

    def answer(self, token, value):
        self._app.answer(token, value)

    def rod_click(self, kind, n):
        self._app.rod_click(kind, int(n))

    def use_angle(self, sens, yaw, pitch):
        self._app.use_angle(sens, yaw, pitch)

    def start_turn_record(self):
        self._app.start_turn_record()

    def test_turn(self):
        self._app.test_turn()

    def check_now(self):
        self._app.check_now()

    def quit(self):
        self._app.close()


class WebApp:
    def __init__(self):
        self.cfg = load_config()
        self.q = queue.Queue()
        self.f7 = threading.Event()
        self.quit_req = threading.Event()
        self.waiting_item = None
        self.turn_stage = 0
        self.page = "home"
        self.mini = False
        self.macro = None
        self.window = None
        self.loaded = threading.Event()
        self.waits = {}                                   # 화면 답을 기다리는 것 (영역 지정·질문)
        self._last_toggle = 0.0
        self._last_caught = None
        self._catch_until = 0.0
        self._img_t = 0.0
        self._closing = False
        self._early_logs = []
        self.cfg.setdefault("win_preset", "mid")
        self.cfg.setdefault("topmost", True)
        self.cfg.setdefault("remember_window", True)

    # ---------- 화면과 주고받기 ----------
    def push(self, kind, data=None):
        if not self.loaded.is_set() and kind == "log":
            self._early_logs.append(data)                 # 화면이 뜨기 전 기록은 모아뒀다가 처음에 보냄
            return
        if not self.window or not self.loaded.is_set() or self._closing:
            return
        try:
            self.window.evaluate_js(f"window.App && window.App.push({json.dumps(kind)}, {json.dumps(data, ensure_ascii=False)})")
        except Exception:
            pass

    def guard(self, fn):
        """버튼 하나가 오류를 내도 앱은 계속 (오류는 error.txt + 알림)."""
        def run(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception:
                save_error(traceback.format_exc())
                self.log("오류가 났어 (error.txt 에 남김)", "bad")
        return run

    def log(self, msg, tag=None):
        if tag is None:
            tag = ("bad" if ("오류" in msg or "알림" in msg or "정지 ->" in msg) else
                   "good" if ("입질" in msg or "끝" in msg or "완료" in msg or "감지" in msg) else
                   "warn" if ("시작" in msg or "F7" in msg) else None)
        line = msg.splitlines()[0] if msg else ""
        self.push("log", {"time": time.strftime("%H:%M"), "text": line, "tag": tag or "info"})

    def alert(self, title, msg, kind="info"):
        self.push("dialog", {"title": title, "text": msg, "kind": kind})

    def _wait(self, kind, data):
        token = f"{time.time_ns()}"
        ev = threading.Event()
        self.waits[token] = [ev, None]
        data = dict(data, token=token)
        self.push(kind, data)
        while not ev.wait(0.2):
            if self._closing:
                return None
        return self.waits.pop(token)[1]

    def answer(self, token, value):
        w = self.waits.get(token)
        if w:
            w[1] = value
            w[0].set()

    def confirm(self, title, msg, yes="예", no="아니오"):
        return bool(self._wait("confirm", {"title": title, "text": msg, "yes": yes, "no": no}))

    def ask(self, img, guide, mode="rect", max_size=(1280, 720), ok_text="확인"):
        """영역 지정 창 (tk PickDialog 와 같은 결과): rect -> [x,y,w,h] / point -> (x,y) / view -> True·False·None."""
        h, w = img.shape[:2]
        s = min(max_size[0] / w, max_size[1] / h)
        url = png_b64(img, max_size)
        r = self._wait("pick", {"img": url, "w": w, "h": h, "guide": guide, "mode": mode, "ok": ok_text,
                                "pixel": s >= 1})
        if r is None or r is False:
            return r
        if mode == "view":
            return True
        if mode == "rect":
            x, y, rw, rh = (int(v) for v in r)
            x, y = max(0, min(w - 1, x)), max(0, min(h - 1, y))
            return [x, y, max(1, min(w - x, rw)), max(1, min(h - y, rh))]
        return (min(int(r[0]), w - 1), min(int(r[1]), h - 1))

    def ask_roi(self, img, name, precise=True):
        """1단계: 전체 화면에서 대충 -> 2단계: 확대해서 정확히 (tk 버전과 같음)."""
        r = self.ask(img, f"[{name}] {'1/2  ' if precise else ''}주변을 드래그로 감싸기")
        if not r or not precise:
            return r
        x, y, w, h = r
        H, W = img.shape[:2]
        m = max(10, max(w, h) // 3)
        x0, y0 = max(0, x - m), max(0, y - m)
        x1, y1 = min(W, x + w + m), min(H, y + h + m)
        r2 = self.ask(img[y0:y1, x0:x1], f"[{name}] 2/2  확대 화면에서 정확히 드래그", max_size=(1000, 500))
        if not r2:
            return None
        return [x0 + r2[0], y0 + r2[1], r2[2], r2[3]]

    # ---------- 처음 화면에 줄 것 ----------
    def public_cfg(self):
        c = self.cfg
        keys = ADV_KEYS + ["bite_mode", "bobber_style", "pack_version", "background", "durability_ignore",
                           "durability_stop_pct", "durability_max", "goal_count", "goal_minutes", "sneak_key",
                           "reel_click_after_game", "log_file", "discord_webhook", "notify_each_catch", "rod_swap",
                           "rod_slots", "exact_durability", "inv_check_every", "exact_slot", "repair_on",
                           "repair_rod_slot", "repair_string_slot", "repair_cost", "mouse_sens_pct", "repair_yaw",
                           "repair_pitch", "inv_full_stop", "inv_min_empty", "topmost", "win_preset",
                           "remember_window", "total_caught"]
        return {k: c.get(k) for k in keys}

    def initial(self):
        logs, self._early_logs = self._early_logs[-5:], []
        self.loaded.set()
        return {"cfg": self.public_cfg(), "status": self.status(), "version": app_version(),
                "packVersions": list(BOBBER_PACK_VERSIONS), "mini": self.mini, "logs": logs}

    def status(self):
        c = self.cfg
        done = {"subtitle": bool(c["subtitle_roi"] and SUBTITLE_PATH.exists()), "bobber": bool(c["bobber_roi"]),
                "rod": bool(c["durability_roi"])}
        mode = c["bite_mode"]
        need = {"subtitle": {"subtitle": "필수", "bobber": "안 씀"}.get(mode, "둘 중 하나"),
                "bobber": {"subtitle": "안 씀", "bobber": "필수"}.get(mode, "둘 중 하나")}
        out = {}
        for k, ok in done.items():
            if k == "rod" and not ok:
                out[k] = {"text": "자동 (선택한 칸)", "cls": "auto"}
            else:
                out[k] = {"text": "지정됨" if ok else f"미설정 ({need[k]})",
                          "cls": "ok" if ok else ("no" if need[k] == "필수" else "off")}
        out["bar"] = {"text": "찾음" if c["bar_roi"] else "자동으로 찾음", "cls": "ok" if c["bar_roi"] else "auto"}
        return out

    def refresh_status(self):
        self.push("status", self.status())

    # ---------- 실시간 상태 ----------
    def snapshot(self):
        m = self.macro
        if not m:
            return None
        s = m.stats
        now = time.time()
        if s["caught"] != self._last_caught and self._last_caught is not None:
            self._catch_until = now + 1.8
        self._last_caught = s["caught"]
        elapsed = (now - s["started"]) if (m.running and s["started"]) else getattr(self, "_elapsed", 0.0)
        self._elapsed = elapsed
        caught = m.run_caught
        bins = [0] * 12
        for t in s["catch_times"]:
            k = int((now - t) // 300)
            if 0 <= k < 12:
                bins[11 - k] += 1
        c = self.cfg
        if c["bite_mode"] == "subtitle" or (c["bite_mode"] == "both" and not c["bobber_roi"]):
            sub = s["sub"]
            bite = {"text": "-" if sub is None else f"자막 {sub:.0%}", "hit": sub is not None and sub >= c["subtitle_threshold"]}
        else:
            bite = {"text": "-" if not c["bobber_roi"] else f"찌 {s['bobber_n']}px", "hit": False}
        dura = None
        if s["dura"] is not None:
            val, kind = s["dura"]
            mx = s.get("dura_max") or c["durability_max"]
            stop = mx * c["durability_stop_pct"] / 100
            dura = {"text": f"{'1~2' if kind == 'low' else val}/{mx}" + (" (정밀)" if kind == "exact" else ""),
                    "frac": 0 if kind == "low" else min(1, val / max(1, mx)),
                    "ignore": c["durability_ignore"],
                    "danger": not c["durability_ignore"] and (kind == "low" or val <= stop)}
        roi = c["bar_roi"]
        bar = {"roi": bool(roi), "active": bool(s["active"]), "zone": s["zone"], "fish": s["fish"],
               "zw": max(m.zone_w, 4) if roi else 0, "w": roi[2] if roi else 1}
        snap = {"running": m.running, "state": m.state, "anim": anim_key(m, now < self._catch_until),
                "caught": caught, "elapsed": int(elapsed), "casts": s["casts"], "caughtAll": s["caught"],
                "perHour": round(caught / (elapsed / 3600)) if elapsed > 60 else 0,
                "rate": round(s["caught"] / s["casts"] * 100) if s["casts"] else 0,
                "total": c.get("total_caught", 0), "colors": s["colors"], "bins": bins, "bite": bite,
                "dura": dura, "bar": bar, "showLive": c["bite_mode"] in ("bobber", "both"),
                "goalN": c["goal_count"], "goalM": c["goal_minutes"]}
        if snap["showLive"] and self.page == "home" and not self.mini:
            snap["trace"] = [[round(a, 3), round(b, 3)] for a, b in (s.get("trace") or [])[-100:]]
            img = s.get("bobber_view")
            if img is not None and getattr(img, "size", 0) and now - self._img_t > 0.25:
                self._img_t = now
                snap["bobberImg"] = png_b64(img, (180, 90), nearest=True)
        return snap

    def rod_data(self):
        m, c = self.macro, self.cfg
        cur = m.stats.get("slot") if m else None
        dep = sorted(m.depleted) if m else []
        dura = None
        if m and cur and m.stats.get("dura"):
            val, kind = m.stats["dura"]
            mx = m.stats.get("dura_max") or c["durability_max"]
            dura = 0.05 if kind == "low" else min(1, val / max(1, mx))
        parts = []
        if c.get("repair_turn"):
            parts.append(f"방향: 기록됨 ({c['repair_turn'][0]}, {c['repair_turn'][1]})")
        elif c.get("repair_yaw") is not None:
            parts.append(f"방향: 각도 {c['repair_yaw']:g}° / {c.get('repair_pitch', 0):g}°")
        else:
            parts.append("방향: 아직 없음")
        parts.append("수리 창: " + ("지정됨" if c.get("repair_points") else "아직 없음"))
        parts.append("골드 영역: " + ("지정됨" if c.get("gold_roi") else "없음 (확인 안 함)"))
        ready = bool((c.get("repair_turn") or c.get("repair_yaw") is not None) and c.get("repair_points"))
        inv_map = list(m.inv_map) if (m and m.inv_map is not None) else None
        return {"cur": cur, "depleted": dep, "dura": dura, "rodSlots": c["rod_slots"], "rodSwap": c["rod_swap"],
                "exactSlot": 0 if c["rod_swap"] else c.get("exact_slot", 0), "repairRod": c["repair_rod_slot"],
                "repairString": c["repair_string_slot"], "repairText": None if self.turn_stage else "  ·  ".join(parts),
                "repairReady": ready, "invMap": inv_map,
                "invNote": (m.inv_note if (m and m.inv_empty is not None) else "아직 확인 안 함"),
                "invBad": bool(m and m.inv_empty is not None and m.inv_empty <= c["inv_min_empty"])}

    def push_page(self, page):
        if page == "rod":
            self.push("rod", self.rod_data())
        elif page == "log":
            self.push("history", self.history())

    def history(self):
        hist = self.macro.history if self.macro else load_history()
        return {"hist": hist, "today": dt.date.today().isoformat()}

    # ---------- 매크로 스레드 / 화면 갱신 ----------
    def worker(self):
        self.macro = Macro(self.cfg, out=self.q.put, hotkeys=False)
        self.macro.run()

    def ticker(self):
        n = 0
        while not self._closing:
            try:
                self.tick(n)
            except Exception:
                if not getattr(self, "_tick_err", False):
                    self._tick_err = True
                    save_error(traceback.format_exc())
            n += 1
            time.sleep(0.1)

    def tick(self, n):
        if self.quit_req.is_set():
            self.close()
            return
        while not self.q.empty():
            self.log(self.q.get())
        if self.f7.is_set() and self.turn_stage:
            self.f7.clear()
            self.turn_record_f7()
        if self.f7.is_set():
            self.f7.clear()
            if self.waiting_item:
                item, self.waiting_item = self.waiting_item, None
                img = Screen(self.cfg["monitor"]).full()
                self.push("guide", None)
                self.bring_front()
                threading.Thread(target=self.guard(self.run_set), args=(item, img), daemon=True).start()
        snap = self.snapshot()
        if snap:
            self.push("state", snap)
        if self.page == "rod" and n % 5 == 0:
            self.push("rod", self.rod_data())
        if self.page == "log" and n % 30 == 0:
            self.push("history", self.history())
        if self.cfg["bar_roi"] and n % 10 == 0:
            st = self.status()
            if st != getattr(self, "_last_status", None):
                self._last_status = st
                self.push("status", st)

    def bring_front(self):
        try:
            self.window.restore()
            self.window.show()
            self.window.on_top = True
            if not self.cfg.get("topmost") and not self.mini:
                threading.Timer(0.5, lambda: setattr(self.window, "on_top", False)).start()
        except Exception:
            pass

    # ---------- 시작/정지 ----------
    def toggle(self):
        """시작/정지. 꾹 누르면 켜졌다 꺼지는 걸 막음 (0.5초 안 재입력 무시)."""
        now = time.perf_counter()
        if now - self._last_toggle < 0.5:
            return
        self._last_toggle = now
        if self.macro:
            self.macro.toggle()

    # ---------- 설정 ----------
    BOOL_KEYS = {"background", "durability_ignore", "reel_click_after_game", "log_file", "notify_each_catch",
                 "rod_swap", "exact_durability", "repair_on", "inv_full_stop", "remember_window"}
    INT_KEYS = {"goal_count": (0, 100000), "goal_minutes": (0, 100000), "durability_stop_pct": (1, 99),
                "durability_max": (1, 2000), "inv_check_every": (1, 200), "inv_min_empty": (0, 35),
                "repair_cost": (0, 1000000)}

    def set_cfg(self, key, value):
        c = self.cfg
        if key in self.BOOL_KEYS:
            c[key] = bool(value)
        elif key in self.INT_KEYS:
            try:
                v = int(float(value))
            except (TypeError, ValueError):
                return False                              # 입력 중 (빈칸 등)
            lo, hi = self.INT_KEYS[key]
            if not lo <= v <= hi:
                return False
            c[key] = v
        elif key == "bite_mode" and value in ("subtitle", "bobber", "both"):
            c[key] = value
            self.log("입질 감지: " + {"subtitle": "자막만", "bobber": "찌 화면만"}.get(value, "자막 + 찌 (먼저 잡히는 쪽)"), "warn")
            self.refresh_status()
        elif key == "bobber_style" and value in BOBBER_STYLES:
            c[key] = value
            if self.macro:
                self.macro.pre_mask = None
            self.log("찌 색: " + BOBBER_STYLES[value]["name"] + ("" if value == "vanilla" else " (마크에 리소스팩을 켜야 해)"), "warn")
        elif key == "pack_version" and value in ("26.1.2", "26.3", "both", "all"):
            c[key] = value
        elif key == "sneak_key" and value in ("shift", "ctrl"):
            c[key] = value
            self.log(f"웅크리기 키: {'Ctrl' if value == 'ctrl' else 'Shift'}", "good")
        else:
            return False
        save_config(c)
        if key == "background":
            self.log("백그라운드 모드 켬: 마크에서 F3+P 꼭 누르고, 창 최소화는 하지 마" if c[key] else "백그라운드 모드 끔",
                     "warn" if c[key] else None)
        if key == "repair_on" and c[key] and c["background"]:
            self.log("자동 수리는 일반 모드에서만 돼 ('다른 창 쓰면서 낚시'는 꺼줘)", "warn")
        if key == "rod_swap" and c[key] and c["durability_ignore"]:
            self.log("자동 교체는 내구도를 봐야 해: 낚시 탭의 '안 봄'을 꺼줘", "warn")
        if key in ("rod_swap", "repair_on", "exact_durability"):
            self.push("rod", self.rod_data())
        return True

    def save_adv(self, values):
        """세부 설정 저장 (tk 의 save_adv 와 같음: 숫자 13개 + 웅크리기 키 + 체크 2개)."""
        try:
            new = {}
            for k in ADV_KEYS:
                v = float(values[k])
                new[k] = int(v) if isinstance(self.cfg[k], int) and v.is_integer() else v
        except (KeyError, TypeError, ValueError):
            self.alert("오류", "숫자만 입력해줘", "bad")
            return False
        self.cfg.update(new)
        self.cfg["reel_click_after_game"] = bool(values.get("reel_click_after_game"))
        if values.get("sneak_key") in ("shift", "ctrl"):
            self.cfg["sneak_key"] = values["sneak_key"]
        self.cfg["log_file"] = bool(values.get("log_file"))
        save_config(self.cfg)
        self.log("세부 설정 저장 완료!", "good")
        return True

    def reset_bar(self):
        self.cfg["bar_roi"] = None
        if self.macro:
            self.macro.zone_w, self.macro.prev_zone = 0, None
        save_config(self.cfg)
        self.refresh_status()
        self.log("바 자동 찾기 켜짐. 미니게임이 뜨면 찾아 (매크로 꺼둔 채 직접 낚시해도 찾음)", "warn")

    def save_hook(self, url, each):
        self.cfg["discord_webhook"] = (url or "").strip()
        self.cfg["notify_each_catch"] = bool(each)
        save_config(self.cfg)

    def test_hook(self, url, each):
        self.save_hook(url, each)
        if not self.cfg["discord_webhook"].startswith("https://"):
            self.alert("디스코드", "웹후크 주소(https://discord.com/api/webhooks/...)를 넣어줘", "warn")
            return
        notify(self.cfg["discord_webhook"], "낚시 매크로 알림 테스트!")
        self.log("디스코드 테스트 보냄 (채널에 메시지가 왔는지 확인)", "good")

    def run_analysis(self):
        events = [(t, tag, msg) for t, tag, msg in list(MEMLOG)]
        try:
            if len(events) >= 5:
                return analysis.report(events)
            return analysis.report_file(DATA_DIR / "macro.log")
        except Exception as e:                            # 분석이 틀려도 앱은 멀쩡해야 함
            return f"분석 중 오류: {e}"

    def make_bobber_pack(self):
        """찌 리소스팩 zip 을 마크 resourcepacks 폴더에 만듦 (폴더를 못 찾으면 고르게 함)."""
        chosen = bobber_style(self.cfg)
        st = chosen
        if st in ("auto", "vanilla"):
            st = "magenta" if self.confirm("찌 리소스팩", "어떤 색으로 만들까?", "형광 분홍 (추천)", "형광 연두") else "lime"
        folder = Path(os.environ.get("APPDATA", "")) / ".minecraft" / "resourcepacks"
        if not folder.is_dir():
            picked = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            if not picked:
                return
            folder = Path(picked[0] if isinstance(picked, (list, tuple)) else picked)
        pv = self.cfg.get("pack_version", "both")
        versions = ["26.1.2", "26.3"] if pv == "both" else [pv]
        paths = []
        try:
            for v in versions:
                paths.append(write_bobber_pack(folder, st, v))
        except OSError as e:
            self.alert("오류", f"리소스팩을 못 만들었어: {e}", "bad")
            return
        if chosen not in ("auto", "vanilla"):
            self.cfg["bobber_style"] = st
        self.cfg["pack_made"] = True
        save_config(self.cfg)
        name = BOBBER_STYLES[st]["name"]
        made = ", ".join(p.name for p in paths)
        self.push("packMade", f"만들었어: {made}  (폴더: {folder})")
        self.log(f"찌 리소스팩 만듦 ({name}): {made}", "good")
        pick = ("마크 리소스팩 목록에 두 개가 보여. 지금 쓰는 마크 버전에 맞는 걸 하나만 켜줘\n   (" + " / ".join(
            f"{BOBBER_PACK_VERSIONS[v]['name']}용: {p.name}" for v, p in zip(versions, paths)) + ")")
        self.alert("찌 리소스팩", f"만들었어!\n{folder}\n" + "\n".join(p.name for p in paths) + "\n\n"
                   "1) 마크 옵션 > 리소스팩 에서 " + (pick if len(paths) > 1 else f"'{paths[0].name}' 을") + " 오른쪽(켬)으로 옮기고 맨 위로 올리기\n"
                   "   ('호환 안 됨' 표시가 떠도 눌러서 켜면 돼)\n"
                   "2) 완료 누르면 적용돼. 안 바뀌면 F3+T\n"
                   "3) 낚싯대를 던져서 찌가 " + name + " 으로 보이면 성공. 찌 색 설정이 '자동'이면 알아서 맞춰 찾아\n"
                   "4) 설정 탭 '찌 영역'을 다시 지정하면 더 정확해", "good")

    # ---------- 화면 위치 지정 (F7) ----------
    def begin_set(self, item, capture="live"):
        if item not in ITEM_SCENES:
            return
        if self.macro and self.macro.running:
            self.alert("안내", "매크로를 먼저 정지해줘")
            return
        scene = ITEM_SCENES[item]
        if capture == "file":
            def from_file():
                paths = self.window.create_file_dialog(
                    webview.FileDialog.OPEN, file_types=("이미지 (*.png;*.jpg;*.jpeg;*.bmp;*.webp)",))
                if not paths:
                    return
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
                try:
                    from PIL import Image
                    img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()   # 한글 경로 지원
                except Exception as e:
                    self.alert("오류", f"이미지 열기 실패: {e}", "bad")
                    return
                self.run_set(item, img)
            threading.Thread(target=self.guard(from_file), daemon=True).start()
            return
        self.waiting_item = item
        self.f7.clear()
        self.push("guide", {"item": item, "text": f"게임에서 [{scene}] 장면을 띄우고 F7 !"})
        self.log(f"F7 기다리는 중: {scene}", "warn")

    def run_set(self, item, img):
        """영역 지정하는 동안만 창을 크게 (작은 창에선 게임 화면이 너무 작게 보임). 끝나면 원래 크기로."""
        w, prev = self.window, None
        if not self.mini:
            try:
                prev = (w.width, w.height)
                w.resize(*self.fit(1340, 940))
            except Exception:
                prev = None
        try:
            self.do_set(item, img)
        finally:
            if prev:
                w.resize(*prev)

    def sync_window(self):
        """지정 전에: 마크 창이 예전과 다르면 이미 지정한 위치들을 지금 창에 맞춰 둠."""
        if IS_WIN and self.macro and not self.macro.running:
            try:
                self.macro.follow_window()
            except Exception:
                pass

    def do_set(self, item, img):
        c = self.cfg
        self.sync_window()
        if item == "gold":
            rect = self.ask_roi(img, "골드 숫자만 (예: 30,979) 감싸기")
            if not rect:
                return
            x, y, w, h = rect
            val = read_number(img[y:y + h, x:x + w])
            c["gold_roi"] = rect
            save_config(c)
            self.log(f"골드 영역 지정: 지금 {val:,} 골드로 읽힘" if val is not None
                     else "골드 숫자를 못 읽었어. 숫자만 딱 맞게 다시 감싸줘", "good" if val is not None else "warn")
            self.push("rod", self.rod_data())
            return
        if item == "repair":
            names = [("in1", "낚싯대 넣는 칸 (왼쪽 첫 칸)"), ("in2", "실 넣는 칸 (가운데 칸)"),
                     ("out", "결과 칸 (화살표 오른쪽)"), ("ok", "✓ 수리 버튼"),
                     ("hot1", "아래 핫바 1번 칸"), ("hot9", "아래 핫바 9번 칸")]
            pts = {}
            for i, (k, name) in enumerate(names):
                pt = self.ask(img, f"[수리 창 {i + 1}/{len(names)}] {name} 가운데를 클릭", mode="point")
                if not pt:
                    return
                pts[k] = [int(pt[0]), int(pt[1])]
            if abs(pts["hot9"][0] - pts["hot1"][0]) < 40:
                self.alert("수리 창", "핫바 1번과 9번 칸을 다시 확인해줘 (너무 가까워)", "warn")
                return
            pitch = abs(pts["hot9"][0] - pts["hot1"][0]) / 8
            pts["hot"] = hotbar_points(img, pts["hot1"], pts["hot9"])
            for k in ("in1", "in2", "out"):
                pts[k] = snap_slot(img, pts[k], pitch)
            pts["screen"] = [img.shape[1], img.shape[0]]
            c["repair_points"] = pts
            save_config(c)
            self.log("수리 창 위치 지정 완료", "good")
            self.push("rod", self.rod_data())
            return
        if item == "subtitle":
            rect = self.ask_roi(img, "입질 자막 - '낚시찌 ... 첨벙' 글자 한 줄 전체 (화살표 < > 는 빼고)")
            if not rect:
                return
            x, y, w, h = rect
            made = make_subtitle_template(img[y:y + h, x:x + w])
            if made is None:
                self.alert("확인", "흰 자막 글자가 안 보여. 자막 글자 위를 다시 감싸줘.\n"
                                   "(설정 > 접근성 > 텍스트 배경 불투명도를 올리면 잘 보여)", "warn")
                return
            tmpl, (tx, ty, tw, th) = made
            if tw < 15 or th < 5:
                self.alert("확인", "너무 작게 잡혔어. 자막 글자 한 줄 전체를 감싸줘.", "warn")
                return
            save_subtitle_template(tmpl)
            c["subtitle_scale"] = detect_gui_scale(img)
            c["subtitle_roi"] = subtitle_search_roi([x + tx, y + ty, tw, th], img.shape[1], img.shape[0])
            if self.macro:
                self.macro.sub_tmpl = None
            self.log("입질 자막 설정 완료! (실시간 상태의 '입질 감지'가 자막 뜰 때 80% 넘으면 정상)", "good")

        elif item == "bobber":
            roi = self.ask_roi(img, "찌 영역 - 찌가 떨어질 수 있는 물 쪽을 넓게 (하트/핫바는 빼고)", precise=False)
            if not roi:
                return
            x, y, w, h = roi
            crop = img[y:y + h, x:x + w].copy()
            H, W = img.shape[:2]
            found, fst = None, None
            for st in bobber_candidates("auto"):
                f = find_bobber(crop, (W / 2 - x, H / 2 - y), max_side=max(40, int(0.075 * H)), style=st)
                if f and (found is None or st == bobber_style(c)):
                    found, fst = f, st
            if found:
                bx, by, bw, bh = found
                cv2.rectangle(crop, (bx - 4, by - 4), (bx + bw + 4, by + bh + 4), (0, 255, 0), 2)
                msg = f"초록 네모 = 찾은 찌 ({BOBBER_STYLES[fst]['name']}). 맞으면 확인"
                if bobber_style(c) not in ("auto", fst):
                    msg += (f"\n주의: 찌 색 설정은 '{BOBBER_STYLES[bobber_style(c)]['name']}' 인데 화면에선 "
                            f"'{BOBBER_STYLES[fst]['name']}' 로 보여. 리소스팩이 안 켜졌거나 찌 색 설정이 다른 거야")
            else:
                msg = "지금 화면에선 찌를 못 찾았어 (찌가 안 보이거나 너무 어두움).\n영역만 저장하려면 확인"
            if not self.ask(crop, msg, mode="view", max_size=(900, 500)):
                return
            c["bobber_roi"] = roi
            self.log("찌 설정 완료!", "good")

        elif item == "rod":
            roi = self.ask_roi(img, "내구도 줄 - 핫바 낚싯대 칸 아래 색깔 줄만")
            if not roi:
                return
            x, y, w, h = roi
            val, kind = durability_value(img[y:y + h, x:x + w], c["durability_max"])
            c["durability_roi"] = roi
            if kind == "full":
                self.log(f"내구도 설정됨. 지금은 내구도 줄이 안 보여서 최대({val})로 읽혀 (안 닳았으면 정상)", "warn")
            elif kind == "low":
                self.log("내구도 설정됨. 지금 내구도 1~2 (거의 부서짐)", "warn")
            else:
                self.log(f"내구도 설정 완료! 지금 {val}/{c['durability_max']}", "good")

        elif item == "bar":
            roi = self.ask_roi(img, "미니게임 바 - 하트/게이지 빼고 바 줄만")
            if not roi:
                return
            x, y, w, h = roi
            crop = img[y:y + h, x:x + w]
            f, b = fish_mask(crop, c), bracket_mask(crop, c)
            view = crop.copy()
            view[f] = (0, 0, 255)
            view[b] = (0, 255, 0)
            vr, row = view_roi(roi)
            vx, vy, vw, vh = vr
            _, above = split_view(img[vy:vy + vh, vx:vx + vw], row)
            has_gauge = gauge_present(above, roi[3])
            ok = self.ask(view, f"빨강 = 물고기 ({int(f.sum())}px), 초록 = 괄호 ({int(b.sum())}px), "
                                f"바 위 게이지 {'있음' if has_gauge else '없음!'}\n"
                                "물고기·괄호가 보이고 게이지가 '있음'이면 확인", mode="view", max_size=(1000, 300))
            if not ok:
                return
            c["bar_roi"] = roi
            c["bar_scale"] = detect_gui_scale(img)
            if self.macro:
                self.macro.zone_w, self.macro.prev_zone = 0, None
            self.log("미니게임 바 직접 지정 완료!", "good")

        save_config(c)
        self.refresh_status()

    # ---------- 낚싯대 페이지 ----------
    def rod_click(self, kind, n):
        c = self.cfg
        if kind == "swap" and 1 <= n <= 9:
            c["rod_slots"] = sorted(set(c["rod_slots"]) ^ {n})
        elif kind == "exact" and 0 <= n <= 9:
            c["exact_slot"] = n
            if self.macro:
                self.macro.exact = None                   # 다른 칸이면 예전 값은 버림
                self.macro.inv_due = True
        elif kind in ("repair_rod_slot", "repair_string_slot") and 1 <= n <= 9:
            c[kind] = n
        else:
            return
        save_config(c)
        self.push("rod", self.rod_data())

    def use_angle(self, sens, yaw, pitch):
        try:
            sens, yaw, pitch = float(sens), float(yaw), float(pitch or 0)
        except (TypeError, ValueError):
            self.alert("모루 방향", "감도 %와 좌우 각도를 숫자로 넣어줘 (예: 69, 180)", "warn")
            return
        c = self.cfg
        c["mouse_sens_pct"], c["repair_yaw"], c["repair_pitch"] = sens, yaw, pitch
        c["repair_turn"] = None
        save_config(c)
        ANVIL_PATH.unlink(missing_ok=True)
        from common import turn_pixels
        dx, dy = turn_pixels(yaw, pitch, sens)
        self.log(f"모루 방향: 각도로 설정 (좌우 {yaw:g}°, 위아래 {pitch:g}° = 마우스 {dx}, {dy})", "good")
        self.push("rod", self.rod_data())

    def start_turn_record(self):
        if not IS_WIN:
            self.alert("모루 방향", "윈도우에서만 돼")
            return
        if self.macro and self.macro.running:
            self.alert("안내", "매크로를 먼저 정지해줘")
            return
        self.turn_stage = 1
        self.f7.clear()
        self.push("repairGuide", "마크에서 낚시하던 방향(물)을 보고 F7")
        self.log("모루 방향 기록: 물을 보고 F7 -> 모루를 십자선에 맞추고 F7", "warn")

    def turn_record_f7(self):
        if self.turn_stage == 1:
            self.turn_rec = winapi.RawMouseRecorder().start()
            self.turn_stage = 2
            self.push("repairGuide", "이제 마우스로 모루를 십자선 가운데에 맞추고 F7")
        elif self.turn_stage == 2:
            dx, dy = self.turn_rec.stop()
            self.turn_stage = 0
            c = self.cfg
            c["repair_turn"] = [int(dx), int(dy)]
            save_config(c)
            img = self.grab_game()
            if img is not None:
                cv2.imencode(".png", img)[1].tofile(str(ANVIL_PATH))
            self.push("repairGuide", None)
            self.log(f"모루 방향 기록 완료 (마우스 {dx}, {dy}). 마크에서 다시 물 쪽으로 돌려놔", "good")
            self.push("rod", self.rod_data())

    def grab_game(self):
        if not IS_WIN or not self.macro:
            return None
        hwnd = winapi.find_minecraft()
        if not hwnd:
            return None
        self.macro.hwnd = hwnd
        try:
            return self.macro.client_img()
        except Exception:
            return None

    def test_turn(self):
        if not self.macro or self.macro.running:
            self.alert("안내", "매크로가 정지된 상태에서 해줘")
            return
        turn = self.macro.turn_amount()
        if not turn:
            self.alert("모루 방향", "먼저 방향을 기록하거나 각도를 넣어줘")
            return
        hwnd = winapi.find_minecraft()
        m = self.macro

        def run():
            if hwnd:
                winapi.bring_to_front(hwnd)
            time.sleep(0.6)
            home = self.grab_game()
            winapi.send_mouse_move(*turn)
            time.sleep(0.3)
            anvil = m.anvil_ref()
            if anvil is not None and m.align_view(anvil, tag="[테스트]"):
                m.out("[테스트] 모루 화면에 맞춤")
            time.sleep(1.5)
            winapi.send_mouse_move(-turn[0], -turn[1])
            time.sleep(0.3)
            if home is not None:
                m.out("[테스트] 원래 시점으로 돌아옴" if m.align_view(home, tag="[테스트]")
                      else "[테스트] 원래 시점과 달라 보여 (확인해줘)")
        threading.Thread(target=self.guard(run), daemon=True).start()
        self.log("모루 보기 테스트: 모루를 보고(화면 맞춤) 다시 돌아와. 십자선이 모루에 있는지 봐줘", "warn")

    def check_now(self):
        if self.macro and self.macro.running:
            self.macro.inv_due = True
            self.log("다음 던지기 전에 인벤 확인할게", "good")
        else:
            self.log("낚시 중일 때 눌러줘 (던지기 전에 인벤을 열어 확인)", "warn")

    # ---------- 창 ----------
    def screen_size(self):
        try:
            s = webview.screens[0]
            return s.width, s.height
        except Exception:
            return 1920, 1080

    def fit(self, w, h):
        sw, sh = self.screen_size()
        return min(w, sw), min(h, sh - 60)

    def set_top(self, on):
        self.cfg["topmost"] = on
        save_config(self.cfg)
        if not self.mini:
            self.window.on_top = on

    def set_size(self, preset):
        if preset not in SIZES:
            return
        self.cfg["win_preset"] = preset
        save_config(self.cfg)
        if not self.mini:
            self.window.resize(*self.fit(*SIZES[preset]))

    def set_mini(self, on):
        if on == self.mini:
            return
        w = self.window
        if on:
            self.remember_geometry()
            self.mini = True
            self.push("mini", True)
            w.on_top = True
            w.resize(*MINI_SIZE)
        else:
            self.mini = False
            self.push("mini", False)
            w.on_top = bool(self.cfg.get("topmost"))
            c = self.cfg
            w.resize(*self.fit(c.get("win_w") or SIZES[c["win_preset"]][0], c.get("win_h") or SIZES[c["win_preset"]][1]))

    def remember_geometry(self):
        """창 크기·위치 기억 (미니 모드일 땐 큰 창 값은 안 바꿈)."""
        w = self.window
        if self.mini or not w or not self.cfg.get("remember_window", True):
            return
        try:
            if w.width > 200 and w.height > 200:
                self.cfg.update(win_w=int(w.width), win_h=int(w.height), win_x=int(w.x), win_y=int(w.y))
        except Exception:
            pass

    def first_geometry(self):
        c = self.cfg
        if c.get("win_layout") != LAYOUT:
            for k in ("win_w", "win_h", "win_x", "win_y"):
                c.pop(k, None)
            c["win_layout"], c["win_preset"] = LAYOUT, "mid"
        pw, ph = SIZES.get(c.get("win_preset"), SIZES["mid"])
        if c.get("remember_window", True) and c.get("win_w"):
            w, h = self.fit(int(c["win_w"]), int(c.get("win_h") or ph))
            x, y = c.get("win_x"), c.get("win_y")
            vx, vy, vw, vh = virtual_screen()             # 모니터 전체 (왼쪽 보조 모니터면 x 가 음수)
            if x is None or y is None or not (vx - w + 80 < x < vx + vw - 80 and vy <= y < vy + vh - 80):
                x = y = None                              # 화면 밖이면 가운데
            return w, h, x, y
        w, h = self.fit(pw, ph)
        return w, h, None, None

    def close(self):
        """F12·종료 버튼: 정리하고 창 닫기."""
        if self._closing:
            return
        self.cleanup()
        try:
            self.window.destroy()
        except Exception:
            pass

    def on_closing(self):
        """창의 X 버튼 (창은 알아서 닫힘)."""
        if not self._closing:
            self.cleanup()

    def cleanup(self):
        """tk 버전 close() 와 같음: 크기·위치 저장, 매크로 멈추고 Shift 떼기, 단축키 해제."""
        self.remember_geometry()
        try:
            save_config(self.cfg)
        except Exception:
            pass
        self._closing = True
        if self.macro:
            self.macro.quit = True
            self.macro.running = False
            try:
                self.macro.set_shift(False)
                self.macro.close_screen()
            except Exception:
                pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        global _POLLER
        if _POLLER is not None:                           # 예전 화면으로 넘어갈 때 F8 이 두 번 먹지 않게
            _POLLER.stop()
            _POLLER = None
        for ev, _ in list(self.waits.values()):
            ev.set()

    # ---------- 실행 ----------
    def on_start(self):
        threading.Thread(target=self.worker, daemon=True).start()
        hotkey("f8", self.toggle)
        hotkey("f12", self.quit_req.set)                  # 완전 종료
        hotkey("f7", self.f7.set)
        threading.Thread(target=self.ticker, daemon=True).start()
        self.log("준비 완료! '설정'에서 지정하고 '홈'에서 시작해", "good")

    def run(self):
        w, h, x, y = self.first_geometry()
        self.window = webview.create_window(
            "마크 낚시 매크로", str(HERE / "webui" / "index.html"), js_api=Bridge(self),
            width=w, height=h, x=x, y=y, min_size=(340, 200), on_top=bool(self.cfg.get("topmost", True)),
            background_color="#EAF4F9", text_select=True)
        self.window.events.closing += self.on_closing
        icon = HERE / "icon.ico"
        webview.start(self.on_start, gui="edgechromium", http_server=True, private_mode=True,
                      icon=str(icon) if icon.exists() else None)
        if getattr(sys, "frozen", False):
            os._exit(0)                   # 캡처 스레드 등이 남아 프로세스가 안 꺼지는 것 방지


if __name__ == "__main__":
    WebApp().run()
