"""마인크래프트 낚시 매크로 - UI 버전.

실행: python app.py   (또는 app.py 더블클릭)
"""
import ctypes
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import numpy as np
from PIL import Image, ImageTk

try:  # 고해상도 모니터에서 좌표/선명도 맞추기
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import keyboard

from common import Screen, color_mask, durability_hue, load_config, save_config
from fishing_macro import Macro

FONT = ("맑은 고딕", 10)
FONT_B = ("맑은 고딕", 10, "bold")
FONT_BIG = ("맑은 고딕", 14, "bold")


def load_image(path):
    """한글 경로 지원. BGR numpy 반환."""
    return np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()


# ---------------------------------------------------------------- 영역 선택 창
class PickDialog(tk.Toplevel):
    """mode: rect = 드래그로 사각형 / point = 클릭으로 한 점 / view = 보기만."""

    def __init__(self, parent, img, guide, mode="rect", max_size=(1280, 720), ok_text="확인"):
        super().__init__(parent)
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

        tk.Label(self, text=guide, font=FONT_B, fg="#c0392b", justify="left").pack(anchor="w", padx=10, pady=(8, 4))
        self.cv = tk.Canvas(self, width=vw, height=vh, highlightthickness=1, highlightbackground="#888",
                            cursor="crosshair" if mode != "view" else "arrow")
        self.cv.pack(padx=10)
        self.cv.create_image(0, 0, image=self.photo, anchor="nw")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        self.ok_btn = ttk.Button(bar, text=f"{ok_text} (Enter)", command=self.ok)
        self.ok_btn.pack(side="right")
        ttk.Button(bar, text="취소 (Esc)", command=self.destroy).pack(side="right", padx=6)
        if mode == "view":
            ttk.Button(bar, text="다시 하기", command=self.retry).pack(side="right")
        else:
            self.ok_btn.state(["disabled"])

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
            if self.shape:
                for sh in self.shape:
                    self.cv.delete(sh)
            self.shape = (self.cv.create_line(e.x - 10, e.y, e.x + 10, e.y, fill="#00ff00", width=2),
                          self.cv.create_line(e.x, e.y - 10, e.x, e.y + 10, fill="#00ff00", width=2))
            self.sel = (e.x, e.y)
            self.ok_btn.state(["!disabled"])

    def on_drag(self, e):
        if self.mode != "rect" or not self.start:
            return
        if self.shape:
            self.cv.delete(self.shape)
        self.shape = self.cv.create_rectangle(*self.start, e.x, e.y, outline="#00ff00", width=2)

    def on_up(self, e):
        if self.mode != "rect" or not self.start:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            self.sel = (x0, y0, x1, y1)
            self.ok_btn.state(["!disabled"])

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
        ("bobber", "찌 (필수)", "찌가 물 위에 떠 있을 때"),
        ("rod", "낚싯대 내구도 (권장)", "핫바에 낚싯대 내구도 줄이 보일 때"),
        ("gauge", "원형 게이지 (선택)", "게이지가 '가득 찬' 순간 (스크린샷 파일 추천)"),
    ]

    SETTINGS = [
        ("bite_drop_ratio", "입질 판정: 찌가 이 비율 아래로 줄면", 0.1, 0.95, 0.05),
        ("bite_dip_px", "입질 판정: 찌가 이만큼(px) 내려가면", 1, 30, 1),
        ("tolerance", "색 허용 오차", 5, 80, 1),
        ("deadzone_px", "바 따라가기 허용 오차(px)", 0, 30, 1),
        ("lead_sec", "바 움직임 예측(초)", 0.0, 0.3, 0.01),
        ("cast_settle_sec", "던진 뒤 대기(초)", 0.5, 5, 0.1),
        ("bite_timeout_sec", "입질 최대 대기(초)", 10, 120, 5),
        ("recast_delay_sec", "다시 던지기 전 대기(초)", 0.2, 5, 0.1),
        ("start_delay_sec", "시작 버튼 후 대기(초)", 0, 10, 1),
    ]

    def __init__(self):
        self.cfg = load_config()
        self.q = queue.Queue()
        self.waiting_item = None
        self.f7 = threading.Event()

        self.root = tk.Tk()
        self.root.title("마크 낚시 매크로")
        self.root.option_add("*Font", FONT)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.build()

        self.macro = None
        threading.Thread(target=self.worker, daemon=True).start()
        keyboard.add_hotkey("f8", lambda: self.macro and self.macro.toggle())
        keyboard.add_hotkey("f7", self.f7.set)

        self.refresh_status()
        self.root.after(100, self.tick)
        self.log("준비됨. ① 설정 → ② 시작 순서로 진행해.")

    # ---------- 레이아웃 ----------
    def build(self):
        pad = {"padx": 10, "pady": 5}

        # ① 설정
        f1 = ttk.LabelFrame(self.root, text=" ① 화면 위치 설정 ")
        f1.pack(fill="x", **pad)
        self.status_lbl = {}
        for r, (key, name, _) in enumerate(self.ITEMS):
            ttk.Label(f1, text=name, width=18).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            lbl = tk.Label(f1, text="", width=14, anchor="w")
            lbl.grid(row=r, column=1, sticky="w")
            self.status_lbl[key] = lbl
            ttk.Button(f1, text="지정하기", command=lambda k=key: self.begin_set(k)).grid(row=r, column=2, padx=6)

        r = len(self.ITEMS)
        ttk.Label(f1, text="미니게임 바 (자동)", width=18).grid(row=r, column=0, sticky="w", padx=6, pady=3)
        self.status_lbl["bar"] = tk.Label(f1, text="", width=14, anchor="w")
        self.status_lbl["bar"].grid(row=r, column=1, sticky="w")
        ttk.Button(f1, text="다시 찾기", command=self.reset_bar).grid(row=r, column=2, padx=6)

        mf = ttk.Frame(f1)
        mf.grid(row=r + 1, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 4))
        ttk.Label(mf, text="화면 가져오기:").pack(side="left")
        self.capture_mode = tk.StringVar(value="live")
        ttk.Radiobutton(mf, text="게임에서 F7", variable=self.capture_mode, value="live").pack(side="left", padx=4)
        ttk.Radiobutton(mf, text="스크린샷 파일", variable=self.capture_mode, value="file").pack(side="left")

        self.guide = tk.Label(f1, text="", fg="#c0392b", font=FONT_B, wraplength=380, justify="left")
        self.guide.grid(row=r + 2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))

        # ② 실행
        f2 = ttk.LabelFrame(self.root, text=" ② 실행 ")
        f2.pack(fill="x", **pad)
        self.run_btn = tk.Button(f2, text="▶ 시작 (F8)", font=FONT_BIG, bg="#27ae60", fg="white",
                                 activebackground="#2ecc71", relief="flat", command=self.toggle)
        self.run_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.state_lbl = tk.Label(f2, text="정지됨", font=FONT_B)
        self.state_lbl.pack()
        ttk.Label(f2, text="시작 누르고 바로 게임 창 클릭. 게임 중엔 F8로 시작/정지", foreground="#666").pack(pady=(0, 6))

        # 실시간 상태
        f3 = ttk.LabelFrame(self.root, text=" 실시간 상태 ")
        f3.pack(fill="x", **pad)
        self.vals = {}
        for i, (k, name) in enumerate([("bobber", "찌 픽셀"), ("caught", "낚은 횟수"),
                                       ("gauge", "게이지"), ("hue", "내구도 색")]):
            ttk.Label(f3, text=name).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=6)
            v = ttk.Label(f3, text="-", font=FONT_B, width=10)
            v.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w")
            self.vals[k] = v
        self.bar_cv = tk.Canvas(f3, width=380, height=34, bg="#1b2631", highlightthickness=0)
        self.bar_cv.grid(row=2, column=0, columnspan=4, padx=6, pady=6)

        # 세부 설정
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.root, text="세부 설정 보기", variable=self.show_adv,
                        command=self.toggle_adv).pack(anchor="w", padx=12)
        self.adv = ttk.Frame(self.root)
        self.adv_vars = {}
        for i, (k, name, lo, hi, step) in enumerate(self.SETTINGS):
            ttk.Label(self.adv, text=name).grid(row=i, column=0, sticky="w", padx=6, pady=1)
            var = tk.StringVar(value=str(self.cfg[k]))
            ttk.Spinbox(self.adv, from_=lo, to=hi, increment=step, textvariable=var, width=8).grid(row=i, column=1)
            self.adv_vars[k] = var
        self.reel_var = tk.BooleanVar(value=self.cfg["reel_click_after_game"])
        ttk.Checkbutton(self.adv, text="미니게임 끝나고 우클릭 한 번 더", variable=self.reel_var).grid(
            row=len(self.SETTINGS), column=0, columnspan=2, sticky="w", padx=6)
        ttk.Button(self.adv, text="설정 저장", command=self.save_adv).grid(
            row=len(self.SETTINGS) + 1, column=0, columnspan=2, pady=4)

        # 로그
        self.log_frame = ttk.LabelFrame(self.root, text=" 로그 ")
        self.log_frame.pack(fill="both", **pad)
        self.log_box = ScrolledText(self.log_frame, height=8, width=52, font=("맑은 고딕", 9), state="disabled")
        self.log_box.pack(fill="both", padx=4, pady=4)
        of = ttk.Frame(self.log_frame)
        of.pack(fill="x")
        self.debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(of, text="자세한 로그", variable=self.debug_var,
                        command=lambda: self.macro and setattr(self.macro, "debug", self.debug_var.get())
                        ).pack(side="left", padx=4)
        self.top_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(of, text="항상 위", variable=self.top_var,
                        command=lambda: self.root.attributes("-topmost", self.top_var.get())).pack(side="left")
        self.root.attributes("-topmost", True)

    def toggle_adv(self):
        if self.show_adv.get():
            self.adv.pack(fill="x", padx=10, before=self.log_frame)
        else:
            self.adv.pack_forget()

    # ---------- 매크로 스레드 ----------
    def worker(self):
        self.macro = Macro(self.cfg, out=self.q.put, hotkeys=False)
        self.macro.run()

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def tick(self):
        while not self.q.empty():
            self.log(self.q.get())

        if self.f7.is_set():
            self.f7.clear()
            if self.waiting_item:
                item, self.waiting_item = self.waiting_item, None
                img = Screen(self.cfg["monitor"]).full()
                self.guide.config(text="")
                self.root.deiconify()
                self.root.lift()
                self.do_set(item, img)

        m = self.macro
        if m:
            s = m.stats
            self.vals["bobber"].config(text="-" if not self.cfg["bobber_roi"] else str(s["bobber_n"]))
            self.vals["caught"].config(text=str(s["caught"]))
            self.vals["gauge"].config(text="-" if s["gauge"] is None else f"{s['gauge']:.0%}")
            hue = s["hue"]
            if hue is None:
                self.vals["hue"].config(text="-", foreground="black")
            else:
                red = not (self.cfg["durability_red_hue"] < hue < 330)
                self.vals["hue"].config(text=f"{hue:.0f}° {'빨강!' if red else '정상'}",
                                        foreground="#c0392b" if red else "#27ae60")
            self.state_lbl.config(text=m.state)
            if m.running:
                self.run_btn.config(text="■ 정지 (F8)", bg="#c0392b", activebackground="#e74c3c")
            else:
                self.run_btn.config(text="▶ 시작 (F8)", bg="#27ae60", activebackground="#2ecc71")
            self.draw_bar(s)
            if self.cfg["bar_roi"] and self.status_lbl["bar"].cget("text") != "✔ 찾음":
                self.refresh_status()

        self.root.after(100, self.tick)

    def draw_bar(self, s):
        cv = self.bar_cv
        cv.delete("all")
        W, H = 380, 34
        roi = self.cfg["bar_roi"]
        if not roi:
            cv.create_text(W // 2, H // 2, text="미니게임이 뜨면 바를 자동으로 찾음", fill="#aab7b8")
            return
        cv.create_rectangle(6, 12, W - 6, 22, fill="#0b3c5d", outline="")
        scale = (W - 12) / roi[2]
        if s["zone"] is not None and self.macro:
            zw = max(self.macro.zone_w, 4) * scale
            zx = 6 + s["zone"] * scale
            cv.create_rectangle(zx - zw / 2, 8, zx + zw / 2, 26, outline="#aed6f1", width=2)
        if s["fish"] is not None:
            fx = 6 + s["fish"] * scale
            cv.create_oval(fx - 6, 11, fx + 6, 23, fill="#58d68d", outline="")
        if s["zone"] is None and s["fish"] is None:
            cv.create_text(W // 2, H // 2, text="미니게임 대기 중", fill="#aab7b8")

    # ---------- 설정 ----------
    def refresh_status(self):
        c = self.cfg
        done = {"bobber": bool(c["bobber_roi"]), "rod": bool(c["durability_roi"]),
                "gauge": bool(c["gauge_roi"])}
        for k, ok in done.items():
            self.status_lbl[k].config(text="✔ 완료" if ok else "✖ 미설정",
                                      fg="#27ae60" if ok else ("#c0392b" if k == "bobber" else "#7f8c8d"))
        self.status_lbl["bar"].config(text="✔ 찾음" if c["bar_roi"] else "… 자동 대기",
                                      fg="#27ae60" if c["bar_roi"] else "#7f8c8d")

    def begin_set(self, item):
        if self.macro and self.macro.running:
            messagebox.showinfo("안내", "매크로를 먼저 정지해줘")
            return
        scene = {k: s for k, _, s in self.ITEMS}[item]
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
        self.guide.config(text=f"▶ 게임에서 [{scene}] 장면을 띄우고 F7 누르기")
        self.log(f"F7 대기 중: {scene}")

    def do_set(self, item, img):
        c = self.cfg
        if item == "bobber":
            roi = ask_roi(self.root, img, "찌 영역 - 찌가 위아래로 움직이니 넉넉히", precise=False)
            if not roi:
                return
            x, y, w, h = roi
            crop = img[y:y + h, x:x + w]
            while True:
                pt = ask(self.root, crop, "[찌 색] 찌의 빨간 부분을 클릭", mode="point", max_size=(800, 500))
                if not pt:
                    return
                color = [int(v) for v in crop[pt[1], pt[0]]]
                mask = color_mask(crop, color, c["tolerance"])
                ok = ask(self.root, overlay(crop, mask),
                         f"초록 = 감지된 부분 ({int(mask.sum())}px)\n찌만 초록이면 확인, 배경까지 초록이면 다시 하기",
                         mode="view", max_size=(800, 500))
                if ok is None:
                    return
                if ok:
                    break
            c["bobber_roi"], c["bobber_color"] = roi, color
            self.log(f"찌 설정 완료: 영역 {roi}, 색 {color}")

        elif item == "rod":
            roi = ask_roi(self.root, img, "내구도 줄 - 핫바 낚싯대 칸 아래 색깔 줄만")
            if not roi:
                return
            x, y, w, h = roi
            hue = durability_hue(img[y:y + h, x:x + w])
            c["durability_roi"] = roi
            if hue is None:
                self.log("내구도 설정됨. 단, 지금은 색 줄을 못 찾음 (내구도 가득이면 정상, 아니면 다시 지정)")
            else:
                self.log(f"내구도 설정 완료: 현재 색 {hue:.0f}° (빨강 기준 {c['durability_red_hue']}° 이하)")

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
            self.log(f"게이지 설정 완료: 가득 찼을 때 {n}px")

        save_config(c)
        self.refresh_status()

    def reset_bar(self):
        self.cfg["bar_roi"] = None
        if self.macro:
            self.macro.zone_w, self.macro.prev_zone = 0, None
        save_config(self.cfg)
        self.refresh_status()
        self.log("바 위치 초기화. 다음 미니게임 때 다시 찾음")

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
        self.log("세부 설정 저장됨")

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
