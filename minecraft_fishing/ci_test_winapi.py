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
    print(f"INFO PrintWindow 1280x720: {(time.perf_counter() - t) / 20 * 1000:.1f} ms/frame", flush=True)

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
        print(f"INFO WGC grab: {(time.perf_counter() - t) / 200 * 1000:.2f} ms/grab", flush=True)
        wgc.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("INFO WGC unavailable here:", repr(e), flush=True)
    scr, how = winapi.open_window_screen(hwnd)
    check("open_window_screen", not scr.is_black(), how)
    if hasattr(scr, "stop"):
        scr.stop()

    # 원시 입력 기록 + 상대 이동 (모루 자동 수리의 시점 돌리기/되돌리기)
    rec = winapi.RawMouseRecorder().start()
    time.sleep(0.3)
    winapi.send_mouse_move(240, -90)
    time.sleep(0.5)
    winapi.send_mouse_move(-240, 90)
    time.sleep(0.5)
    rdx, rdy = rec.stop()
    print(f"INFO raw recorder events={rec.events} net=({rdx},{rdy})", flush=True)
    check("raw recorder saw moves", rec.events > 0, rec.events)
    check("raw recorder net ~0 after there-and-back", abs(rdx) <= 2 and abs(rdy) <= 2, (rdx, rdy))
    rec2 = winapi.RawMouseRecorder().start()
    time.sleep(0.3)
    winapi.send_mouse_move(300, 120)
    time.sleep(0.5)
    d2 = rec2.stop()
    check("raw recorder measures one-way move", abs(d2[0] - 300) <= 3 and abs(d2[1] - 120) <= 3, d2)
    winapi.send_mouse_move(-300, -120)
    print("INFO options.txt sensitivity:", winapi.read_mouse_sensitivity(), flush=True)

    # Alt+Tab 뒤처럼 Alt 가 눌린 상태여도 F8 단축키가 먹는지 (KeyPoller: 키 상태를 직접 확인)
    hits = []
    poller = winapi.KeyPoller().add("f8", lambda: hits.append(1)).start()
    time.sleep(0.2)
    kb = winapi.user32.keybd_event
    kb(0x12, 0x38, 0, 0)                           # Alt 누름 (계속 눌린 상태)
    time.sleep(0.1)
    kb(0x77, 0x42, 0, 0)                           # F8
    time.sleep(0.08)
    kb(0x77, 0x42, 2, 0)
    time.sleep(0.2)
    kb(0x12, 0x38, 2, 0)                           # Alt 뗌
    time.sleep(0.5)
    kb(0x77, 0x42, 0, 0)                           # 0.5초 뒤 한 번 더 (총 2번)
    time.sleep(0.08)
    kb(0x77, 0x42, 2, 0)
    time.sleep(0.2)
    time.sleep(0.5)
    kb(0x77, 0x42, 0, 0)                           # 꾹 누르기 (자동 반복처럼 누름 신호 여러 번) -> 1번만
    for _ in range(8):
        time.sleep(0.08)
        kb(0x77, 0x42, 0, 0)
    time.sleep(0.1)
    kb(0x77, 0x42, 2, 0)
    time.sleep(0.3)
    poller.stop()
    print(f"INFO f8 presses seen: {len(hits)}", flush=True)
    check("F8: Alt held, after, and a long hold count as 3 presses", len(hits) == 3, len(hits))

    # 원시 입력 기록기를 여러 번 만들어도 (창 클래스 재사용 없이) 매번 동작
    for i in range(3):
        r = winapi.RawMouseRecorder().start()
        time.sleep(0.2)
        winapi.send_mouse_move(50, 0)
        time.sleep(0.3)
        d = r.stop()
        winapi.send_mouse_move(-50, 0)
        check(f"raw recorder #{i + 1}", abs(d[0] - 50) <= 2, d)

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
