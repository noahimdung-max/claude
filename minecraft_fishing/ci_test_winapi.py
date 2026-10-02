"""GitHub Actions 윈도우 서버에서 백그라운드 모드 기능을 실제로 시험.
실제처럼 '다른 프로세스'에 Minecraft 제목의 빨간 창 + 그 위를 가리는 파란 창을 띄우고:
창 찾기 / 가려진 창 캡처 / 메시지 보내기."""
import faulthandler
import subprocess
import sys
import time

faulthandler.dump_traceback_later(90, exit=True)   # 멈추면 어디서 멈췄는지 찍고 종료

WIN = r'''
import tkinter as tk
root = tk.Tk(); root.title("Minecraft* 1.21.1 - test"); root.geometry("1280x720+100+100")
tk.Canvas(root, bg="#ff0000", highlightthickness=0).pack(fill="both", expand=True)
cover = tk.Toplevel(root); cover.title("Other app"); cover.geometry("1400x850+50+50")
tk.Canvas(cover, bg="#0000ff", highlightthickness=0).pack(fill="both", expand=True)
root.after(400, lambda: (cover.lift(), cover.focus_force()))
root.after(60000, root.destroy)
root.mainloop()
'''

import winapi

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, detail, flush=True)
    ok &= bool(cond)


proc = subprocess.Popen([sys.executable, "-c", WIN])
try:
    hwnd = None
    for _ in range(40):
        time.sleep(0.25)
        hwnd = winapi.find_minecraft()
        if hwnd:
            break
    check("find_minecraft", hwnd, hwnd)
    time.sleep(1.0)
    check("not foreground (covered)", not winapi.is_foreground(hwnd))
    x, y, w, h = winapi.client_rect(hwnd)
    check("client_rect", w > 1000 and h > 600, (x, y, w, h))
    img = winapi.capture_client(hwnd)
    check("capture_client", img is not None and img.shape[0] > 600, None if img is None else img.shape)
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
    t = time.perf_counter()
    for _ in range(20):
        winapi.capture_client(hwnd)
    print(f"INFO PrintWindow 1280x720: {(time.perf_counter() - t) / 20 * 1000:.1f} ms/장", flush=True)

    try:
        wgc = winapi.WGCScreen(hwnd)
        check("WGC first frame", not wgc.is_black())
        crop = wgc.grab([x + 10, y + 10, 20, 20])
        check("WGC covered window red at client", crop[:, :, 2].mean() > 150 and crop[:, :, 0].mean() < 100,
              crop.mean(axis=(0, 1)))
        f0 = wgc.frames
        time.sleep(2)
        print(f"INFO WGC frames/sec (static window): {(wgc.frames - f0) / 2:.1f}", flush=True)
        t = time.perf_counter()
        for _ in range(200):
            wgc.grab([x + 100, y + 100, 400, 20])
        print(f"INFO WGC grab: {(time.perf_counter() - t) / 200 * 1000:.2f} ms/번", flush=True)
        wgc.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("INFO WGC unavailable here:", repr(e), flush=True)
    scr, how = winapi.open_window_screen(hwnd)
    check("open_window_screen", not scr.is_black(), how)
    if hasattr(scr, "stop"):
        scr.stop()

    prio, throttle = winapi.keep_awake(hwnd)
    check("keep_awake priority", prio)
    check("keep_awake power throttling off", throttle)
    winapi.bring_to_front(hwnd)
    time.sleep(0.5)
    print("INFO bring_to_front -> foreground:", winapi.is_foreground(hwnd), flush=True)
except Exception as e:
    import traceback
    traceback.print_exc()
    check("exception", False, repr(e))
finally:
    proc.kill()
sys.exit(0 if ok else 1)
