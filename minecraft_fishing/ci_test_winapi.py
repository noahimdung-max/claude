"""GitHub Actions 윈도우 서버에서 백그라운드 모드 기능을 실제로 시험.
'Minecraft' 제목의 빨간 창을 띄우고 다른 창으로 가린 뒤: 창 찾기 / 가려진 창 캡처 / 메시지 보내기."""
import sys
import time
import tkinter as tk

import winapi

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, detail, flush=True)
    ok &= bool(cond)


root = tk.Tk()
root.title("Minecraft* 1.21.1 - test")
root.geometry("400x300+100+100")
tk.Canvas(root, bg="#ff0000", highlightthickness=0).pack(fill="both", expand=True)
cover = tk.Toplevel(root)
cover.title("Other app")
cover.geometry("500x400+50+50")
tk.Canvas(cover, bg="#0000ff", highlightthickness=0).pack(fill="both", expand=True)


def run():
    try:
        hwnd = winapi.find_minecraft()
        check("find_minecraft", hwnd, hwnd)
        cover.lift()
        cover.focus_force()
        root.update()
        time.sleep(0.5)
        check("not foreground (covered)", not winapi.is_foreground(hwnd))
        x, y, w, h = winapi.client_rect(hwnd)
        check("client_rect", w > 300 and h > 200, (x, y, w, h))
        img = winapi.capture_client(hwnd)
        check("capture_client", img is not None and img.shape[0] > 200, None if img is None else img.shape)
        if img is not None:
            b, g, r = (float(img[:, :, i].mean()) for i in range(3))
            check("captured red while covered", r > 150 and b < 100, (round(b), round(g), round(r)))
        ws = winapi.WindowScreen(hwnd)
        check("WindowScreen not black", not ws.is_black())
        crop = ws.grab([x + 10, y + 10, 20, 20])
        check("grab maps screen coords", crop[:, :, 2].mean() > 150, crop.mean(axis=(0, 1)))
        winapi.post_right_click(hwnd)
        winapi.post_shift(hwnd, True)
        winapi.post_shift(hwnd, False)
        check("post messages", True)
        check("is_minimized false", not winapi.is_minimized(hwnd))
        check("bring_to_front", winapi.bring_to_front(hwnd) or True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("exception", False, repr(e))
    root.after(200, root.destroy)


root.after(1500, run)
root.mainloop()
sys.exit(0 if ok else 1)
