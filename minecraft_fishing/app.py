"""마인크래프트 낚시 매크로 - UI 버전.

실행: run.bat 더블클릭 (또는 python app.py)
폰트: Galmuri (SIL OFL 1.1, fonts/LICENSE.txt)
"""
import colorsys
import os
import ctypes
import queue
import random
import sys
import threading
import time
import tkinter as tk
import traceback
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
                    subtitle_search_roi, view_roi, load_history, read_number, save_repair_refs,
                    hotbar_points, snap_slot, detect_gui_scale)
from fishing_macro import Macro
import winapi
from winapi import IS_WIN

HERE = Path(__file__).parent

# ---------------------------------------------------------------- 색상
THEMES = {
    # 마크 인벤토리 GUI 느낌: 회색 판 + 입체 테두리(위·왼쪽 밝게, 아래·오른쪽 어둡게), 각진 모서리
    "light": dict(
        SKY="#2b2b2b", PANEL="#c6c6c6", LINE="#8b8b8b", SOFT="#b4b4b4", ACCENT="#2f7d32",
        TXT="#2f2f2f", MUTED="#555555", OK="#2e7d32", BAD="#b3261e", SIDEBAR="#1f1f1f", NAV_SEL="#c6c6c6",
        GUIDE_BG="#dcdcdc", BAR_BG="#1d2b4f", BEV_HI="#ffffff", BEV_LO="#555555", NAV_TXT="#d6d6d6",
        HEADER=["#7cc6ef", "#8ccdf1", "#9cd5f3", "#acdcf5"], CLOUD="#ffffff",
        BTN={  # 면, 글자, 테두리, 마우스 올렸을 때 면
            "gray": ("#717171", "#ffffff", "#000000", "#8a8fb0"),
            "green": ("#3f9a46", "#ffffff", "#000000", "#4cb554"),
            "red": ("#a8322a", "#ffffff", "#000000", "#c03f35"),
            "mint": ("#3f6fa8", "#ffffff", "#000000", "#4d82c2"),
        }),
    "dark": dict(
        SKY="#121212", PANEL="#383838", LINE="#262626", SOFT="#4a4a4a", ACCENT="#7ddc6f",
        TXT="#eeeeee", MUTED="#ababab", OK="#7ddc6f", BAD="#ff7b6b", SIDEBAR="#0c0c0c", NAV_SEL="#383838",
        GUIDE_BG="#2a2a2a", BAR_BG="#101a30", BEV_HI="#5c5c5c", BEV_LO="#1a1a1a", NAV_TXT="#cfcfcf",
        HEADER=["#141c36", "#18213f", "#1d2748", "#222d52"], CLOUD="#3b4466",
        BTN={
            "gray": ("#555555", "#ffffff", "#000000", "#6a6f90"),
            "green": ("#3a8a41", "#ffffff", "#000000", "#46a04e"),
            "red": ("#9c2e27", "#ffffff", "#000000", "#b53a31"),
            "mint": ("#365f91", "#ffffff", "#000000", "#4373ab"),
        }),
}


def apply_theme(name):
    globals().update(THEMES[name])
    globals()["SLOT"] = globals()["SOFT"]


SKY = PANEL = LINE = SOFT = ACCENT = TXT = MUTED = OK = BAD = SIDEBAR = NAV_SEL = GUIDE_BG = BAR_BG = None
BEV_HI = BEV_LO = NAV_TXT = None
CLOUD = SLOT = HEADER = BTN = None
apply_theme("light")

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
    "chest": ([
        ".kkkkkkkkk.",
        "kBBBBBBBBBk",
        "kbbbbbbbbbk",
        "kkkkkGkkkkk",
        "kBBBkYkBBBk",
        "kbbbbbbbbbk",
        "kbbbbbbbbbk",
        ".kkkkkkkkk.",
    ], {"k": "#3b2410", "B": "#c08a3e", "b": "#9a6a2c", "G": "#9e9e9e", "Y": "#ffd54f"}),
    "book": ([
        "..kkkkkkk",
        ".kRRRRRRk",
        "kRRRRRRk.",
        "kRwwwwRk.",
        "kRRRRRRk.",
        "kRRRRRRk.",
        "kWWWWWWk.",
        ".kkkkkkk.",
    ], {"k": "#3a1d1d", "R": "#c0392b", "w": "#ffd54f", "W": "#f5f5f5"}),
}
TIP_BG = "#100010"
FISH_HEX = {"빨강": "#e53935", "주황": "#fb8c00", "노랑": "#fdd835", "초록": "#43a047", "하늘": "#29b6f6",
            "파랑": "#1e88e5", "보라": "#8e24aa", "분홍": "#ec407a"}
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
SIDE_W = 78
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
    fams = tkfont.families(root)
    pix = "Galmuri11" if "Galmuri11" in fams else "맑은 고딕"
    body = next((f for f in ("맑은 고딕", "Malgun Gothic", "NanumGothic", "NanumBarunGothic") if f in fams), pix)
    FONTS["r"] = tkfont.Font(root, family=body, size=-13 * S)
    FONTS["b"] = tkfont.Font(root, family=body, size=-13 * S, weight="bold")
    FONTS["h"] = tkfont.Font(root, family=body, size=-15 * S, weight="bold")
    FONTS["t"] = tkfont.Font(root, family=pix, size=-24 * S, weight="bold")
    FONTS["m"] = tkfont.Font(root, family=body, size=-17 * S, weight="bold")


def sprite(name, scale):
    rows, pal = SPRITES[name]
    w, h = max(len(r) for r in rows), len(rows)
    img = tk.PhotoImage(width=w * scale, height=h * scale)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                img.put(pal[ch], to=(x * scale, y * scale, (x + 1) * scale, (y + 1) * scale))
    return img


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    """마크 GUI 는 각진 모서리 -> 그냥 사각형 (예전 둥근 사각형 자리)."""
    kw.pop("smooth", None)
    return cv.create_rectangle(x0, y0, x1, y1, **kw)


def bevel(cv, x0, y0, x1, y1, face, hi=None, lo=None, border="#000000", t=None, tag=""):
    """마크 GUI 입체 칸: 검은 테두리 + 위·왼쪽 밝은 선 + 아래·오른쪽 어두운 선. hi/lo 를 바꾸면 들어간 칸."""
    hi, lo, t = hi or BEV_HI, lo or BEV_LO, t or 2 * S
    cv.create_rectangle(x0, y0, x1, y1, fill=border, outline="", tags=tag)
    b = max(1, S)
    cv.create_rectangle(x0 + b, y0 + b, x1 - b, y1 - b, fill=face, outline="", tags=tag)
    cv.create_rectangle(x0 + b, y0 + b, x1 - b, y0 + b + t, fill=hi, outline="", tags=tag)
    cv.create_rectangle(x0 + b, y0 + b, x0 + b + t, y1 - b, fill=hi, outline="", tags=tag)
    cv.create_rectangle(x0 + b, y1 - b - t, x1 - b, y1 - b, fill=lo, outline="", tags=tag)
    cv.create_rectangle(x1 - b - t, y0 + b, x1 - b, y1 - b, fill=lo, outline="", tags=tag)


def slot(cv, x0, y0, x1, y1, fill=None, tag=""):
    """들어간 칸 (아이템 칸·트랙): 위·왼쪽 어둡고 아래·오른쪽 밝음."""
    fill = fill or LINE
    bevel(cv, x0, y0, x1, y1, fill, hi="#373737", lo="#ffffff" if PANEL == "#c6c6c6" else "#5c5c5c",
          border=fill, t=max(1, S), tag=tag)


def shadow_text(cv, x, y, text, font, fill="#ffffff", **kw):
    """마크 글자처럼 오른쪽 아래 그림자."""
    cv.create_text(x + max(1, S), y + max(1, S), text=text, font=font, fill="#3f3f3f", **kw)
    return cv.create_text(x, y, text=text, font=font, fill=fill, **kw)


# ---------------------------------------------------------------- 위젯
class PixelButton(tk.Canvas):
    """알약 모양 버튼. variant: gray(살구) / green(코랄) / red(진갈색) / mint"""

    def __init__(self, parent, text, command, variant="gray", width=None, height=None, font=None, bg=None):
        self.font = font or FONTS["b"]
        bg = bg or parent["bg"]
        super().__init__(parent, width=width or self.font.measure(text) + 30 * S, height=height or 28 * S,
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
        w = self.winfo_width() if self.winfo_width() > 2 else int(self["width"])
        h = int(self["height"])
        face, fg, line, hov = BTN[self.variant]
        if self.pressed:
            bevel(self, 0, 0, w, h, face, hi="#3a3a3a", lo="#9a9a9a")
        else:
            bevel(self, 0, 0, w, h, hov if self.hover else face, hi="#ffffff" if not self.hover else "#d7dcff",
                  lo="#2e2e2e")
            if self.hover:
                self.create_rectangle(0, 0, w - 1, h - 1, outline="#ffffff", width=max(1, S))
        dy = S if self.pressed else 0
        shadow_text(self, w / 2, h / 2 + dy, self.text, self.font, fg)


class PixelCheck(tk.Frame):
    """체크박스는 토글 스위치, radio_value 가 있으면 동그란 라디오."""

    def __init__(self, parent, text, variable, command=None, radio_value=None, bg=None, fg=None):
        bg, fg = bg or parent["bg"], fg or TXT
        super().__init__(parent, bg=bg)
        self.var, self.rv, self.command, self.bgc = variable, radio_value, command, bg
        w, h = (16 * S, 16 * S) if radio_value is not None else (34 * S, 18 * S)
        self.box = tk.Canvas(self, width=w, height=h, bg=bg, highlightthickness=0, cursor="hand2")
        lbl = tk.Label(self, text=text, bg=bg, fg=fg, font=FONTS["r"], cursor="hand2")
        if radio_value is not None:
            self.box.pack(side="left")
            lbl.pack(side="left", padx=(5 * S, 0))
        else:
            lbl.pack(side="left", padx=(0, 6 * S))
            self.box.pack(side="left")
        for x in (self.box, lbl):
            x.bind("<Button-1>", self.click)
        variable.trace_add("write", lambda *a: self.draw())
        self.draw()

    def checked(self):
        return self.var.get() == self.rv if self.rv is not None else bool(self.var.get())

    def click(self, e=None):
        self.var.set(self.rv if self.rv is not None else not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        c = self.box
        c.delete("all")
        on = self.checked()
        if self.rv is not None:
            n = 16 * S
            slot(c, 0, 0, n, n, fill="#8b8b8b")
            if on:
                c.create_rectangle(4 * S, 4 * S, n - 4 * S, n - 4 * S, fill="#55ff55", outline="#1f5f1f")
            return
        w, h = 34 * S, 18 * S
        slot(c, 0, 0, w, h, fill="#3f9a46" if on else "#555555")
        k = h - 4 * S
        x = w - 2 * S - k if on else 2 * S
        bevel(c, x, 2 * S, x + k, 2 * S + k, "#c6c6c6", hi="#ffffff", lo="#555555", t=max(1, S))


class Panel(tk.Frame):
    """둥근 흰 카드. 내용은 .content 에."""

    def __init__(self, parent, title, icon=None):
        super().__init__(parent, bg=SKY)
        self.pad = 14 * S
        self.cv = tk.Canvas(self, width=PANEL_W, height=40, bg=SKY, highlightthickness=0, bd=0)
        self.cv.pack()
        self.body = tk.Frame(self.cv, bg=PANEL)
        head = tk.Frame(self.body, bg=PANEL)
        head.pack(anchor="w", pady=(0, 6 * S))
        if icon:
            tk.Label(head, image=icon, bg=PANEL).pack(side="left", padx=(0, 6 * S))
        tk.Label(head, text=title, font=FONTS["h"], fg=TXT, bg=PANEL).pack(side="left")
        self.content = tk.Frame(self.body, bg=PANEL)
        self.content.pack(fill="x")
        self.cv.create_window(self.pad, self.pad - 2 * S, window=self.body, anchor="nw",
                              width=PANEL_W - 2 * self.pad)
        self.body.bind("<Configure>", self.redraw)

    def redraw(self, e=None):
        h = self.body.winfo_reqheight() + 2 * self.pad - 4 * S
        self.cv.configure(height=h)
        self.cv.delete("bev")
        bevel(self.cv, 0, 0, PANEL_W, h, PANEL, t=3 * S, tag="bev")
        self.cv.tag_lower("bev")


def label(parent, text="", font="r", fg=None, **kw):
    return tk.Label(parent, text=text, font=FONTS[font], fg=fg or TXT, bg=parent["bg"], **kw)


class NavItem(tk.Canvas):
    """왼쪽 메뉴 버튼 (아이콘 + 글자, 선택되면 분홍 배경)."""

    def __init__(self, parent, icon, text, command):
        super().__init__(parent, width=SIDE_W - 12 * S, height=58 * S, bg=SIDEBAR, highlightthickness=0,
                         cursor="hand2")
        self.icon, self.text, self.command, self.selected = icon, text, command, False
        self.bind("<Button-1>", lambda e: command())
        self.draw()

    def select(self, on):
        self.selected = on
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        if self.selected:
            bevel(self, 2 * S, 2 * S, w - 2 * S, h - 2 * S, NAV_SEL)
        else:
            slot(self, 4 * S, 4 * S, w - 4 * S, h - 4 * S, fill="#2c2c2c" if PANEL == "#c6c6c6" else "#1e1e1e")
        self.create_image(w / 2, h / 2 - 8 * S, image=self.icon)
        self.create_text(w / 2, h - 13 * S, text=self.text, font=FONTS["r"] if not self.selected else FONTS["b"],
                         fill=TXT if self.selected else NAV_TXT)


class PixelStepper(tk.Frame):
    """( - )  [ 값 ]  ( + )"""

    def __init__(self, parent, var, lo, hi, step, width=5):
        bg = parent["bg"]
        super().__init__(parent, bg=bg)
        self.var, self.lo, self.hi, self.step = var, lo, hi, step
        self.dec = 0 if float(step).is_integer() else len(str(step).split(".")[1])
        n = 24 * S
        PixelButton(self, "−", lambda: self.bump(-1), width=n, height=n, bg=bg).pack(side="left")
        tk.Entry(self, textvariable=var, width=width, font=FONTS["b"], justify="center", bg="#000000",
                 fg="#ffffff", insertbackground="#ffffff", relief="flat", bd=0, highlightthickness=1,
                 highlightbackground="#a0a0a0", highlightcolor="#ffffff").pack(
            side="left", padx=4 * S, ipady=3 * S)
        PixelButton(self, "+", lambda: self.bump(1), width=n, height=n, bg=bg).pack(side="left")

    def bump(self, d):
        try:
            v = float(self.var.get())
        except ValueError:
            v = self.lo
        v = min(self.hi, max(self.lo, v + d * self.step))
        self.var.set(f"{v:.{self.dec}f}" if self.dec else str(int(round(v))))


_POLLER = None


def hotkey(key, fn, gap=0.4):
    """F7/F8/F12 단축키. add_hotkey 는 Alt+Tab 뒤에 Alt 를 계속 눌린 걸로 착각해서
    F8 이 'Alt+F8' 로 취급돼 안 먹는 문제가 있음 -> 다른 키 상태와 상관없이 그 키만 보고 반응.
    꾹 누를 때 반복 입력은 gap 초 안이면 무시. 윈도우에선 키 상태를 직접 물어보는 방식(KeyPoller)."""
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

        tk.Label(self, text=guide, font=FONTS["b"], fg=ACCENT, bg=GUIDE_BG, justify="left",
                 padx=10 * S, pady=6 * S, highlightthickness=0
                 ).pack(anchor="w", padx=10 * S, pady=(8 * S, 6 * S))
        self.cv = tk.Canvas(self, width=vw, height=vh, highlightthickness=2 * S, highlightbackground=LINE,
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
        ("left_click_cps", "미니게임 중 좌클릭 (초당, 0=끔)", 0, 20, 1),
        ("lead_sec", "바 움직임 예측(초)", 0.0, 0.3, 0.01),
        ("cast_settle_sec", "던진 뒤 대기(초)", 0.5, 5, 0.1),
        ("bite_timeout_sec", "입질 최대 대기(초)", 10, 120, 5),
        ("recast_delay_sec", "다시 던지기 전 대기(초)", 0.2, 5, 0.1),
        ("start_delay_sec", "시작 버튼 후 대기(초)", 0, 10, 1),
        ("max_fails", "연속 실패 이만큼이면 멈춤", 1, 50, 1),
    ]

    def __init__(self):
        global S, PANEL_W
        self.cfg = load_config()
        self.q = queue.Queue()
        self.waiting_item = None
        self.f7 = threading.Event()

        self.theme = self.cfg.get("theme", "light")
        self.page = "fish"
        self.topmost = True
        self.notes = []
        apply_theme(self.theme)
        register_fonts()
        self.root = tk.Tk()
        S = max(1, round(self.root.winfo_fpixels("1i") / 96))
        PANEL_W = 400 * S
        globals()["SIDE_W"] = 78 * S
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
        self.show_page("fish")

        self.macro = None
        threading.Thread(target=self.worker, daemon=True).start()
        self.quit_req = threading.Event()
        hotkey("f8", self.toggle)
        hotkey("f12", self.quit_req.set)                  # 완전 종료 (tk 는 tick 에서 닫음)
        hotkey("f7", self.f7.set)

        self.refresh_status()
        self.anim_t = 0
        self.root.after(100, self.tick)
        self.root.after(150, self.animate)
        self.log("준비 완료! 왼쪽 '설정'에서 지정하고 '낚시'에서 시작해", "good")

    # ---------- 레이아웃 ----------
    def build(self):
        m = 10 * S
        self.root.configure(bg=SKY)
        self.build_header()
        main = tk.Frame(self.root, bg=SKY)
        main.pack(fill="both", expand=True)
        side = tk.Frame(main, bg=SIDEBAR, width=SIDE_W)
        side.pack(side="left", fill="y")
        # 페이지가 화면보다 길면 마우스 휠로 스크롤
        self.scroll_cv = tk.Canvas(main, bg=SKY, width=PANEL_W, height=200, highlightthickness=0, bd=0)
        self.scroll_cv.pack(side="left", fill="y", padx=m, pady=(m, m))
        area = tk.Frame(self.scroll_cv, bg=SKY)
        self.scroll_cv.create_window(0, 0, window=area, anchor="nw")
        area.bind("<Configure>", lambda e: self.fit_scroll())
        self.scroll_area = area
        self.root.bind_all("<MouseWheel>", self.on_wheel)
        self.pages = {k: tk.Frame(area, bg=SKY) for k in ("fish", "log", "rod", "setup", "adv", "guide")}
        self.nav = {}
        for k, ic, text in (("fish", "fish", "낚시"), ("log", "book", "기록"), ("rod", "rod", "낚싯대"),
                             ("setup", "bobber", "설정"), ("adv", "emerald", "세부"), ("guide", "chat", "가이드")):
            self.nav[k] = NavItem(side, self.icons[ic], text, lambda k=k: self.show_page(k))
            self.nav[k].pack(padx=6 * S, pady=(8 * S if k == "fish" else 2 * S, 0))
        bottom = tk.Frame(side, bg=SIDEBAR)
        bottom.pack(side="bottom", pady=10 * S)
        n = 40 * S
        PixelButton(bottom, "☀" if self.theme == "dark" else "☾", self.toggle_theme, width=n, height=n,
                    font=FONTS["m"]).pack(pady=(0, 6 * S))
        self.pin_btn = PixelButton(bottom, "고정", self.toggle_top, "mint" if self.topmost else "gray",
                                   width=n + 8 * S, height=26 * S)
        self.pin_btn.pack()
        PixelButton(bottom, "작게", self.toggle_mini, width=n + 8 * S, height=26 * S).pack(pady=(6 * S, 0))
        self.root.attributes("-topmost", self.topmost)
        self.main_frame = main

        p1 = Panel(self.pages["setup"], "화면 위치 설정", self.icons["bobber"])
        p1.pack()
        c = p1.content
        c.columnconfigure(2, weight=1)
        self.status_lbl = {}
        bf = tk.Frame(c, bg=PANEL)
        bf.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4 * S))
        label(bf, "입질 감지 :", "b").pack(side="left", padx=(0, 6 * S))
        self.bite_mode = tk.StringVar(value=self.cfg["bite_mode"])
        PixelCheck(bf, "자막 (추천)", self.bite_mode, self.change_mode, radio_value="subtitle").pack(
            side="left", padx=(0, 8 * S))
        PixelCheck(bf, "찌 화면", self.bite_mode, self.change_mode, radio_value="bobber").pack(
            side="left", padx=(0, 8 * S))
        PixelCheck(bf, "둘 다", self.bite_mode, self.change_mode, radio_value="both").pack(side="left")
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
        self.guide = tk.Label(c, text="", font=FONTS["b"], fg=ACCENT, bg=GUIDE_BG, padx=8 * S, pady=6 * S,
                              highlightthickness=0,
                              wraplength=PANEL_W - 40 * S, justify="left")
        self.guide_row = len(rows) + 2

        p2 = Panel(self.pages["fish"], "낚시 시작", self.icons["rod"])
        p2.pack()
        self.run_btn = PixelButton(p2.content, "▶ 낚시 시작! (F8)", self.toggle, "green",
                                   width=PANEL_W - 30 * S, height=44 * S, font=FONTS["m"])
        self.run_btn.pack(pady=(0, 4 * S))
        self.pipe_cv = tk.Canvas(p2.content, width=PANEL_W - 30 * S, height=40 * S, bg=PANEL, highlightthickness=0)
        self.pipe_cv.pack(pady=(4 * S, 0))
        self.state_lbl = label(p2.content, "정지됨", "b")
        self.state_lbl.pack()
        label(p2.content, "시작하면 마크 창으로 자동 전환돼. 게임 중엔 F8", fg=MUTED).pack()
        gf = tk.Frame(p2.content, bg=PANEL)
        gf.pack(fill="x", pady=(8 * S, 0))
        tk.Label(gf, image=self.icons["emerald"], bg=PANEL).pack(side="left", padx=(0, 6 * S))
        label(gf, "목표", "b").pack(side="left", padx=(0, 6 * S))
        self.goal_n_var = tk.StringVar(value=str(self.cfg["goal_count"]))
        self.goal_m_var = tk.StringVar(value=str(self.cfg["goal_minutes"]))
        spinbox(gf, self.goal_n_var, 0, 100000, 10).pack(side="left")
        label(gf, "마리").pack(side="left", padx=(3 * S, 8 * S))
        spinbox(gf, self.goal_m_var, 0, 100000, 10).pack(side="left")
        label(gf, "분 (0=끔)").pack(side="left", padx=(3 * S, 0))
        for var in (self.goal_n_var, self.goal_m_var):
            var.trace_add("write", lambda *a: self.save_goals())
        bgf = tk.Frame(p2.content, bg=PANEL)
        bgf.pack(fill="x", pady=(8 * S, 0))
        tk.Label(bgf, image=self.icons["heart"], bg=PANEL).pack(side="left", padx=(0, 6 * S))
        label(bgf, "다른 창 쓰면서 낚시", "b").pack(side="left")
        label(bgf, "(실험 · 가이드 참고)", fg=MUTED).pack(side="left", padx=(4 * S, 0))
        self.bg_var = tk.BooleanVar(value=self.cfg["background"])
        PixelCheck(bgf, "", self.bg_var, self.save_background).pack(side="right")
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

        pd = Panel(self.pages["fish"], "낚시 기록", self.icons["fish"])
        pd.pack(pady=(8 * S, 0))
        self.dash_cv = tk.Canvas(pd.content, width=PANEL_W - 30 * S, height=64 * S, bg=PANEL, highlightthickness=0)
        self.dash_cv.pack()
        self.chips = tk.Frame(pd.content, bg=PANEL)
        self.chips.pack(fill="x", pady=(6 * S, 0))
        self.spark_cv = tk.Canvas(pd.content, width=PANEL_W - 30 * S, height=46 * S, bg=PANEL, highlightthickness=0)
        self.spark_cv.pack(pady=(4 * S, 0))
        self.elapsed = 0.0

        p3 = Panel(self.pages["fish"], "실시간 상태", self.icons["heart"])
        p3.pack(pady=(8 * S, 0))
        g = tk.Frame(p3.content, bg=PANEL)
        g.pack(fill="x")
        self.vals = {}
        for i, (k, ic, name) in enumerate([("bite", "chat", "입질 감지"), ("dura", "rod", "내구도"),
                                           ("gauge", "emerald", "게이지")]):
            r, col = divmod(i, 2)
            tk.Label(g, image=self.icons[ic], bg=PANEL, width=24 * S).grid(row=r, column=col * 3, pady=2 * S)
            label(g, name).grid(row=r, column=col * 3 + 1, sticky="w", padx=(2 * S, 6 * S))
            v = label(g, "-", "b", width=9, anchor="w")
            v.grid(row=r, column=col * 3 + 2, sticky="w")
            self.vals[k] = v
        self.dura_cv = tk.Canvas(g, width=40 * S, height=8 * S, bg=PANEL, highlightthickness=0)
        self.bar_cv = tk.Canvas(p3.content, width=PANEL_W - 16 * S, height=30 * S, bg=PANEL, highlightthickness=0)
        self.bar_cv.pack(pady=(6 * S, 0))
        self.live = tk.Frame(p3.content, bg=PANEL)       # 찌 실시간 화면 (찌/둘 다 모드)
        self.live_img = tk.Label(self.live, bg=PANEL)
        self.live_img.pack(side="left")
        self.trace_cv = tk.Canvas(self.live, width=PANEL_W - 2 * 14 * S - 188 * S, height=90 * S, bg=PANEL, highlightthickness=0)
        self.trace_cv.pack(side="left", padx=(8 * S, 0))
        self.live_photo = None

        self.build_rod_page()
        self.build_log_page()

        self.adv = Panel(self.pages["adv"], "세부 설정", self.icons["emerald"])
        self.adv.pack()
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
        self.logf_var = tk.BooleanVar(value=self.cfg["log_file"])
        PixelCheck(a, "로그 남기기 (exe 옆 macro.log, 다음 시작부터)", self.logf_var).grid(
            row=len(self.SETTINGS) + 1, column=0, columnspan=2, sticky="w", pady=(4 * S, 0))
        PixelButton(a, "설정 저장", self.save_adv, "green").grid(
            row=len(self.SETTINGS) + 2, column=0, columnspan=2, pady=(6 * S, 0))

        pn = Panel(self.pages["adv"], "디스코드 알림", self.icons["chat"])
        pn.pack(pady=(8 * S, 0))
        label(pn.content, "멈출 때(목표 달성·내구도·연속 실패·오류) 디스코드로 알려줘. 채널 설정 → 연동 → 웹후크 주소",
              fg=MUTED, wraplength=PANEL_W - 40 * S, justify="left").pack(anchor="w")
        self.hook_var = tk.StringVar(value=self.cfg["discord_webhook"])
        tk.Entry(pn.content, textvariable=self.hook_var, font=FONTS["r"], bg=SOFT, fg=TXT, insertbackground=TXT,
                 relief="flat", bd=0, highlightthickness=0).pack(fill="x", pady=(6 * S, 0), ipady=5 * S)
        hr = tk.Frame(pn.content, bg=PANEL)
        hr.pack(fill="x", pady=(6 * S, 0))
        self.each_var = tk.BooleanVar(value=self.cfg["notify_each_catch"])
        PixelCheck(hr, "낚을 때마다 알림", self.each_var, self.save_hook).pack(side="left")
        PixelButton(hr, "저장 + 테스트", self.test_hook, "green").pack(side="right")

        self.build_guide()

        self.note_panel = Panel(self.pages["fish"], "알림", self.icons["chat"])
        self.note_panel.pack(pady=(8 * S, 0))
        self.note_lbls = []
        tip = tk.Frame(self.note_panel.content, bg=TIP_BG, highlightthickness=2 * S, highlightbackground="#2a0a5e",
                       padx=8 * S, pady=6 * S)      # 마크 아이템 툴팁 모양
        tip.pack(fill="x")
        for _ in range(4):
            lb = tk.Label(tip, text="", font=FONTS["r"], bg=TIP_BG, fg="#aaaaaa", anchor="w", justify="left",
                          wraplength=PANEL_W - 50 * S)
            lb.pack(fill="x", anchor="w")
            self.note_lbls.append(lb)

    GUIDE = [
        ("처음 한 번만", [
            "마크 설정 → 접근성 → 자막 표시 켜기",
            "접근성 → 텍스트 배경 불투명도 올리기 (자막이 잘 보여야 함)",
            "왼쪽 '설정' → 입질 자막 → 지정하기 → 직접 낚시하다 자막 뜨면 F7",
            "미니게임 바, 낚싯대 내구도는 자동으로 찾음 (안 되면 '직접')",
        ]),
        ("잘 낚이게 하는 마크 설정", [
            "파티클: 최소  (물보라·거품이 찌/화면 판정을 방해함)",
            "GUI 배율이 바뀌면(자동 배율은 창 크기 따라 바뀜) 자막·바는 자동으로 맞춤. 안 맞으면 다시 지정",
            "밤·물속처럼 어두우면 찌 화면 모드는 어려움 → 자막 모드 사용",
            "낚싯대는 핫바에서 선택한 상태로, 물을 바라보고 시작",
        ]),
        ("낚싯대 탭 (교체·정밀 내구도·인벤)", [
            "자동 교체: 낚싯대를 넣은 핫바 칸을 눌러 고르고 켜기. 내구도 기준 아래면 다음 칸으로",
            "정밀 내구도(실험): 마크에서 F3+H(고급 툴팁) 켜기. N마리마다 인벤을 1~2초 열었다 닫음",
            "인벤 가득 참: 빈칸 기준 이하면 멈추고 디스코드 알림. 인벤 확인 때 같이 셈",
            "리소스팩으로 인벤/툴팁 모양이 바뀌면 안 될 수 있음 → '툴팁 숫자 못 읽음'이 뜨면 꺼줘",
        ]),
        ("모루 자동 수리 (실험)", [
            "모루는 낚시 자리 바로 뒤(뒤돌면 십자선에 걸리게) 1~2칸에 두는 걸 추천",
            "낚싯대 탭 → 낚싯대 칸·실 칸 고르기 → '방향 기록하기': 물 보고 F7, 모루 보고 F7",
            "또는 감도 %(마크 설정 숫자)와 각도(뒤돌기 = 180) 넣고 '각도로 쓰기'",
            "모루 창을 빈 상태로 열고 '수리 창 위치 지정' → F7 → 칸 6곳 클릭",
            "'골드 숫자 영역'을 지정하면 수리비보다 적을 때 미리 멈추고 알림",
            "마크 설정 > 마우스 > 원시 입력 켜짐 필요. 일반 모드에서만 됨",
        ]),
        ("다른 창 쓰면서 낚시 (실험)", [
            "마크에서 F3+P 한 번 → '포커스를 잃으면 일시정지' 꺼짐",
            "마크 창은 최소화하지 말고 다른 창 뒤에 두기만",
            "마크 창 크기·위치는 지정할 때와 같게",
            "안 되면 '이 PC에선 캡처할 수 없어' 알림 → 이 기능 끄고 사용",
            "마크가 뒤로 가면 끊길 때: 비디오 설정 → '비활성 FPS 제한'을 '최소화 시'로",
            "Dynamic FPS 모드나 런처(루나·페더 등)를 쓰면 '포커스 없을 때 FPS'를 60 이상으로",
            "NVIDIA 제어판 → '백그라운드 응용 프로그램 최대 프레임 속도' 끄기",
            "윈도우 설정 → 디스플레이 → 그래픽 → javaw.exe 를 '고성능'으로",
        ]),
        ("멈추는 경우", [
            "내구도가 정한 % 이하 (수선 낚싯대는 '안 봄')",
            "연속으로 못 낚으면 (기본 5번) 알림 띄우고 멈춤",
            "일반 모드에서 마크 창이 뒤로 가면 잠깐 멈췄다가 돌아오면 계속",
        ]),
    ]

    def build_guide(self):
        for i, (title, lines) in enumerate(self.GUIDE):
            p = Panel(self.pages["guide"], title, self.icons[("chat", "emerald", "heart", "rod", "chest", "book")[i % 6]])
            p.pack(pady=(0 if i == 0 else 8 * S, 0))
            for ln in lines:
                row = tk.Frame(p.content, bg=PANEL)
                row.pack(fill="x", anchor="w")
                label(row, "•", "b", fg=ACCENT).pack(side="left", anchor="n", padx=(0, 6 * S))
                label(row, ln, anchor="w", justify="left", wraplength=PANEL_W - 60 * S).pack(side="left", fill="x")

    def fit_scroll(self):
        """창 높이는 페이지 길이에 맞추되 화면보다 길면 잘라서 스크롤."""
        cv = self.scroll_cv
        need = self.scroll_area.winfo_reqheight()
        room = self.root.winfo_screenheight() - 92 * S - 20 * S - 90      # 헤더·여백·작업표시줄
        cv.configure(height=max(200, min(need, room)), scrollregion=(0, 0, PANEL_W, need))

    def on_wheel(self, e):
        try:
            if e.widget.winfo_toplevel() is not self.root:
                return                               # 다른 창(영역 지정 등)은 무시
        except (tk.TclError, AttributeError):
            return
        cv = self.scroll_cv
        if self.scroll_area.winfo_reqheight() > cv.winfo_height():
            cv.yview_scroll(int(-e.delta / 120) * 3, "units")

    def show_page(self, key):
        self.page = key
        if key == "log":
            self.draw_log_page()
        elif key == "rod":
            self.draw_rod_page()
        for k, f in self.pages.items():
            f.pack_forget()
            self.nav[k].select(k == key)
        self.pages[key].pack(fill="both", expand=True)
        self.scroll_cv.yview_moveto(0)
        self.root.after(10, self.fit_scroll)

    def toggle_top(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.pin_btn.set(variant="mint" if self.topmost else "gray")

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.cfg["theme"] = self.theme
        save_config(self.cfg)
        self.rebuild()

    def rebuild(self):
        """테마 바꾸면 화면을 새로 그림 (매크로는 계속 돎)."""
        apply_theme(self.theme)
        self.icons_big.pop("fish_r", None)
        for w in self.root.winfo_children():
            w.destroy()
        self.build()
        self.show_page(self.page)
        self.refresh_status()
        self.render_notes()

    def build_header(self):
        W, H = SIDE_W + PANEL_W + 20 * S, 92 * S
        cv = self.header = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bg=SKY)
        cv.pack()
        bands = HEADER + [SKY]
        bh = H // len(bands)
        for i, col in enumerate(bands):
            cv.create_rectangle(0, i * bh, W, (i + 1) * bh + bh, fill=col, outline="")
        P = 4 * S
        for cx, cy, cw in ((12, 14, 7), (W // S - 46, 8, 8)):
            cv.create_rectangle(cx * S, cy * S, cx * S + cw * P, cy * S + 2 * P, fill=CLOUD, outline="")
            cv.create_rectangle(cx * S + P, cy * S - P, cx * S + (cw - 3) * P, cy * S, fill=CLOUD, outline="")

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

    def celebrate(self):
        """낚을 때 헤더에 '+1' 이 떠오름."""
        if getattr(self, "mini", None):
            return
        cv = self.header
        x = int(cv["width"]) - 60 * S
        t = cv.create_text(x, self.h_water_y, text="+1", font=FONTS["t"], fill="#ffd866")

        def rise(k=0):
            if k >= 12:
                cv.delete(t)
                return
            cv.move(t, 0, -3 * S)
            self.root.after(60, lambda: rise(k + 1))
        rise()

    @staticmethod
    def flip(img):
        w, h = img.width(), img.height()
        out = tk.PhotoImage(width=w, height=h)
        for y in range(h):
            for x in range(w):
                if not img.transparency_get(x, y):
                    out.put("#%02x%02x%02x" % img.get(x, y), (w - 1 - x, y))
        return out

    # ---------- 매크로 스레드 ----------
    def worker(self):
        self.macro = Macro(self.cfg, out=self.q.put, hotkeys=False)
        self.macro.run()

    def log(self, msg, tag=None):
        if tag is None:
            tag = ("bad" if ("오류" in msg or "알림" in msg or "정지 ->" in msg) else
                   "good" if ("입질" in msg or "끝" in msg or "완료" in msg or "감지" in msg) else
                   "warn" if ("시작" in msg or "F7" in msg) else None)
        line = msg.splitlines()[0] if msg else ""
        self.notes.insert(0, (time.strftime("%H:%M"), line, tag))
        del self.notes[4:]
        self.render_notes()

    def render_notes(self):
        colors = {"good": "#55ff55", "warn": "#ffff55", "bad": "#ff5555"}
        for i, lb in enumerate(self.note_lbls):
            if i >= len(self.notes):
                lb.config(text="")
                continue
            t, text, tag = self.notes[i]
            lb.config(text=f"{t}  {text}", fg=colors.get(tag, "#ffffff") if i == 0 else "#aaaaaa")

    def tick(self):
        """화면 갱신. 그리다 오류가 나도 갱신은 계속 (멈추면 버튼/상태가 안 바뀌어 '정지 안 됨'처럼 보임)."""
        try:
            self.tick_body()
        except Exception:
            if not getattr(self, "_tick_err", False):
                self._tick_err = True
                from fishing_macro import save_error
                save_error(traceback.format_exc())
        self.root.after(100, self.tick)

    def tick_body(self):
        if self.quit_req.is_set():
            self.close()
            return
        while not self.q.empty():
            self.log(self.q.get())

        if self.f7.is_set() and getattr(self, "turn_stage", 0):
            self.f7.clear()
            self.turn_record_f7()
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
            self.draw_pipeline(m)
            self._tick_n = getattr(self, "_tick_n", 0) + 1
            if self.page == "rod" and self._tick_n % 5 == 0:
                self.draw_rod_page()
            if self.page == "log" and self._tick_n % 30 == 0:
                self.draw_log_page()
            self.draw_dashboard(m)
            self.draw_live(s)
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
            if getattr(self, "mini", None):
                self.mini_lbl.config(text=f"{m.run_caught}마리")
                self.mini_btn.set("■ 정지 (F8)" if m.running else "▶ 시작 (F8)", "red" if m.running else "green")
            if s["caught"] != getattr(self, "_last_caught", s["caught"]):
                self.celebrate()
            self._last_caught = s["caught"]
            if self.cfg["bar_roi"] and not self.status_lbl["bar"].cget("text").startswith("● 찾음"):
                self.refresh_status()

    def draw_durability(self, d):
        v = self.vals["dura"]
        if d is None:
            v.config(text="-", fg=TXT)
            self.dura_cv.grid_forget()
            return
        val, kind = d
        mx = (self.macro and self.macro.stats.get("dura_max")) or self.cfg["durability_max"]
        stop = mx * self.cfg["durability_stop_pct"] / 100
        danger = not self.cfg["durability_ignore"] and (kind == "low" or val <= stop)
        v.config(text=f"{'1~2' if kind == 'low' else val}/{mx}" + (" ✓" if kind == "exact" else ""), width=9,
                 fg=MUTED if self.cfg["durability_ignore"] else BAD if danger else OK)
        frac = 0 if kind == "low" else min(1, val / mx)
        r, g, b = colorsys.hsv_to_rgb(frac / 3, 1, 1)
        c = self.dura_cv
        c.delete("all")
        c.create_rectangle(0, 0, 40 * S, 8 * S, fill="#000000", outline="")
        if frac > 0:
            c.create_rectangle(S, S, S + round(38 * S * frac), 6 * S, outline="",
                               fill="#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
        c.grid(row=0, column=6, sticky="w")

    # ---------- 낚싯대 페이지 ----------
    def build_rod_page(self):
        pg, c = self.pages["rod"], self.cfg
        W = PANEL_W - 30 * S

        def head(panel, var, text, cmd):
            r = tk.Frame(panel.content, bg=PANEL)
            r.pack(fill="x")
            PixelCheck(r, text, var, cmd).pack(side="left")
            return r

        def desc(panel, text):
            label(panel.content, text, fg=MUTED, wraplength=W, justify="left").pack(anchor="w", pady=(4 * S, 0))

        # 자동 교체
        p = Panel(pg, "낚싯대 자동 교체", self.icons["rod"])
        p.pack()
        self.swap_var = tk.BooleanVar(value=c["rod_swap"])
        head(p, self.swap_var, "켜기", self.save_rod)
        desc(p, "내구도가 멈춤 기준(낚시 탭의 %) 아래로 내려가면 아래에서 고른 칸 중 다음 칸으로 바꿔서 계속 낚아. "
                "고른 칸을 다 쓰면 멈춤. 칸을 눌러서 고르기")
        self.slot_cv = tk.Canvas(p.content, width=W, height=58 * S, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.slot_cv.pack(pady=(8 * S, 0))
        self.slot_cv.bind("<Button-1>", self.click_slot)
        self.swap_lbl = label(p.content, "", fg=MUTED)
        self.swap_lbl.pack(anchor="w", pady=(4 * S, 0))

        # 정밀 내구도
        p = Panel(pg, "정밀 내구도  (실험)", self.icons["chat"])
        p.pack(pady=(8 * S, 0))
        self.exact_var = tk.BooleanVar(value=c["exact_durability"])
        head(p, self.exact_var, "켜기", self.save_rod)
        desc(p, "인벤을 잠깐 열어 낚싯대에 마우스를 올리고, 툴팁의 '내구도: 57 / 64' 숫자를 그대로 읽어. "
                "마크에서 F3+H(고급 툴팁)를 한 번 눌러둬야 해. 최대 내구도도 자동으로 맞춰짐")
        r = tk.Frame(p.content, bg=PANEL)
        r.pack(fill="x", pady=(8 * S, 0))
        label(r, "인벤 확인: ").pack(side="left")
        self.every_var = tk.StringVar(value=str(c["inv_check_every"]))
        spinbox(r, self.every_var, 1, 200, 1).pack(side="left")
        label(r, " 마리마다").pack(side="left")
        PixelButton(r, "다음에 바로 확인", self.check_now, "green").pack(side="right")
        label(p.content, "읽을 낚싯대 칸  (자동 = 지금 들고 있는 칸)",
              fg=MUTED).pack(anchor="w", pady=(8 * S, 2 * S))
        self.eslot_cv = tk.Canvas(p.content, width=W, height=34 * S, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.eslot_cv.pack()
        self.eslot_cv.bind("<Button-1>", self.click_eslot)
        self.every_var.trace_add("write", lambda *a: self.save_rod())

        # 모루 자동 수리
        p = Panel(pg, "모루 자동 수리  (실험)", self.icons["chest"])
        p.pack(pady=(8 * S, 0))
        self.repair_var = tk.BooleanVar(value=c["repair_on"])
        head(p, self.repair_var, "켜기 (내구도가 멈춤 기준 아래면 수리)", self.save_repair)
        desc(p, "모루 쪽으로 시점을 돌려 수리 창을 열고, 낚싯대·실을 Shift+클릭 -> ✓ -> 수리된 낚싯대를 원래 칸으로 "
                "-> 다시 물 쪽으로. 골드·실이 모자라면 멈추고 알림. 일반 모드에서만 됨")
        self.rslot_cvs = {}
        for key, name in (("repair_rod_slot", "낚싯대 칸"), ("repair_string_slot", "실 칸")):
            r = tk.Frame(p.content, bg=PANEL)
            r.pack(fill="x", pady=(6 * S, 0))
            label(r, name, width=7, anchor="w").pack(side="left")
            cv = tk.Canvas(r, width=W - 70 * S, height=28 * S, bg=PANEL, highlightthickness=0, cursor="hand2")
            cv.pack(side="left")
            cv.bind("<Button-1>", lambda e, k=key: self.click_rslot(k, e))
            self.rslot_cvs[key] = cv
        r = tk.Frame(p.content, bg=PANEL)
        r.pack(fill="x", pady=(8 * S, 0))
        label(r, "수리비").pack(side="left")
        self.cost_var = tk.StringVar(value=str(c["repair_cost"]))
        spinbox(r, self.cost_var, 0, 1000000, 50).pack(side="left", padx=(6 * S, 4 * S))
        label(r, "골드").pack(side="left")
        PixelButton(r, "골드 숫자 영역 (F7)", lambda: self.begin_set("gold")).pack(side="right")
        self.cost_var.trace_add("write", lambda *a: self.save_repair())

        label(p.content, "모루 방향: 기록하기 (추천) 또는 각도 입력", "b").pack(anchor="w", pady=(10 * S, 2 * S))
        r = tk.Frame(p.content, bg=PANEL)
        r.pack(fill="x")
        PixelButton(r, "방향 기록하기 (F7 두 번)", self.start_turn_record, "green").pack(side="left")
        PixelButton(r, "모루 보기 테스트", self.test_turn).pack(side="left", padx=(6 * S, 0))
        r = tk.Frame(p.content, bg=PANEL)
        r.pack(fill="x", pady=(6 * S, 0))
        self.sens_var = tk.StringVar(value=str(c["mouse_sens_pct"]))
        self.yaw_var = tk.StringVar(value="" if c["repair_yaw"] is None else str(c["repair_yaw"]))
        self.pitch_var = tk.StringVar(value=str(c["repair_pitch"]))
        for text, var, wdt in (("감도 %", self.sens_var, 4), ("좌우°", self.yaw_var, 5), ("위아래°", self.pitch_var, 4)):
            label(r, text).pack(side="left", padx=(0, 3 * S))
            tk.Entry(r, textvariable=var, width=wdt, font=FONTS["b"], justify="center", bg="#000000", fg="#ffffff",
                     insertbackground="#ffffff", relief="flat", highlightthickness=1,
                     highlightbackground="#a0a0a0").pack(side="left", padx=(0, 8 * S), ipady=2 * S)
        PixelButton(r, "각도로 쓰기", self.use_angle).pack(side="right")
        desc(p, "각도: 오른쪽·아래가 + (뒤돌기 = 180). 감도는 마크 설정 > 마우스 감도 숫자. DPI 는 상관없음")
        r = tk.Frame(p.content, bg=PANEL)
        r.pack(fill="x", pady=(8 * S, 0))
        PixelButton(r, "수리 창 위치 지정 (F7)", lambda: self.begin_set("repair")).pack(side="left")
        self.repair_lbl = label(p.content, "", fg=MUTED, wraplength=W, justify="left")
        self.repair_lbl.pack(anchor="w", pady=(6 * S, 0))

        # 인벤토리
        p = Panel(pg, "인벤토리 가득 참", self.icons["chest"])
        p.pack(pady=(8 * S, 0))
        self.full_var = tk.BooleanVar(value=c["inv_full_stop"])
        r = head(p, self.full_var, "빈칸이 없으면 멈춤", self.save_rod)
        self.min_empty_var = tk.StringVar(value=str(c["inv_min_empty"]))
        label(r, " 개 이하").pack(side="right")
        spinbox(r, self.min_empty_var, 0, 35, 1).pack(side="right")
        label(r, "빈칸 ").pack(side="right")
        self.min_empty_var.trace_add("write", lambda *a: self.save_rod())
        desc(p, "꽉 차면 낚은 물고기가 바닥에 떨어져서 손해. 위 '인벤 확인' 때 같이 셈")
        self.inv_cv = tk.Canvas(p.content, width=W, height=96 * S, bg=PANEL, highlightthickness=0)
        self.inv_cv.pack(pady=(8 * S, 0))
        self.inv_lbl = label(p.content, "아직 확인 안 함", fg=MUTED)
        self.inv_lbl.pack(anchor="w", pady=(4 * S, 0))
        self.draw_rod_page()

    def click_rslot(self, key, e):
        n = int(e.x // (int(self.rslot_cvs[key]["width"]) / 9)) + 1
        self.cfg[key] = min(9, max(1, n))
        save_config(self.cfg)
        self.draw_rod_page()

    def save_repair(self):
        c = self.cfg
        c["repair_on"] = self.repair_var.get()
        try:
            c["repair_cost"] = max(0, int(float(self.cost_var.get() or 0)))
        except ValueError:
            pass
        save_config(c)
        if c["repair_on"] and c["background"]:
            self.log("자동 수리는 일반 모드에서만 돼 ('다른 창 쓰면서 낚시'는 꺼줘)", "warn")
        self.draw_rod_page()

    def use_angle(self):
        try:
            sens = float(self.sens_var.get())
            yaw = float(self.yaw_var.get())
            pitch = float(self.pitch_var.get() or 0)
        except ValueError:
            messagebox.showwarning("모루 방향", "감도 %와 좌우 각도를 숫자로 넣어줘 (예: 69, 180)")
            return
        c = self.cfg
        c["mouse_sens_pct"], c["repair_yaw"], c["repair_pitch"] = sens, yaw, pitch
        c["repair_turn"] = None                      # 각도 방식으로
        save_config(c)
        from common import turn_pixels
        dx, dy = turn_pixels(yaw, pitch, sens)
        self.log(f"모루 방향: 각도로 설정 (좌우 {yaw:g}°, 위아래 {pitch:g}° = 마우스 {dx}, {dy})", "good")
        self.draw_rod_page()

    def start_turn_record(self):
        if not IS_WIN:
            messagebox.showinfo("모루 방향", "윈도우에서만 돼")
            return
        if self.macro and self.macro.running:
            messagebox.showinfo("안내", "매크로를 먼저 정지해줘")
            return
        self.turn_stage = 1
        self.f7.clear()
        self.repair_lbl.config(text="▶ 마크에서 낚시하던 방향(물)을 보고 F7", fg=ACCENT)
        self.log("모루 방향 기록: 물을 보고 F7 -> 모루를 십자선에 맞추고 F7", "warn")

    def turn_record_f7(self):
        if self.turn_stage == 1:
            self.turn_rec = winapi.RawMouseRecorder().start()
            self.turn_stage = 2
            self.repair_lbl.config(text="▶ 이제 마우스로 모루를 십자선 가운데에 맞추고 F7", fg=ACCENT)
        elif self.turn_stage == 2:
            dx, dy = self.turn_rec.stop()
            self.turn_stage = 0
            c = self.cfg
            c["repair_turn"] = [int(dx), int(dy)]
            save_config(c)
            self.log(f"모루 방향 기록 완료 (마우스 {dx}, {dy}). 마크에서 다시 물 쪽으로 돌려놔", "good")
            self.draw_rod_page()

    def test_turn(self):
        if not self.macro or self.macro.running:
            messagebox.showinfo("안내", "매크로가 정지된 상태에서 해줘")
            return
        turn = self.macro.turn_amount()
        if not turn:
            messagebox.showinfo("모루 방향", "먼저 방향을 기록하거나 각도를 넣어줘")
            return
        hwnd = winapi.find_minecraft()

        def run():
            if hwnd:
                winapi.bring_to_front(hwnd)
            time.sleep(0.6)
            winapi.send_mouse_move(*turn)
            time.sleep(2.0)
            winapi.send_mouse_move(-turn[0], -turn[1])
        threading.Thread(target=run, daemon=True).start()
        self.log("모루 보기 테스트: 2초 동안 모루를 보고 다시 돌아와. 십자선이 모루에 있는지 봐줘", "warn")

    def click_eslot(self, e):
        k = int(e.x // (int(self.eslot_cv["width"]) / 10))
        self.cfg["exact_slot"] = min(9, max(0, k))
        save_config(self.cfg)
        if self.macro:
            self.macro.exact = None                 # 다른 칸이면 예전 값은 버림
            self.macro.inv_due = True
        self.draw_rod_page()

    def click_slot(self, e):
        n = int(e.x // (int(self.slot_cv["width"]) / 9)) + 1
        slots = set(self.cfg["rod_slots"])
        slots ^= {n}
        self.cfg["rod_slots"] = sorted(slots)
        save_config(self.cfg)
        self.draw_rod_page()

    def save_rod(self):
        c = self.cfg
        c["rod_swap"], c["exact_durability"], c["inv_full_stop"] = (
            self.swap_var.get(), self.exact_var.get(), self.full_var.get())
        try:
            c["inv_check_every"] = max(1, int(float(self.every_var.get() or 1)))
            c["inv_min_empty"] = max(0, int(float(self.min_empty_var.get() or 0)))
        except ValueError:
            pass
        save_config(c)
        if c["rod_swap"] and c["durability_ignore"]:
            self.log("자동 교체는 내구도를 봐야 해: 낚시 탭의 '안 봄'을 꺼줘", "warn")

    def check_now(self):
        if self.macro and self.macro.running:
            self.macro.inv_due = True
            self.log("다음 던지기 전에 인벤 확인할게", "good")
        else:
            self.log("낚시 중일 때 눌러줘 (던지기 전에 인벤을 열어 확인)", "warn")

    def draw_rod_page(self):
        m = getattr(self, "macro", None)
        cur = m.stats.get("slot") if m else None
        dep = m.depleted if m else set()
        cv = self.slot_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        bw = W / 9
        for i in range(1, 10):
            x0 = (i - 1) * bw + 3 * S
            on = i in self.cfg["rod_slots"]
            fill = SOFT if not on else (LINE if i in dep else ACCENT)
            round_rect(cv, x0, 4 * S, x0 + bw - 6 * S, H - 16 * S, 10 * S, fill=fill,
                       outline=TXT if i == cur else "", width=2 * S)
            cv.create_text(x0 + (bw - 6 * S) / 2, (H - 12 * S) / 2, text=str(i), font=FONTS["m"],
                           fill="#ffffff" if on and i not in dep else MUTED)
            # 칸 아래 내구도 줄 (지금 칸 = 읽은 값, 다 쓴 칸 = 빨강)
            frac = None
            if i == cur and m and m.stats.get("dura"):
                val, kind = m.stats["dura"]
                mx = m.stats.get("dura_max") or self.cfg["durability_max"]
                frac = 0.05 if kind == "low" else min(1, val / max(1, mx))
            elif on and i in dep:
                frac = 0.05
            if frac is not None:
                bx0, bx1, by = x0 + 5 * S, x0 + bw - 11 * S, H - 22 * S
                cv.create_rectangle(bx0, by, bx1, by + 3 * S, fill="#000000", outline="")
                r_, g_, b_ = colorsys.hsv_to_rgb(frac / 3, 1, 1)
                cv.create_rectangle(bx0, by, bx0 + (bx1 - bx0) * frac, by + 2 * S, outline="",
                                    fill="#%02x%02x%02x" % (int(r_ * 255), int(g_ * 255), int(b_ * 255)))
            if on:
                cv.create_text(x0 + (bw - 6 * S) / 2, H - 6 * S, font=FONTS["r"], fill=MUTED,
                               text="다 씀" if i in dep else ("사용 중" if i == cur else "대기"))
        for key, cv in self.rslot_cvs.items():       # 모루 수리: 낚싯대 칸 / 실 칸
            cv.delete("all")
            W, H = int(cv["width"]), int(cv["height"])
            bw = W / 9
            for k in range(1, 10):
                x0 = (k - 1) * bw
                if k == self.cfg[key]:
                    bevel(cv, x0 + S, 0, x0 + bw - S, H, "#3f9a46")
                    shadow_text(cv, x0 + bw / 2, H / 2, str(k), FONTS["b"])
                else:
                    slot(cv, x0 + S, 0, x0 + bw - S, H, fill="#8b8b8b")
                    cv.create_text(x0 + bw / 2, H / 2, text=str(k), font=FONTS["r"], fill="#e8e8e8")
        c = self.cfg
        if not getattr(self, "turn_stage", 0):
            parts = []
            if c.get("repair_turn"):
                parts.append(f"방향: 기록됨 ({c['repair_turn'][0]}, {c['repair_turn'][1]})")
            elif c.get("repair_yaw") is not None:
                parts.append(f"방향: 각도 {c['repair_yaw']:g}° / {c.get('repair_pitch', 0):g}°")
            else:
                parts.append("방향: 아직 없음")
            parts.append("수리 창: " + ("지정됨" if c.get("repair_points") else "아직 없음"))
            parts.append("골드 영역: " + ("지정됨" if c.get("gold_roi") else "없음 (확인 안 함)"))
            ready = (c.get("repair_turn") or c.get("repair_yaw") is not None) and c.get("repair_points")
            self.repair_lbl.config(text="  ·  ".join(parts), fg=OK if ready else MUTED)

        cv = self.eslot_cv                           # 정밀 내구도 칸 고르기: [자동] 1 ~ 9
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        bw = W / 10
        sel = 0 if self.cfg["rod_swap"] else self.cfg.get("exact_slot", 0)
        for k in range(10):
            x0 = k * bw
            if k == sel:
                bevel(cv, x0 + S, 0, x0 + bw - S, H, "#3f9a46")
                shadow_text(cv, x0 + bw / 2, H / 2, "자동" if k == 0 else str(k), FONTS["b"])
            else:
                slot(cv, x0 + S, 0, x0 + bw - S, H, fill="#8b8b8b")
                cv.create_text(x0 + bw / 2, H / 2, text="자동" if k == 0 else str(k), font=FONTS["r"],
                               fill="#e8e8e8")
        self.swap_lbl.config(text=f"고른 칸: {', '.join(map(str, self.cfg['rod_slots'])) or '없음'}"
                                  + (f"  ·  지금 {cur}번 칸" if cur else ""))
        # 인벤 36칸
        cv = self.inv_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        inv_map = m.inv_map if m else None
        cs = min((W - 8 * S) / 9, (H - 10 * S) / 4)
        ox = (W - cs * 9) / 2
        for k in range(36):
            r, col = divmod(k, 9)
            y = r * cs + (8 * S if r == 3 else 0)                 # 핫바는 살짝 띄움
            x = ox + col * cs
            full = inv_map is not None and not inv_map[k]
            round_rect(cv, x + 2 * S, y + 2 * S, x + cs - 2 * S, y + cs - 2 * S, 5 * S,
                       fill=MUTED if full else PANEL, outline="" if full else LINE, width=S)
        if m and m.inv_empty is not None:
            self.inv_lbl.config(text=m.inv_note,
                                fg=BAD if m.inv_empty <= self.cfg["inv_min_empty"] else TXT)

    # ---------- 기록 페이지 ----------
    def build_log_page(self):
        pg = self.pages["log"]
        W = PANEL_W - 30 * S
        p = Panel(pg, "날짜별 기록", self.icons["book"])
        p.pack()
        self.tiles_cv = tk.Canvas(p.content, width=W, height=92 * S, bg=PANEL, highlightthickness=0)
        self.tiles_cv.pack()
        p = Panel(pg, "최근 14일 낚은 수", self.icons["fish"])
        p.pack(pady=(8 * S, 0))
        self.days_cv = tk.Canvas(p.content, width=W, height=170 * S, bg=PANEL, highlightthickness=0)
        self.days_cv.pack()
        self.days_cv.bind("<Motion>", lambda e: self.draw_log_page(hover=e.x))
        self.days_cv.bind("<Leave>", lambda e: self.draw_log_page())
        p = Panel(pg, "물고기 색 (전체 기간)", self.icons["emerald"])
        p.pack(pady=(8 * S, 0))
        self.colors_cv = tk.Canvas(p.content, width=W, height=30 * S, bg=PANEL, highlightthickness=0)
        self.colors_cv.pack()
        self.draw_log_page()

    def draw_log_page(self, hover=None):
        import datetime as dt
        hist = self.macro.history if getattr(self, "macro", None) else load_history()
        today = dt.date.today()
        days = [(today - dt.timedelta(days=13 - i)) for i in range(14)]
        get = lambda d: hist.get(d.isoformat(), {})

        def agg(keys):
            out = {"caught": 0, "casts": 0, "seconds": 0}
            for k in keys:
                for f in out:
                    out[f] += hist.get(k, {}).get(f, 0)
            return out

        def fmt_t(sec):
            m = int(sec // 60)
            return f"{m // 60}시간 {m % 60}분" if m >= 60 else f"{m}분"

        tiles = [("오늘", agg([today.isoformat()])),
                 ("어제", agg([(today - dt.timedelta(days=1)).isoformat()])),
                 ("최근 7일", agg([d.isoformat() for d in days[-7:]])),
                 ("전체", agg(hist.keys()))]
        cv = self.tiles_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        gap = 6 * S
        tw = (W - 3 * gap) / 4
        for i, (name, a) in enumerate(tiles):
            x0 = i * (tw + gap)
            round_rect(cv, x0, 0, x0 + tw, H, 12 * S, fill=SOFT, outline="")
            cv.create_text(x0 + tw / 2, 15 * S, text=name, font=FONTS["r"], fill=MUTED)
            cv.create_text(x0 + tw / 2, 38 * S, text=f"{a['caught']}마리", font=FONTS["m"],
                           fill=ACCENT if i == 0 else TXT)
            ph = a["caught"] / (a["seconds"] / 3600) if a["seconds"] >= 300 else None
            cv.create_text(x0 + tw / 2, 60 * S, font=FONTS["r"], fill=MUTED, text=fmt_t(a["seconds"]))
            if ph:
                cv.create_text(x0 + tw / 2, 77 * S, font=FONTS["r"], fill=MUTED, text=f"시간당 {ph:.0f}마리")

        # 14일 막대
        cv = self.days_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        top_pad, bot = 26 * S, 22 * S
        vals = [get(d).get("caught", 0) for d in days]
        vmax = max(vals) or 1
        bw = W / 14
        base = H - bot
        cv.create_line(0, base, W, base, fill=LINE, width=S)
        hi = None if hover is None else min(13, max(0, int(hover // bw)))
        for i, (d, v) in enumerate(zip(days, vals)):
            x0, x1 = i * bw + 4 * S, (i + 1) * bw - 4 * S
            h = (base - top_pad) * v / vmax
            if v:
                col = ACCENT if (hi is None or hi == i) else LINE
                round_rect(cv, x0, base - max(h, 4 * S), x1, base + 4 * S, 4 * S, fill=col, outline="")
                cv.create_rectangle(x0, base, x1, base + 4 * S, fill=PANEL, outline="")
            if i % 2 == 1 or i == 13:
                cv.create_text((x0 + x1) / 2, base + 11 * S, font=FONTS["r"], fill=MUTED,
                               text="오늘" if i == 13 else f"{d.month}/{d.day}")
        if hi is not None:
            e = get(days[hi])
            casts = e.get("casts", 0)
            rate = f" · 성공 {e.get('caught', 0) / casts:.0%}" if casts else ""
            text = f"{days[hi].month}/{days[hi].day}  {e.get('caught', 0)}마리 · {fmt_t(e.get('seconds', 0))}{rate}"
            cv.create_text(W / 2, 10 * S, text=text, font=FONTS["b"], fill=TXT)
        else:
            i = int(np.argmax(vals))
            if vals[i]:
                cv.create_text(W / 2, 10 * S, text=f"가장 많이: {days[i].month}/{days[i].day} {vals[i]}마리  "
                                                  "(막대에 마우스를 올리면 자세히)", font=FONTS["r"], fill=MUTED)
            else:
                cv.create_text(W / 2, (base + top_pad) / 2, text="아직 기록이 없어. 낚시하면 여기에 쌓여",
                               font=FONTS["r"], fill=MUTED)

        # 색 분포
        colors = {}
        for e in hist.values():
            for k, v in e.get("colors", {}).items():
                colors[k] = colors.get(k, 0) + v
        items = sorted(colors.items(), key=lambda kv: -kv[1])
        cv = self.colors_cv
        rh = 24 * S
        cv.configure(height=max(30 * S, rh * len(items)))
        cv.delete("all")
        W = int(cv["width"])
        if not items:
            cv.create_text(W / 2, 15 * S, text="색은 미니게임 시작할 때 물고기 색으로 기록돼", font=FONTS["r"], fill=MUTED)
        total = sum(colors.values()) or 1
        vmax = items[0][1] if items else 1
        for i, (name, v) in enumerate(items):
            y = i * rh + rh / 2
            cv.create_oval(2 * S, y - 6 * S, 14 * S, y + 6 * S, fill=FISH_HEX.get(name, MUTED), outline="")
            cv.create_text(22 * S, y, text=name, anchor="w", font=FONTS["b"], fill=TXT)
            x0, x1 = 64 * S, W - 118 * S
            round_rect(cv, x0, y - 5 * S, x1, y + 5 * S, 5 * S, fill=SOFT, outline="")
            round_rect(cv, x0, y - 5 * S, x0 + max(10 * S, (x1 - x0) * v / vmax), y + 5 * S, 5 * S,
                       fill=FISH_HEX.get(name, MUTED), outline="")
            cv.create_text(W - 2 * S, y, text=f"{v}마리 · {v / total:.0%}", anchor="e", font=FONTS["r"], fill=TXT)

    STEPS = [("던지기", ("던지는",)), ("입질 대기", ("자리잡는", "입질 기다리는")),
             ("미니게임", ("미니게임",)), ("다시 던지기", ("다시 던지기",))]

    def draw_pipeline(self, m):
        cv = self.pipe_cv
        cv.delete("all")
        W = int(cv["width"])
        cur = next((i for i, (_, keys) in enumerate(self.STEPS) if any(k in m.state for k in keys)), None)
        if not m.running:
            cur = None
        # 마크 경험치 바처럼: 위에 단계 글자, 아래 초록 막대 (지금 단계까지 참), 오른쪽에 낚은 수 = 레벨
        n = len(self.STEPS)
        x = 0
        for i, (name, _) in enumerate(self.STEPS):
            on = i == cur
            t = cv.create_text(x, 9 * S, text=name, anchor="w", font=FONTS["b" if on else "r"],
                               fill=TXT if on else MUTED)
            x = cv.bbox(t)[2] + 4 * S
            if i < n - 1:
                t = cv.create_text(x, 9 * S, text="›", anchor="w", font=FONTS["r"], fill=MUTED)
                x = cv.bbox(t)[2] + 4 * S
        shadow_text(cv, W - 2 * S, 9 * S, f"Lv. {m.run_caught}", FONTS["b"], "#80ff20", anchor="e")
        y0, y1 = 22 * S, 32 * S
        cv.create_rectangle(0, y0, W, y1, fill="#000000", outline="")
        if cur is not None:
            fx = (W - 2 * S) * (cur + 1) / n
            cv.create_rectangle(S, y0 + S, S + fx, y1 - S, fill="#80ff20", outline="")
            cv.create_rectangle(S, y1 - 4 * S, S + fx, y1 - S, fill="#3f9f00", outline="")
        for i in range(1, 18):                       # 경험치 바 눈금
            gx = W * i / 18
            cv.create_line(gx, y0 + S, gx, y1 - S, fill="#000000", width=max(1, S))

    def draw_dashboard(self, m):
        s = m.stats
        now = time.time()
        if m.running and s["started"]:
            self.elapsed = now - s["started"]
        mins = self.elapsed / 60
        caught = m.run_caught
        per_hour = caught / (self.elapsed / 3600) if self.elapsed > 60 else 0
        rate = s["caught"] / s["casts"] if s["casts"] else 0
        tiles = [("이번 낚시", f"{caught}마리"), ("시간당", f"{per_hour:.0f}마리"),
                 ("성공률", f"{rate:.0%}"), ("진행", f"{int(mins // 60)}:{int(mins % 60):02d}")]
        cv = self.dash_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        gap = 6 * S
        tw = (W - gap * 3) / 4
        for i, (name, val) in enumerate(tiles):
            x0 = i * (tw + gap)
            slot(cv, x0, 0, x0 + tw, H, fill="#8b8b8b")
            cv.create_text(x0 + 8 * S, 15 * S, text=name, anchor="w", font=FONTS["r"], fill="#e8e8e8")
            shadow_text(cv, x0 + tw - 8 * S, 42 * S, val, FONTS["m"], "#80ff20" if i == 0 else "#ffffff",
                        anchor="e")
        # 물고기 색 칩
        key = tuple(sorted(s["colors"].items())) + (self.cfg.get("total_caught", 0), id(self.chips))
        if key != getattr(self, "_chip_key", None):
            self._chip_key = key
            for w in self.chips.winfo_children():
                w.destroy()
            # 이번에 낚은 물고기 = 아이템 칸 (색별 물고기 그림 + 개수)
            n = 7
            W = PANEL_W - 30 * S
            cs = W / n
            cv = tk.Canvas(self.chips, width=W, height=int(cs) + 18 * S, bg=PANEL, highlightthickness=0)
            cv.pack()
            items = sorted(s["colors"].items(), key=lambda kv: -kv[1])
            for k in range(n):
                x0 = k * cs
                slot(cv, x0, 0, x0 + cs - S, cs - S, fill="#8b8b8b")
                if k < len(items):
                    name, cnt = items[k]
                    col = FISH_HEX.get(name, "#9e9e9e")
                    cx, cy = x0 + cs / 2, cs / 2 - 2 * S
                    cv.create_rectangle(cx - 11 * S, cy - 5 * S, cx + 6 * S, cy + 5 * S, fill=col, outline="#202020",
                                        width=max(1, S))
                    cv.create_polygon(cx + 6 * S, cy, cx + 12 * S, cy - 6 * S, cx + 12 * S, cy + 6 * S, fill=col,
                                      outline="#202020", width=max(1, S))
                    cv.create_rectangle(cx - 8 * S, cy - 2 * S, cx - 6 * S, cy, fill="#202020", outline="")
                    shadow_text(cv, x0 + cs - 4 * S, cs - 7 * S, str(cnt), FONTS["b"], anchor="e")
                    cv.create_text(x0 + cs / 2, cs + 8 * S, text=name, font=FONTS["r"], fill=MUTED)
            cv.create_text(W, cs + 8 * S, text=f"총 {self.cfg.get('total_caught', 0)}마리", anchor="e",
                           font=FONTS["b"], fill=TXT)
        # 최근 1시간, 5분 단위 막대
        cv = self.spark_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        bins = [0] * 12
        for t in s["catch_times"]:
            k = int((now - t) // 300)
            if 0 <= k < 12:
                bins[11 - k] += 1
        top = max(bins) or 1
        bw = W / 12
        for i, v in enumerate(bins):
            h = (H - 14 * S) * v / top
            round_rect(cv, i * bw + 2 * S, H - 14 * S - max(h, 2 * S), (i + 1) * bw - 2 * S, H - 14 * S,
                       3 * S, fill=ACCENT if v else LINE, outline="")
        cv.create_text(2 * S, H - 6 * S, text="1시간 전", anchor="w", font=FONTS["r"], fill=MUTED)
        cv.create_text(W - 2 * S, H - 6 * S, text="지금", anchor="e", font=FONTS["r"], fill=MUTED)

    def draw_live(self, s):
        """찌 모드: 찌 확대 화면 + 가라앉음/물보라 그래프 (1 넘으면 입질)."""
        show = self.cfg["bite_mode"] in ("bobber", "both")
        if show and not self.live.winfo_ismapped():
            self.live.pack(fill="x", pady=(6 * S, 0))
        elif not show and self.live.winfo_ismapped():
            self.live.pack_forget()
        if not show:
            return
        img = s.get("bobber_view")
        if img is not None and img.size:
            h, w = img.shape[:2]
            k = min(180 * S / w, 90 * S / h)
            self.live_img.config(width=180 * S, height=90 * S)
            pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).resize(
                (max(1, int(w * k)), max(1, int(h * k))), Image.NEAREST)
            self.live_photo = ImageTk.PhotoImage(pil)
            self.live_img.config(image=self.live_photo)
        cv = self.trace_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        slot(cv, 0, 0, W, H, fill=BAR_BG)
        y1 = H * 0.75 - H * 0.55
        cv.create_line(4 * S, y1, W - 4 * S, y1, fill=ACCENT, dash=(4, 3))
        cv.create_text(W - 6 * S, y1 + 8 * S, text="입질 기준", anchor="e", font=FONTS["r"], fill=ACCENT)
        tr = s.get("trace") or []
        if len(tr) >= 2:
            for idx, color in ((0, "#1e88e5"), (1, OK)):
                pts = []
                for i, t in enumerate(tr[-100:]):
                    v = max(-0.3, min(1.3, t[idx]))
                    pts += [4 * S + (W - 8 * S) * i / 99, H * 0.75 - H * 0.55 * v]
                cv.create_line(*pts, fill=color, width=2 * S, smooth=True)
        cv.create_text(6 * S, 8 * S, text="━ 가라앉음", anchor="w", font=FONTS["r"], fill="#1e88e5")
        cv.create_text(84 * S, 8 * S, text="━ 물보라", anchor="w", font=FONTS["r"], fill=OK)

    def draw_bar(self, s):
        cv = self.bar_cv
        cv.delete("all")
        W, H = int(cv["width"]), int(cv["height"])
        slot(cv, 0, 0, W, H, fill=BAR_BG)
        roi = self.cfg["bar_roi"]
        if not roi:
            cv.create_text(W // 2, H // 2, text="미니게임이 뜨면 바를 자동으로 찾아요", font=FONTS["r"], fill=MUTED)
            return
        if not s["active"]:
            cv.create_text(W // 2, H // 2, text="미니게임 기다리는 중 ...", font=FONTS["r"], fill=MUTED)
            return
        scale = (W - 8 * S) / roi[2]
        if s["zone"] is not None and self.macro:
            zw = max(self.macro.zone_w, 4) * scale
            zx = 4 * S + s["zone"] * scale
            cv.create_rectangle(zx - zw / 2, 3 * S, zx + zw / 2, H - 3 * S, outline=ACCENT, width=2 * S)
        if s["fish"] is not None:
            cv.create_image(4 * S + s["fish"] * scale, H // 2, image=self.icons["fish"])

    # ---------- 설정 ----------
    def refresh_status(self):
        c = self.cfg
        sub_mode = c["bite_mode"] == "subtitle"
        done = {"subtitle": c["subtitle_roi"] and SUBTITLE_PATH.exists(), "bobber": c["bobber_roi"],
                "rod": c["durability_roi"], "gauge": c["gauge_roi"]}
        need = {"subtitle": "필수" if sub_mode else "안 씀", "bobber": "안 씀" if sub_mode else "필수",
                "rod": "자동", "gauge": "선택"}
        for k, ok in done.items():
            if not ok and k == "rod":
                self.status_lbl[k].config(text="● 자동 (선택한 칸)", fg=OK)
                continue
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
        scenes["repair"] = "모루 수리 창을 연 상태 (낚싯대·실 넣기 전, 빈 창)"
        scenes["gold"] = "골드 숫자가 보이는 게임 화면"
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
        if item in ("repair", "gold"):
            self.repair_lbl.config(text=f"▶ 게임에서 [{scene}] 띄우고 F7", fg=ACCENT)

    def do_set(self, item, img):
        c = self.cfg
        if item == "gold":
            rect = ask_roi(self.root, img, "골드 숫자만 (예: 30,979) 감싸기")
            if not rect:
                return
            x, y, w, h = rect
            val = read_number(img[y:y + h, x:x + w])
            c["gold_roi"] = rect
            save_config(c)
            self.log(f"골드 영역 지정: 지금 {val:,} 골드로 읽힘" if val is not None
                     else "골드 숫자를 못 읽었어. 숫자만 딱 맞게 다시 감싸줘", "good" if val is not None else "warn")
            self.draw_rod_page()
            return
        if item == "repair":
            names = [("in1", "낚싯대 넣는 칸 (왼쪽 첫 칸)"), ("in2", "실 넣는 칸 (가운데 칸)"),
                     ("out", "결과 칸 (화살표 오른쪽)"), ("ok", "✓ 수리 버튼"),
                     ("hot1", "아래 핫바 1번 칸"), ("hot9", "아래 핫바 9번 칸")]
            pts = {}
            for i, (k, name) in enumerate(names):
                pt = ask(self.root, img, f"[수리 창 {i + 1}/{len(names)}] {name} 가운데를 클릭", mode="point")
                if not pt:
                    return
                pts[k] = [int(pt[0]), int(pt[1])]
            if abs(pts["hot9"][0] - pts["hot1"][0]) < 40:
                messagebox.showwarning("수리 창", "핫바 1번과 9번 칸을 다시 확인해줘 (너무 가까워)")
                return
            pitch = abs(pts["hot9"][0] - pts["hot1"][0]) / 8
            pts["hot"] = hotbar_points(img, pts["hot1"], pts["hot9"])        # 9칸 다 정확한 가운데로
            for k in ("in1", "in2", "out"):
                pts[k] = snap_slot(img, pts[k], pitch)
            pts["screen"] = [img.shape[1], img.shape[0]]
            half = max(6, int(pitch * 0.4))                                  # 칸 크기의 약 0.8
            save_repair_refs(img, pts, half)
            c["repair_points"] = pts
            save_config(c)
            self.log("수리 창 위치 지정 완료", "good")
            self.draw_rod_page()
            return
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
            c["subtitle_scale"] = detect_gui_scale(img)     # 이 배율 기준 (배율이 바뀌면 자동으로 맞춤)
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
            c["bar_scale"] = detect_gui_scale(img)
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

    def save_background(self):
        self.cfg["background"] = self.bg_var.get()
        save_config(self.cfg)
        if self.cfg["background"]:
            self.log("백그라운드 모드 켬: 마크에서 F3+P 꼭 누르고, 창 최소화는 하지 마", "warn")
        else:
            self.log("백그라운드 모드 끔")

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

    def save_goals(self):
        try:
            self.cfg["goal_count"] = max(0, int(float(self.goal_n_var.get() or 0)))
            self.cfg["goal_minutes"] = max(0, int(float(self.goal_m_var.get() or 0)))
        except ValueError:
            return
        save_config(self.cfg)

    def save_hook(self):
        self.cfg["discord_webhook"] = self.hook_var.get().strip()
        self.cfg["notify_each_catch"] = self.each_var.get()
        save_config(self.cfg)

    def test_hook(self):
        from fishing_macro import notify
        self.save_hook()
        if not self.cfg["discord_webhook"].startswith("https://"):
            messagebox.showwarning("디스코드", "웹후크 주소(https://discord.com/api/webhooks/...)를 넣어줘")
            return
        notify(self.cfg["discord_webhook"], "낚시 매크로 알림 테스트!")
        self.log("디스코드 테스트 보냄 (채널에 메시지가 왔는지 확인)", "good")

    def toggle_mini(self):
        """작은 창: 시작 버튼 + 낚은 수만."""
        if getattr(self, "mini", None):
            self.mini.destroy()
            self.mini = None
            self.header.pack()
            self.main_frame.pack(fill="both", expand=True)
            return
        self.header.pack_forget()
        self.main_frame.pack_forget()
        self.mini = tk.Frame(self.root, bg=SKY, padx=10 * S, pady=10 * S)
        self.mini.pack()
        p = Panel(self.mini, "마크 낚시", self.icons["fish"])
        p.pack()
        self.mini_btn = PixelButton(p.content, "▶ 시작 (F8)", self.toggle, "green", width=200 * S, height=36 * S,
                                    font=FONTS["m"])
        self.mini_btn.pack(side="left")
        self.mini_lbl = label(p.content, "0마리", "m", fg=ACCENT)
        self.mini_lbl.pack(side="left", padx=(10 * S, 0))
        PixelButton(self.mini, "크게", self.toggle_mini, width=60 * S, height=24 * S).pack(pady=(6 * S, 0))

    def save_adv(self):
        try:
            for k, var in self.adv_vars.items():
                v = float(var.get())
                self.cfg[k] = int(v) if isinstance(self.cfg[k], int) and v.is_integer() else v
        except ValueError:
            messagebox.showerror("오류", "숫자만 입력해줘")
            return
        self.cfg["reel_click_after_game"] = self.reel_var.get()
        self.cfg["log_file"] = self.logf_var.get()
        self.save_hook()
        self.log("세부 설정 저장 완료!", "good")

    # ---------- 실행 ----------
    def toggle(self):
        """시작/정지. 키를 꾹 누르면 반복 입력돼서 켜졌다 꺼지는 걸 막음 (0.5초 안 재입력 무시)."""
        now = time.perf_counter()
        if now - getattr(self, "_last_toggle", 0) < 0.5:
            return
        self._last_toggle = now
        if self.macro:
            self.macro.toggle()

    def close(self):
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
        self.root.after(200, self.root.destroy)

    def run(self):
        self.root.mainloop()
        if getattr(sys, "frozen", False):
            os._exit(0)                  # 캡처 스레드 등이 남아 프로세스가 안 꺼지는 것 방지


if __name__ == "__main__":
    App().run()
