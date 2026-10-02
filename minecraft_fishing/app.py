"""마인크래프트 낚시 매크로 - UI 버전.

실행: run.bat 더블클릭 (또는 python app.py)
폰트: Galmuri (SIL OFL 1.1, fonts/LICENSE.txt)
"""
import colorsys
import ctypes
import queue
import random
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

try:  # 고해상도 모니터에서 좌표/선명도 맞추기
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import keyboard

from common import (SUBTITLE_PATH, Screen, find_bobber, bracket_mask, color_mask, durability_value, fish_mask, gauge_present,
                    load_config, make_subtitle_template, save_config, save_subtitle_template, split_view,
                    subtitle_search_roi, view_roi)
from fishing_macro import Macro

HERE = Path(__file__).parent

# ---------------------------------------------------------------- 색상
SKY = "#bfe6f7"
PANEL, HI, SH, OUT, TXT = "#c6c6c6", "#ffffff", "#555555", "#000000", "#3f3f3f"
SLOT, SLOT_HI, SLOT_SH = "#8b8b8b", "#ffffff", "#373737"
OK, BAD, MUTED = "#2e7d32", "#c62828", "#6d6d6d"
BTN = {  # 면, 밝은 테두리, 어두운 테두리, 마우스 올렸을 때 면
    "gray": ("#a0a0a0", "#dcdcdc", "#5a5a5a", "#8c9fe0"),
    "green": ("#43a047", "#8be08e", "#1b5e20", "#5cc160"),
    "red": ("#d9443a", "#f59a92", "#8e2219", "#ea5d52"),
}

# ---------------------------------------------------------------- 픽셀 아트
SPRITES = {
    "fish": ([
        "...oooooo...oo",
        "..ohhhhh#o.o#o",
        ".o#e######o##o",
        "o###########o.",
        ".o########o##o",
        "..o######o.o#o",
        "...oooooo...oo",
    ], {"o": "#1f5f3a", "#": "#6be07b", "h": "#b8f5c0", "e": "#102010"}),
    "bobber": ([
        "...k...",
        "..kRk..",
        ".kRwRk.",
        ".kRRRk.",
        ".kWWWk.",
        ".kWWWk.",
        "..kWk..",
        "...k...",
    ], {"k": "#3a1d1d", "R": "#e53935", "w": "#ff9e98", "W": "#f5f5f5"}),
    "rod": ([
        "........bs",
        ".......bBs",
        "......bB.s",
        ".....bB..s",
        "....bB...s",
        "...bB....s",
        "..bB.....s",
        ".bB......k",
        "bB......kRk",
        "B........k",
    ], {"b": "#a8743f", "B": "#6b4423", "s": "#e0e0e0", "k": "#3a1d1d", "R": "#e53935"}),
    "emerald": ([
        "...kkk...",
        "..khGGk..",
        ".khGGGGk.",
        "khGGGGGGk",
        "kGGGGGGdk",
        ".kGGGGdk.",
        "..kGGdk..",
        "...kkk...",
    ], {"k": "#06331a", "G": "#17dd62", "h": "#b5ffd0", "d": "#0b8a3a"}),
    "chat": ([
        "kkkkkkkkkk",
        "kWWWWWWWWk",
        "kWkkWkkkWk",
        "kWWWWWWWWk",
        "kWkkkWkkWk",
        "kWWWWWWWWk",
        "kkkWkkkkkk",
        "..kWk.....",
        "..kk......",
    ], {"k": "#3f3f3f", "W": "#ffffff"}),
    "heart": ([
        ".kk...kk.",
        "kRRk.kRRk",
        "kRwRkRRRk",
        "kRRRRRRRk",
        ".kRRRRRk.",
        "..kRRRk..",
        "...kRk...",
        "....k....",
    ], {"k": "#3a0a0a", "R": "#e53935", "w": "#ffb3ad"}),
}
CHECK = [
    "........",
    ".......g",
    "......gg",
    "g....gg.",
    "gg..gg..",
    ".gggg...",
    "..gg....",
    "........",
]

S = 1           # UI 배율 (DPI 따라 결정)
FONTS = {}
PANEL_W = 400


def register_fonts():
    if sys.platform != "win32":
        return
    for f in ("Galmuri11.ttf", "Galmuri11-Bold.ttf"):
        p = HERE / "fonts" / f
        if p.exists():
            ctypes.windll.gdi32.AddFontResourceExW(str(p), 0x10, 0)   # FR_PRIVATE


def setup_fonts(root):
    fam = "Galmuri11" if "Galmuri11" in tkfont.families(root) else "맑은 고딕"
    FONTS["r"] = tkfont.Font(root, family=fam, size=-12 * S)
    FONTS["b"] = tkfont.Font(root, family=fam, size=-12 * S, weight="bold")
    FONTS["t"] = tkfont.Font(root, family=fam, size=-24 * S, weight="bold")
    FONTS["m"] = tkfont.Font(root, family=fam, size=-16 * S, weight="bold")


def sprite(name, scale):
    rows, pal = SPRITES[name]
    w, h = max(len(r) for r in rows), len(rows)
    img = tk.PhotoImage(width=w * scale, height=h * scale)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                img.put(pal[ch], to=(x * scale, y * scale, (x + 1) * scale, (y + 1) * scale))
    return img


def bevel(cv, x0, y0, x1, y1, face, hi, sh, bg, tag=""):
    """마크 GUI 느낌 테두리: 검은 외곽 + 밝은 위/왼쪽 + 어두운 아래/오른쪽, 모서리 따냄."""
    o, b = S, 2 * S
    kw = {"outline": "", "tags": tag}
    cv.create_rectangle(x0, y0, x1, y1, fill=OUT, **kw)
    cv.create_rectangle(x0 + o, y0 + o, x1 - o, y1 - o, fill=sh, **kw)
    cv.create_rectangle(x0 + o, y0 + o, x1 - o - b, y1 - o - b, fill=hi, **kw)
    cv.create_rectangle(x0 + o + b, y0 + o + b, x1 - o - b, y1 - o - b, fill=face, **kw)
    for cx, cy in ((x0, y0), (x1 - o, y0), (x0, y1 - o), (x1 - o, y1 - o)):
        cv.create_rectangle(cx, cy, cx + o, cy + o, fill=bg, **kw)


def slot(cv, x0, y0, x1, y1, fill=SLOT, tag=""):
    """인벤토리 칸처럼 움푹 들어간 상자."""
    kw = {"outline": "", "tags": tag}
    cv.create_rectangle(x0, y0, x1, y1, fill=SLOT_SH, **kw)
    cv.create_rectangle(x0 + S, y0 + S, x1, y1, fill=SLOT_HI, **kw)
    cv.create_rectangle(x0 + S, y0 + S, x1 - S, y1 - S, fill=fill, **kw)


# ---------------------------------------------------------------- 위젯
class PixelButton(tk.Canvas):
    def __init__(self, parent, text, command, variant="gray", width=None, height=None, font=None, bg=PANEL):
        self.font = font or FONTS["b"]
        super().__init__(parent, width=width or self.font.measure(text) + 24 * S, height=height or 22 * S,
                         bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command, self.variant, self.bgc = text, command, variant, bg
        self.hover = self.pressed = False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda e: self.draw())
        self.draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, e):
        fire = self.pressed and self.hover
        self._set(pressed=False)
        if fire and self.command:
            self.command()

    def set(self, text=None, variant=None):
        if (text or self.text, variant or self.variant) != (self.text, self.variant):
            self.text, self.variant = text or self.text, variant or self.variant
            self.draw()

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 2) if self.winfo_width() > 2 else int(self["width"])
        h = int(self["height"])
        face, hi, sh, hov = BTN[self.variant]
        if self.pressed:
            hi, sh = sh, hi
        bevel(self, 0, 0, w, h, hov if self.hover else face, hi, sh, self.bgc)
        dy = S if self.pressed else 0
        self.create_text(w / 2 + S, h / 2 + S + dy, text=self.text, font=self.font, fill="#2a2a2a")
        self.create_text(w / 2, h / 2 + dy, text=self.text, font=self.font,
                         fill="#ffffa0" if self.hover else "white")


class PixelCheck(tk.Frame):
    """체크박스(radio_value 없음) 또는 라디오 버튼."""

    def __init__(self, parent, text, variable, command=None, radio_value=None, bg=PANEL, fg=TXT):
        super().__init__(parent, bg=bg)
        self.var, self.rv, self.command = variable, radio_value, command
        n = 12 * S
        self.box = tk.Canvas(self, width=n, height=n, bg=bg, highlightthickness=0, cursor="hand2")
        self.box.pack(side="left")
        lbl = tk.Label(self, text=text, bg=bg, fg=fg, font=FONTS["r"], cursor="hand2")
        lbl.pack(side="left", padx=(4 * S, 0))
        for w in (self.box, lbl):
            w.bind("<Button-1>", self.click)
        variable.trace_add("write", lambda *a: self.draw())
        self.draw()

    def checked(self):
        return self.var.get() == self.rv if self.rv is not None else bool(self.var.get())

    def click(self, e=None):
        self.var.set(self.rv if self.rv is not None else not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        c, n = self.box, 12 * S
        c.delete("all")
        slot(c, 0, 0, n, n)
        if not self.checked():
            return
        if self.rv is not None:
            c.create_rectangle(4 * S, 4 * S, 8 * S, 8 * S, fill="#55ff55", outline="")
            return
        for y, row in enumerate(CHECK):
            for x, ch in enumerate(row):
                if ch == "g":
                    px, py = 2 * S + x * S, 2 * S + y * S
                    c.create_rectangle(px, py, px + S, py + S, fill="#55ff55", outline="")


class Panel(tk.Frame):
    """인벤토리 창 느낌 패널. 내용은 .content 에."""

    def __init__(self, parent, title, icon=None):
        super().__init__(parent, bg=SKY)
        self.pad = 8 * S
        self.cv = tk.Canvas(self, width=PANEL_W, height=40, bg=SKY, highlightthickness=0, bd=0)
        self.cv.pack()
        self.body = tk.Frame(self.cv, bg=PANEL)
        head = tk.Frame(self.body, bg=PANEL)
        head.pack(anchor="w", pady=(0, 4 * S))
        if icon:
            tk.Label(head, image=icon, bg=PANEL).pack(side="left", padx=(0, 4 * S))
        tk.Label(head, text=title, font=FONTS["b"], fg=TXT, bg=PANEL).pack(side="left")
        self.content = tk.Frame(self.body, bg=PANEL)
        self.content.pack(fill="x")
        self.cv.create_window(self.pad, self.pad, window=self.body, anchor="nw", width=PANEL_W - 2 * self.pad)
        self.body.bind("<Configure>", self.redraw)

    def redraw(self, e=None):
        h = self.body.winfo_reqheight() + 2 * self.pad
        self.cv.configure(height=h)
        self.cv.delete("bev")
        bevel(self.cv, 0, 0, PANEL_W, h, PANEL, HI, SH, SKY, tag="bev")


def label(parent, text="", font="r", fg=TXT, **kw):
    return tk.Label(parent, text=text, font=FONTS[font], fg=fg, bg=parent["bg"], **kw)


class PixelStepper(tk.Frame):
    """마크 버튼 [-] 검은 입력칸 [+]"""

    def __init__(self, parent, var, lo, hi, step, width=5):
        bg = parent["bg"]
        super().__init__(parent, bg=bg)
        self.var, self.lo, self.hi, self.step = var, lo, hi, step
        self.dec = 0 if float(step).is_integer() else len(str(step).split(".")[1])
        n = 18 * S
        PixelButton(self, "-", lambda: self.bump(-1), width=n, height=n, bg=bg).pack(side="left")
        tk.Entry(self, textvariable=var, width=width, font=FONTS["b"], justify="center", bg="#000000",
                 fg="#ffffff", insertbackground="#ffffff", relief="flat", bd=0, highlightthickness=2 * S,
                 highlightbackground="#a0a0a0", highlightcolor="#ffffff").pack(side="left", padx=2 * S, ipady=S)
        PixelButton(self, "+", lambda: self.bump(1), width=n, height=n, bg=bg).pack(side="left")

    def bump(self, d):
        try:
            v = float(self.var.get())
        except ValueError:
            v = self.lo
        v = min(self.hi, max(self.lo, v + d * self.step))
        self.var.set(f"{v:.{self.dec}f}" if self.dec else str(int(round(v))))


def spinbox(parent, var, lo, hi, step):
    return PixelStepper(parent, var, lo, hi, step)


# ---------------------------------------------------------------- 영역 선택 창
def load_image(path):
    """한글 경로 지원. BGR numpy 반환."""
    return np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()


class PickDialog(tk.Toplevel):
    """mode: rect = 드래그로 사각형 / point = 클릭으로 한 점 / view = 보기만."""

    def __init__(self, parent, img, guide, mode="rect", max_size=(1280, 720), ok_text="확인"):
        super().__init__(parent, bg=PANEL)
        self.title("영역 지정")
        self.result = None
        self.mode = mode
        h, w = img.shape[:2]
        self.s = s = min(max_size[0] / w, max_size[1] / h)
        self.img_w, self.img_h = w, h
        vw, vh = max(1, round(w * s)), max(1, round(h * s))
        pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
        pil = pil.resize((vw, vh), Image.NEAREST if s >= 1 else Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(pil)

        tk.Label(self, text=guide, font=FONTS["b"], fg="#ffff55", bg="#1a0a2a", justify="left",
                 padx=8 * S, pady=5 * S, highlightthickness=2 * S, highlightbackground="#5a2bd6"
                 ).pack(anchor="w", padx=10 * S, pady=(8 * S, 6 * S))
        self.cv = tk.Canvas(self, width=vw, height=vh, highlightthickness=2 * S, highlightbackground=SLOT_SH,
                            cursor="crosshair" if mode != "view" else "arrow")
        self.cv.pack(padx=10 * S)
        self.cv.create_image(0, 0, image=self.photo, anchor="nw")

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x", padx=10 * S, pady=8 * S)
        self.ok_btn = PixelButton(bar, f"{ok_text} (Enter)", self.ok, "green")
        self.ok_btn.pack(side="right")
        PixelButton(bar, "취소 (Esc)", self.destroy).pack(side="right", padx=6 * S)
        if mode == "view":
            PixelButton(bar, "다시 하기", self.retry).pack(side="right")

        self.start = self.shape = self.sel = None
        self.cv.bind("<ButtonPress-1>", self.on_down)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_up)
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())

        self.attributes("-topmost", True)
        self.transient(parent)
        self.update_idletasks()
        self.geometry(f"+{max(0, (self.winfo_screenwidth() - self.winfo_width()) // 2)}+20")
        self.grab_set()
        self.focus_force()

    def on_down(self, e):
        if self.mode == "rect":
            self.start = (e.x, e.y)
        elif self.mode == "point":
            self.cv.delete("mark")
            for dx, dy in ((10, 0), (0, 10)):
                self.cv.create_line(e.x - dx, e.y - dy, e.x + dx, e.y + dy, fill="#55ff55", width=2, tags="mark")
            self.sel = (e.x, e.y)

    def on_drag(self, e):
        if self.mode != "rect" or not self.start:
            return
        self.cv.delete("mark")
        self.cv.create_rectangle(*self.start, e.x, e.y, outline="#55ff55", width=2, tags="mark")

    def on_up(self, e):
        if self.mode != "rect" or not self.start:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            self.sel = (x0, y0, x1, y1)

    def ok(self):
        s = self.s
        if self.mode == "view":
            self.result = True
        elif self.sel is None:
            return
        elif self.mode == "rect":
            x0, y0, x1, y1 = self.sel
            x, y = int(x0 / s), int(y0 / s)
            w = max(1, min(self.img_w - x, round((x1 - x0) / s)))
            h = max(1, min(self.img_h - y, round((y1 - y0) / s)))
            self.result = [x, y, w, h]
        else:
            px, py = self.sel
            self.result = (min(int(px / s), self.img_w - 1), min(int(py / s), self.img_h - 1))
        self.destroy()

    def retry(self):
        self.result = False
        self.destroy()


def ask(parent, img, guide, mode="rect", **kw):
    d = PickDialog(parent, img, guide, mode, **kw)
    parent.wait_window(d)
    return d.result


def ask_roi(parent, img, name, precise=True):
    """1단계: 전체 화면에서 대충 → 2단계: 확대해서 정확히."""
    r = ask(parent, img, f"[{name}] {'1/2  ' if precise else ''}주변을 드래그로 감싸기")
    if not r or not precise:
        return r
    x, y, w, h = r
    H, W = img.shape[:2]
    m = max(10, max(w, h) // 3)
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(W, x + w + m), min(H, y + h + m)
    r2 = ask(parent, img[y0:y1, x0:x1], f"[{name}] 2/2  확대 화면에서 정확히 드래그", max_size=(1000, 500))
    if not r2:
        return None
    return [x0 + r2[0], y0 + r2[1], r2[2], r2[3]]


def overlay(crop, mask):
    v = crop.copy()
    v[mask] = (0, 255, 0)
    return v


# ---------------------------------------------------------------- 메인 앱
class App:
    ITEMS = [
        ("subtitle", "chat", "입질 자막", "직접 낚시하다 입질 와서 자막 '낚시찌 ... 첨벙'이 떴을 때"),
        ("bobber", "bobber", "찌 (예비)", "물을 바라보고 찌가 떠 있을 때"),
        ("rod", "rod", "낚싯대 내구도", "핫바에 낚싯대 내구도 줄이 보일 때"),
        ("gauge", "emerald", "원형 게이지", "게이지가 '가득 찬' 순간 (스크린샷 파일 추천)"),
    ]
    SETTINGS = [
        ("subtitle_threshold", "자막 일치 기준 (0~1)", 0.5, 0.99, 0.01),
        ("bite_confirm_frames", "입질 확인 횟수 (연속)", 1, 5, 1),
        ("bite_drop_ratio", "입질: 찌가 이 비율 아래로 줄면", 0.1, 0.95, 0.05),
        ("bite_dip_px", "입질: 찌가 이만큼(px) 내려가면", 1, 30, 1),
        ("tolerance", "색 허용 오차", 5, 80, 1),
        ("deadzone_px", "바 따라가기 허용 오차(px)", 0, 30, 1),
        ("lead_sec", "바 움직임 예측(초)", 0.0, 0.3, 0.01),
        ("cast_settle_sec", "던진 뒤 대기(초)", 0.5, 5, 0.1),
        ("bite_timeout_sec", "입질 최대 대기(초)", 10, 120, 5),
        ("recast_delay_sec", "다시 던지기 전 대기(초)", 0.2, 5, 0.1),
        ("start_delay_sec", "시작 버튼 후 대기(초)", 0, 10, 1),
    ]

    def __init__(self):
        global S, PANEL_W
        self.cfg = load_config()
        self.q = queue.Queue()
        self.waiting_item = None
        self.f7 = threading.Event()

        register_fonts()
        self.root = tk.Tk()
        S = max(1, round(self.root.winfo_fpixels("1i") / 96))
        PANEL_W = 400 * S
        setup_fonts(self.root)
        self.root.title("마크 낚시 매크로")
        self.root.configure(bg=SKY)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.icons = {k: sprite(k, 2 * S) for k in SPRITES}
        self.icons_big = {k: sprite(k, 3 * S) for k in ("fish", "bobber")}
        try:
            self.root.iconphoto(True, sprite("fish", 4))
        except tk.TclError:
            pass

        self.build()

        self.macro = None
        threading.Thread(target=self.worker, daemon=True).start()
        keyboard.add_hotkey("f8", lambda: self.macro and self.macro.toggle())
        keyboard.add_hotkey("f7", self.f7.set)

        self.refresh_status()
        self.anim_t = 0
        self.root.after(100, self.tick)
        self.root.after(150, self.animate)
        self.log("준비 완료! ① 설정 → ② 시작 순서로 진행해", "good")

    # ---------- 레이아웃 ----------
    def build(self):
        m = 10 * S
        self.build_header()

        p1 = Panel(self.root, "① 화면 위치 설정", self.icons["bobber"])
        p1.pack(padx=m, pady=(m, 0))
        c = p1.content
        c.columnconfigure(2, weight=1)
        self.status_lbl = {}
        bf = tk.Frame(c, bg=PANEL)
        bf.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4 * S))
        label(bf, "입질 감지 :", "b").pack(side="left", padx=(0, 6 * S))
        self.bite_mode = tk.StringVar(value=self.cfg["bite_mode"])
        PixelCheck(bf, "자막 (추천)", self.bite_mode, self.change_mode, radio_value="subtitle").pack(
            side="left", padx=(0, 8 * S))
        PixelCheck(bf, "찌 화면 (예비)", self.bite_mode, self.change_mode, radio_value="bobber").pack(side="left")
        rows = [(k, ic, n) for k, ic, n, _ in self.ITEMS] + [("bar", "fish", "미니게임 바")]
        for r, (key, ic, name) in enumerate(rows, start=1):
            tk.Label(c, image=self.icons[ic], bg=PANEL, width=24 * S).grid(row=r, column=0, pady=2 * S)
            label(c, name, "b").grid(row=r, column=1, sticky="w", padx=(4 * S, 8 * S))
            self.status_lbl[key] = label(c)
            self.status_lbl[key].grid(row=r, column=2, sticky="w")
            if key == "bar":
                btn = tk.Frame(c, bg=PANEL)
                PixelButton(btn, "자동", self.reset_bar, width=39 * S).pack(side="left")
                PixelButton(btn, "직접", lambda: self.begin_set("bar"), width=39 * S).pack(side="left", padx=(4 * S, 0))
            else:
                btn = PixelButton(c, "지정하기", lambda k=key: self.begin_set(k), width=82 * S)
            btn.grid(row=r, column=3, pady=2 * S)

        mf = tk.Frame(c, bg=PANEL)
        mf.grid(row=len(rows) + 1, column=0, columnspan=4, sticky="w", pady=(6 * S, 0))
        label(mf, "화면 가져오기 :").pack(side="left", padx=(0, 6 * S))
        self.capture_mode = tk.StringVar(value="live")
        PixelCheck(mf, "게임에서 F7", self.capture_mode, radio_value="live").pack(side="left", padx=(0, 8 * S))
        PixelCheck(mf, "스크린샷 파일", self.capture_mode, radio_value="file").pack(side="left")
        self.guide = tk.Label(c, text="", font=FONTS["b"], fg="#ffff55", bg="#1a0a2a", padx=6 * S, pady=4 * S,
                              highlightthickness=2 * S, highlightbackground="#5a2bd6",
                              wraplength=PANEL_W - 40 * S, justify="left")
        self.guide_row = len(rows) + 2

        p2 = Panel(self.root, "② 낚시 시작", self.icons["rod"])
        p2.pack(padx=m, pady=(6 * S, 0))
        self.run_btn = PixelButton(p2.content, "▶ 낚시 시작! (F8)", self.toggle, "green",
                                   width=PANEL_W - 16 * S, height=34 * S, font=FONTS["m"])
        self.run_btn.pack(pady=(0, 4 * S))
        self.state_lbl = label(p2.content, "정지됨", "b")
        self.state_lbl.pack()
        label(p2.content, "시작 누르고 바로 게임 창 클릭! 게임 중엔 F8", fg=MUTED).pack()
        df = tk.Frame(p2.content, bg=PANEL)
        df.pack(fill="x", pady=(8 * S, 0))
        tk.Label(df, image=self.icons["rod"], bg=PANEL).grid(row=0, column=0, rowspan=2, padx=(0, 6 * S))
        label(df, "내구도 지키기", "b").grid(row=0, column=1, sticky="w")
        self.ignore_var = tk.BooleanVar(value=self.cfg["durability_ignore"])
        PixelCheck(df, "안 봄 (수선 낚싯대)", self.ignore_var, self.save_durability).grid(
            row=0, column=2, columnspan=3, sticky="e")
        self.stop_var = tk.StringVar(value=str(self.cfg["durability_stop_pct"]))
        self.max_var = tk.StringVar(value=str(self.cfg["durability_max"]))
        r2 = tk.Frame(df, bg=PANEL)
        r2.grid(row=1, column=1, columnspan=4, sticky="w", pady=(3 * S, 0))
        spinbox(r2, self.stop_var, 1, 99, 5).pack(side="left")
        label(r2, "% 이하면 멈춤").pack(side="left", padx=(4 * S, 12 * S))
        label(r2, "최대").pack(side="left", padx=(0, 4 * S))
        spinbox(r2, self.max_var, 1, 2000, 1).pack(side="left")
        df.columnconfigure(2, weight=1)
        for var in (self.stop_var, self.max_var):
            var.trace_add("write", lambda *a: self.save_durability())

        p3 = Panel(self.root, "실시간 상태", self.icons["heart"])
        p3.pack(padx=m, pady=(6 * S, 0))
        g = tk.Frame(p3.content, bg=PANEL)
        g.pack(fill="x")
        self.vals = {}
        for i, (k, ic, name) in enumerate([("caught", "fish", "낚은 물고기"), ("bite", "chat", "입질 감지"),
                                           ("gauge", "emerald", "게이지"), ("dura", "rod", "내구도")]):
            r, col = divmod(i, 2)
            tk.Label(g, image=self.icons[ic], bg=PANEL, width=24 * S).grid(row=r, column=col * 3, pady=2 * S)
            label(g, name).grid(row=r, column=col * 3 + 1, sticky="w", padx=(2 * S, 6 * S))
            v = label(g, "-", "b", width=9, anchor="w")
            v.grid(row=r, column=col * 3 + 2, sticky="w")
            self.vals[k] = v
        self.dura_cv = tk.Canvas(g, width=40 * S, height=8 * S, bg=PANEL, highlightthickness=0)
        self.bar_cv = tk.Canvas(p3.content, width=PANEL_W - 16 * S, height=30 * S, bg=PANEL, highlightthickness=0)
        self.bar_cv.pack(pady=(6 * S, 0))

        opt = tk.Frame(self.root, bg=SKY)
        opt.pack(fill="x", padx=m + 2 * S, pady=(6 * S, 0))
        self.show_adv = tk.BooleanVar(value=False)
        PixelCheck(opt, "세부 설정", self.show_adv, self.toggle_adv, bg=SKY).pack(side="left")
        self.top_var = tk.BooleanVar(value=True)
        PixelCheck(opt, "항상 위", self.top_var,
                   lambda: self.root.attributes("-topmost", self.top_var.get()), bg=SKY).pack(side="right")
        self.root.attributes("-topmost", True)

        self.adv = Panel(self.root, "세부 설정", self.icons["emerald"])
        a = self.adv.content
        a.columnconfigure(0, weight=1)
        self.adv_vars = {}
        for i, (k, name, lo, hi, step) in enumerate(self.SETTINGS):
            label(a, name).grid(row=i, column=0, sticky="w", pady=1 * S)
            var = tk.StringVar(value=str(self.cfg[k]))
            spinbox(a, var, lo, hi, step).grid(row=i, column=1, pady=1 * S)
            self.adv_vars[k] = var
        self.reel_var = tk.BooleanVar(value=self.cfg["reel_click_after_game"])
        PixelCheck(a, "미니게임 끝나고 우클릭 한 번 더", self.reel_var).grid(
            row=len(self.SETTINGS), column=0, columnspan=2, sticky="w", pady=(4 * S, 0))
        PixelButton(a, "설정 저장", self.save_adv, "green").grid(
            row=len(self.SETTINGS) + 1, column=0, columnspan=2, pady=(6 * S, 0))

        self.note_panel = Panel(self.root, "알림", self.icons["chat"])
        self.note_panel.pack(padx=m, pady=(6 * S, m))
        self.notes = []
        self.note_lbls = []
        for _ in range(4):
            lb = label(self.note_panel.content, "", anchor="w", justify="left", wraplength=PANEL_W - 30 * S)
            lb.pack(fill="x", anchor="w")
            self.note_lbls.append(lb)

    def build_header(self):
        W, H = PANEL_W + 20 * S, 92 * S
        cv = self.header = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bg=SKY)
        cv.pack()
        bands = ["#7cc6ef", "#8ccdf1", "#9cd5f3", "#acdcf5", SKY]
        bh = H // len(bands)
        for i, col in enumerate(bands):
            cv.create_rectangle(0, i * bh, W, (i + 1) * bh + bh, fill=col, outline="")
        P = 4 * S
        for cx, cy, cw in ((12, 14, 7), (W // S - 46, 8, 8)):
            cv.create_rectangle(cx * S, cy * S, cx * S + cw * P, cy * S + 2 * P, fill="white", outline="")
            cv.create_rectangle(cx * S + P, cy * S - P, cx * S + (cw - 3) * P, cy * S, fill="white", outline="")

        water_y = H - 22 * S
        rnd = random.Random(3)
        for x in range(0, W, P):
            for y in range(water_y, H, P):
                c = rnd.choice(["#3f76e4", "#3f76e4", "#3a6dd6", "#4a82ee"])
                cv.create_rectangle(x, y, x + P, y + P, fill=c, outline="")
        gx1 = 92 * S
        for x in range(0, gx1, P):
            for y in range(water_y - 10 * S, H, P):
                top = y < water_y - 10 * S + 2 * P
                c = rnd.choice(["#5fa83a", "#6fbc47", "#549a33"] if top else ["#866043", "#79553a", "#966c4a"])
                cv.create_rectangle(x, y, x + P, y + P, fill=c, outline="")

        tx = W // 2 + 30 * S
        cv.create_text(tx + 2 * S, 30 * S + 2 * S, text="마크 낚시 매크로", font=FONTS["t"], fill="#3f3f3f")
        cv.create_text(tx, 30 * S, text="마크 낚시 매크로", font=FONTS["t"], fill="white")
        cv.create_text(tx + S, 52 * S + S, text="물고기 따라가기 자동 ~", font=FONTS["b"], fill="#3f3f3f")
        cv.create_text(tx, 52 * S, text="물고기 따라가기 자동 ~", font=FONTS["b"], fill="#ffff55")

        # 풀 블록 위에 꽂힌 낚싯대 + 줄
        rod = self.icons_big.setdefault("rod", sprite("rod", 3 * S))
        rx, ry = 52 * S, water_y - 10 * S
        cv.create_image(rx, ry, image=rod, anchor="sw")
        self.h_line = cv.create_line(rx + 27 * S, ry - 29 * S, 150 * S, water_y - 20 * S, fill="#f0f0f0", width=S)
        self.h_bobber = cv.create_image(150 * S, water_y + 2 * S, image=self.icons_big["bobber"], anchor="s")
        self.h_fish = cv.create_image(W - 60 * S, water_y + 12 * S, image=self.icons_big["fish"], anchor="center")
        self.h_water_y = water_y
        self.fish_dir = -1

    def animate(self):
        """헤더 찌 까딱까딱 + 물고기 헤엄."""
        self.anim_t += 1
        cv, wy = self.header, self.h_water_y
        bob = (2 * S if self.anim_t % 8 < 4 else 0)
        if self.macro and self.macro.state == "미니게임 중":
            bob = 5 * S if self.anim_t % 2 else 0
        cv.coords(self.h_bobber, 150 * S, wy + 2 * S + bob)
        x0, y0, _, _ = cv.coords(self.h_line)
        cv.coords(self.h_line, x0, y0, 150 * S, wy - 20 * S + bob)
        x, y = cv.coords(self.h_fish)
        W = int(cv["width"])
        if x < 200 * S or x > W - 30 * S:
            self.fish_dir *= -1
            img = self.icons_big["fish"] if self.fish_dir < 0 else self.icons_big.setdefault(
                "fish_r", self.flip(self.icons_big["fish"]))
            cv.itemconfigure(self.h_fish, image=img)
        cv.coords(self.h_fish, x + self.fish_dir * 2 * S, wy + 12 * S + (S if self.anim_t % 6 < 3 else 0))
        self.root.after(150, self.animate)

    @staticmethod
    def flip(img):
        w, h = img.width(), img.height()
        out = tk.PhotoImage(width=w, height=h)
        for y in range(h):
            for x in range(w):
                if not img.transparency_get(x, y):
                    out.put("#%02x%02x%02x" % img.get(x, y), (w - 1 - x, y))
        return out

    def toggle_adv(self):
        if self.show_adv.get():
            self.adv.pack(padx=10 * S, pady=(6 * S, 0), before=self.note_panel)
        else:
            self.adv.pack_forget()

    # ---------- 매크로 스레드 ----------
    def worker(self):
        self.macro = Macro(self.cfg, out=self.q.put, hotkeys=False)
        self.macro.run()

    def log(self, msg, tag=None):
        if tag is None:
            tag = ("bad" if ("오류" in msg or "알림" in msg or "정지 ->" in msg) else
                   "good" if ("입질" in msg or "끝" in msg or "완료" in msg or "감지" in msg) else
                   "warn" if ("시작" in msg or "F7" in msg) else None)
        color = {"good": OK, "warn": "#8a6d00", "bad": BAD, "dim": MUTED}.get(tag, TXT)
        line = msg.splitlines()[0] if msg else ""
        self.notes.insert(0, (time.strftime("%H:%M"), line, color))
        del self.notes[len(self.note_lbls):]
        for lb, item in zip(self.note_lbls, self.notes + [None] * len(self.note_lbls)):
            if item is None:
                lb.config(text="")
            else:
                t, text, col = item
                lb.config(text=f"{t}  {text}", fg=col if lb is self.note_lbls[0] else MUTED)

    def tick(self):
        while not self.q.empty():
            self.log(self.q.get())

        if self.f7.is_set():
            self.f7.clear()
            if self.waiting_item:
                item, self.waiting_item = self.waiting_item, None
                img = Screen(self.cfg["monitor"]).full()
                self.guide.grid_forget()
                self.root.deiconify()
                self.root.lift()
                self.do_set(item, img)

        m = self.macro
        if m:
            s = m.stats
            self.vals["caught"].config(text=f"{s['caught']}마리")
            if self.cfg["bite_mode"] == "subtitle":
                sub = s["sub"]
                hit = sub is not None and sub >= self.cfg["subtitle_threshold"]
                self.vals["bite"].config(text="-" if sub is None else f"자막 {sub:.0%}", fg=OK if hit else TXT)
            else:
                self.vals["bite"].config(text="-" if not self.cfg["bobber_roi"] else f"찌 {s['bobber_n']}px", fg=TXT)
            self.vals["gauge"].config(text="-" if s["gauge"] is None else f"{s['gauge']:.0%}")
            self.draw_durability(s["dura"])
            self.state_lbl.config(text=m.state, fg=OK if m.running else TXT)
            if m.running:
                self.run_btn.set("■ 그만 낚기 (F8)", "red")
            else:
                self.run_btn.set("▶ 낚시 시작! (F8)", "green")
            self.draw_bar(s)
            if self.cfg["bar_roi"] and not self.status_lbl["bar"].cget("text").startswith("● 찾음"):
                self.refresh_status()

        self.root.after(100, self.tick)

    def draw_durability(self, d):
        v = self.vals["dura"]
        if d is None:
            v.config(text="-", fg=TXT)
            self.dura_cv.grid_forget()
            return
        val, kind = d
        mx = self.cfg["durability_max"]
        stop = mx * self.cfg["durability_stop_pct"] / 100
        danger = not self.cfg["durability_ignore"] and (kind == "low" or val <= stop)
        v.config(text=f"{'1~2' if kind == 'low' else val}/{mx}", width=7,
                 fg=MUTED if self.cfg["durability_ignore"] else BAD if danger else OK)
        frac = 0 if kind == "low" else min(1, val / mx)
        r, g, b = colorsys.hsv_to_rgb(frac / 3, 1, 1)
        c = self.dura_cv
        c.delete("all")
        c.create_rectangle(0, 0, 40 * S, 8 * S, fill="#000000", outline="")
        if frac > 0:
            c.create_rectangle(S, S, S + round(38 * S * frac), 6 * S, outline="",
                               fill="#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
        c.grid(row=1, column=6, sticky="w")

    def draw_bar(self, s):
        cv = self.bar_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        slot(cv, 0, 0, W, H, fill="#0b3c5d")
        roi = self.cfg["bar_roi"]
        if not roi:
            cv.create_text(W // 2, H // 2, text="미니게임이 뜨면 바를 자동으로 찾아요", font=FONTS["r"], fill="#aed6f1")
            return
        if not s["active"]:
            cv.create_text(W // 2, H // 2, text="미니게임 기다리는 중 ...", font=FONTS["r"], fill="#aed6f1")
            return
        scale = (W - 8 * S) / roi[2]
        if s["zone"] is not None and self.macro:
            zw = max(self.macro.zone_w, 4) * scale
            zx = 4 * S + s["zone"] * scale
            cv.create_rectangle(zx - zw / 2, 3 * S, zx + zw / 2, H - 3 * S, outline="#aed6f1", width=2 * S)
        if s["fish"] is not None:
            cv.create_image(4 * S + s["fish"] * scale, H // 2, image=self.icons["fish"])

    # ---------- 설정 ----------
    def refresh_status(self):
        c = self.cfg
        sub_mode = c["bite_mode"] == "subtitle"
        done = {"subtitle": c["subtitle_roi"] and SUBTITLE_PATH.exists(), "bobber": c["bobber_roi"],
                "rod": c["durability_roi"], "gauge": c["gauge_roi"]}
        need = {"subtitle": "필수" if sub_mode else "안 씀", "bobber": "안 씀" if sub_mode else "필수",
                "rod": "추천", "gauge": "선택"}
        for k, ok in done.items():
            self.status_lbl[k].config(text="● 완료" if ok else f"○ 미설정 ({need[k]})",
                                      fg=OK if ok else (BAD if need[k] == "필수" else MUTED))
        self.status_lbl["bar"].config(text="● 찾음" if c["bar_roi"] else "○ 자동으로 찾음",
                                      fg=OK if c["bar_roi"] else MUTED)

    def begin_set(self, item):
        if self.macro and self.macro.running:
            messagebox.showinfo("안내", "매크로를 먼저 정지해줘")
            return
        scenes = {k: sc for k, _, _, sc in self.ITEMS}
        scenes["bar"] = "미니게임 바가 떠 있을 때 (직접 낚시하면서)"
        scene = scenes[item]
        if self.capture_mode.get() == "file":
            path = filedialog.askopenfilename(title=f"{scene} 스크린샷",
                                              filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp *.webp")])
            if path:
                try:
                    self.do_set(item, load_image(path))
                except Exception as e:
                    messagebox.showerror("오류", f"이미지 열기 실패: {e}")
            return
        self.waiting_item = item
        self.f7.clear()
        self.guide.config(text=f"▶ 게임에서 [{scene}] 장면을 띄우고 F7 !")
        self.guide.grid(row=self.guide_row, column=0, columnspan=4, sticky="we", pady=(6 * S, 0))
        self.log(f"F7 기다리는 중: {scene}", "warn")

    def do_set(self, item, img):
        c = self.cfg
        if item == "subtitle":
            rect = ask_roi(self.root, img, "입질 자막 - '낚시찌 ... 첨벙' 글자 한 줄 전체 (화살표 < > 는 빼고)")
            if not rect:
                return
            x, y, w, h = rect
            made = make_subtitle_template(img[y:y + h, x:x + w])
            if made is None:
                messagebox.showwarning("확인", "흰 자막 글자가 안 보여. 자막 글자 위를 다시 감싸줘.\n"
                                       "(설정 > 접근성 > 텍스트 배경 불투명도를 올리면 잘 보여)")
                return
            tmpl, (tx, ty, tw, th) = made
            if tw < 15 or th < 5:
                messagebox.showwarning("확인", "너무 작게 잡혔어. 자막 글자 한 줄 전체를 감싸줘.")
                return
            save_subtitle_template(tmpl)
            c["subtitle_roi"] = subtitle_search_roi([x + tx, y + ty, tw, th], img.shape[1], img.shape[0])
            if self.macro:
                self.macro.sub_tmpl = None
            self.log("입질 자막 설정 완료! (실시간 상태의 '입질 감지'가 자막 뜰 때 80% 넘으면 정상)", "good")

        elif item == "bobber":
            roi = ask_roi(self.root, img, "찌 영역 - 찌가 떨어질 수 있는 물 쪽을 넓게 (하트/핫바는 빼고)", precise=False)
            if not roi:
                return
            x, y, w, h = roi
            crop = img[y:y + h, x:x + w].copy()
            H, W = img.shape[:2]
            found = find_bobber(crop, (W / 2 - x, H / 2 - y), max_side=max(40, int(0.075 * H)))
            if found:
                bx, by, bw, bh = found
                cv2.rectangle(crop, (bx - 4, by - 4), (bx + bw + 4, by + bh + 4), (0, 255, 0), 2)
                msg = "초록 네모 = 찾은 찌. 맞으면 확인"
            else:
                msg = "지금 화면에선 찌를 못 찾았어 (찌가 안 보이거나 너무 어두움).\n영역만 저장하려면 확인"
            if not ask(self.root, crop, msg, mode="view", max_size=(900, 500)):
                return
            c["bobber_roi"] = roi
            self.log("찌 설정 완료!", "good")

        elif item == "rod":
            roi = ask_roi(self.root, img, "내구도 줄 - 핫바 낚싯대 칸 아래 색깔 줄만")
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
            roi = ask_roi(self.root, img, "미니게임 바 - 하트/게이지 빼고 바 줄만")
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
            ok = ask(self.root, view, f"빨강 = 물고기 ({int(f.sum())}px), 초록 = 괄호 ({int(b.sum())}px), "
                                      f"바 위 게이지 {'있음' if has_gauge else '없음!'}\n"
                                      "물고기·괄호가 보이고 게이지가 '있음'이면 확인", mode="view", max_size=(1000, 300))
            if not ok:
                return
            c["bar_roi"] = roi
            if self.macro:
                self.macro.zone_w, self.macro.prev_zone = 0, None
            self.log("미니게임 바 직접 지정 완료!", "good")

        elif item == "gauge":
            roi = ask_roi(self.root, img, "원형 게이지 - 가득 찬 상태")
            if not roi:
                return
            x, y, w, h = roi
            n = int(color_mask(img[y:y + h, x:x + w], c["gauge_color"], c["gauge_tolerance"]).sum())
            if n < 20:
                messagebox.showwarning("확인", f"게이지 색이 거의 안 잡힘 ({n}px).\n가득 찬 장면이 맞는지 확인해줘.")
                return
            c["gauge_roi"], c["gauge_full_pixels"] = roi, n
            self.log(f"게이지 설정 완료! ({n}px)", "good")

        save_config(c)
        self.refresh_status()

    def save_durability(self):
        self.cfg["durability_ignore"] = self.ignore_var.get()
        try:
            pct, mx = int(float(self.stop_var.get())), int(float(self.max_var.get()))
        except ValueError:
            save_config(self.cfg)
            return                       # 입력 중 (빈칸 등)
        if 1 <= pct <= 99 and mx >= 1:
            self.cfg["durability_stop_pct"], self.cfg["durability_max"] = pct, mx
        save_config(self.cfg)

    def change_mode(self):
        self.cfg["bite_mode"] = self.bite_mode.get()
        save_config(self.cfg)
        self.refresh_status()
        self.log("입질 감지: " + ("자막" if self.cfg["bite_mode"] == "subtitle" else "찌 화면 (예비)"), "warn")

    def reset_bar(self):
        self.cfg["bar_roi"] = None
        if self.macro:
            self.macro.zone_w, self.macro.prev_zone = 0, None
        save_config(self.cfg)
        self.refresh_status()
        self.log("바 자동 찾기 켜짐. 미니게임이 뜨면 찾아 (매크로 꺼둔 채 직접 낚시해도 찾음)", "warn")

    def save_adv(self):
        try:
            for k, var in self.adv_vars.items():
                v = float(var.get())
                self.cfg[k] = int(v) if isinstance(self.cfg[k], int) and v.is_integer() else v
        except ValueError:
            messagebox.showerror("오류", "숫자만 입력해줘")
            return
        self.cfg["reel_click_after_game"] = self.reel_var.get()
        save_config(self.cfg)
        self.log("세부 설정 저장 완료!", "good")

    # ---------- 실행 ----------
    def toggle(self):
        if self.macro:
            self.macro.toggle()

    def close(self):
        if self.macro:
            self.macro.quit = True
            self.macro.running = False
        keyboard.unhook_all()
        self.root.after(200, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
