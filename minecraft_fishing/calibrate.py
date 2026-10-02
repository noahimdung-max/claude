"""영역/색상 캘리브레이션.

실제 게임으로 (권장):
  python calibrate.py
  -> 게임에서 해당 장면이 나왔을 때 F7 누르면 캡처

녹화 영상으로:
  python calibrate.py --video "C:/Users/tyt18/Videos/NVIDIA/Minecraft/Minecraft 2026.10.02 - 20.22.59.02.mp4"
  -> 슬라이더로 장면 찾고 Enter

한 항목만 다시: --only bobber / bar / gauge / rod
"""
import argparse
import sys

import cv2
import numpy as np

from common import Screen, color_mask, durability_hue, load_config, save_config

VIEW_W, VIEW_H = 1280, 720    # 캘리브레이션 창 최대 크기


def fit(img, max_w=VIEW_W, max_h=VIEW_H):
    """화면에 맞게 크기 조정. (조정된 이미지, 배율) 반환."""
    h, w = img.shape[:2]
    s = min(max_w / w, max_h / h)
    interp = cv2.INTER_NEAREST if s > 1 else cv2.INTER_AREA
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=interp), s


def show_window(name, img):
    cv2.namedWindow(name, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(name, img)
    cv2.moveWindow(name, 20, 20)


# ---------- 장면 고르기 ----------
class VideoSource:
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            sys.exit(f"영상 열기 실패: {path}")
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.pos = 0

    def read(self, idx):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        return frame if ok else None

    def pick(self, what):
        win = "scene"
        print(f"\n[{what}] 장면 찾기: 슬라이더 드래그 / a,d = 1초 이동 / z,c = 1프레임 이동 / Enter = 선택")
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.moveWindow(win, 20, 20)
        state = {"idx": self.pos}

        def on_bar(v):
            state["idx"] = v

        cv2.createTrackbar("frame", win, self.pos, max(1, self.count - 1), on_bar)
        shown, frame = -1, None
        while True:
            if state["idx"] != shown:
                frame = self.read(state["idx"])
                shown = state["idx"]
                if frame is not None:
                    view, _ = fit(frame)
                    cv2.putText(view, f"{what}  {shown / self.fps:.1f}s  (Enter=select)", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                    cv2.imshow(win, view)
            k = cv2.waitKey(30) & 0xFF
            step = {ord("a"): -int(self.fps), ord("d"): int(self.fps), ord("z"): -1, ord("c"): 1}.get(k)
            if step:
                state["idx"] = int(np.clip(state["idx"] + step, 0, self.count - 1))
                cv2.setTrackbarPos("frame", win, state["idx"])
            elif k in (13, 32) and frame is not None:
                self.pos = shown
                cv2.destroyWindow(win)
                return frame
            elif k == 27:
                sys.exit("취소됨")


class LiveSource:
    def __init__(self, monitor):
        import keyboard
        self.keyboard = keyboard
        self.screen = Screen(monitor)

    def pick(self, what):
        print(f"\n[{what}] 게임에서 이 장면을 띄우고 F7 누르기 (ESC 취소)")
        while True:
            ev = self.keyboard.read_event()
            if ev.event_type != "down":
                continue
            if ev.name == "f7":
                frame = self.screen.full()
                print("  캡처됨")
                return frame
            if ev.name == "esc":
                sys.exit("취소됨")


# ---------- 영역/색 지정 ----------
def select_box(img, title):
    view, s = fit(img)
    print(f"  {title}: 드래그 후 Enter (다시 그리려면 그냥 다시 드래그)")
    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.moveWindow(title, 20, 20)
    x, y, w, h = cv2.selectROI(title, view, showCrosshair=False)
    cv2.destroyWindow(title)
    if w == 0 or h == 0:
        sys.exit("영역 선택 취소됨")
    return [int(x / s), int(y / s), max(1, round(w / s)), max(1, round(h / s))]


def select_roi(img, title, precise=True):
    """1차: 전체 화면에서 대충 → 2차: 확대해서 정확히."""
    x, y, w, h = select_box(img, f"{title} - 1/2 rough" if precise else title)
    if not precise:
        return [x, y, w, h]
    H, W = img.shape[:2]
    m = max(10, max(w, h) // 3)
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(W, x + w + m), min(H, y + h + m)
    px, py, pw, ph = select_box(img[y0:y1, x0:x1], f"{title} - 2/2 precise")
    return [x0 + px, y0 + py, pw, ph]


def pick_color(img, roi, title):
    x, y, w, h = roi
    crop = img[y:y + h, x:x + w].copy()
    view, s = fit(crop, 800, 600)
    picked = {}

    def on_mouse(event, mx, my, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            cx, cy = min(int(mx / s), w - 1), min(int(my / s), h - 1)
            picked["c"] = [int(v) for v in crop[cy, cx]]

    print(f"  {title}: 해당 색 위를 클릭")
    show_window(title, view)
    cv2.setMouseCallback(title, on_mouse)
    while "c" not in picked:
        if cv2.waitKey(20) == 27:
            sys.exit("색 선택 취소됨")
    cv2.destroyWindow(title)
    print(f"  -> BGR {picked['c']}")
    return picked["c"]


def confirm_mask(img, roi, color, tol, title):
    """선택한 색으로 잡히는 픽셀을 초록으로 보여줌."""
    x, y, w, h = roi
    crop = img[y:y + h, x:x + w].copy()
    m = color_mask(crop, color, tol)
    crop[m] = (0, 255, 0)
    view, _ = fit(crop, 800, 600)
    print(f"  {title}: 초록 = 감지된 부분 ({int(m.sum())}px). 아무 키나 누르면 계속")
    show_window(title, view)
    cv2.waitKey(0)
    cv2.destroyWindow(title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="녹화 파일 경로 (없으면 실제 게임 화면 사용)")
    ap.add_argument("--only", choices=["bobber", "bar", "gauge", "rod"], help="한 항목만 다시 설정")
    ap.add_argument("--pick-colors", action="store_true", help="바/물고기/게이지 색을 기본값 대신 직접 찍기")
    args = ap.parse_args()

    cfg = load_config()
    src = VideoSource(args.video) if args.video else LiveSource(cfg["monitor"])

    def want(name):
        return args.only in (None, name)

    if want("bobber"):
        img = src.pick("1. 찌가 물에 떠 있는 장면 (입질 전)")
        cfg["bobber_roi"] = select_roi(img, "bobber area", precise=False)
        cfg["bobber_color"] = pick_color(img, cfg["bobber_roi"], "bobber color (red part)")
        confirm_mask(img, cfg["bobber_roi"], cfg["bobber_color"], cfg["tolerance"], "bobber check")

    if want("bar"):
        img = src.pick("2. 미니게임 바 ( 물고기 ) 가 보이는 장면")
        cfg["bar_roi"] = select_roi(img, "bar area (bar line only)")
        if args.pick_colors:
            cfg["bar_color"] = pick_color(img, cfg["bar_roi"], "bracket color")
            cfg["fish_color"] = pick_color(img, cfg["bar_roi"], "fish color")
        confirm_mask(img, cfg["bar_roi"], cfg["bar_color"], cfg["bar_tolerance"], "bracket check")
        confirm_mask(img, cfg["bar_roi"], cfg["fish_color"], cfg["tolerance"], "fish check")

    if want("gauge"):
        img = src.pick("3. 원형 게이지가 '가득 찬' 장면")
        cfg["gauge_roi"] = select_roi(img, "gauge area")
        if args.pick_colors:
            cfg["gauge_color"] = pick_color(img, cfg["gauge_roi"], "gauge filled color")
        x, y, w, h = cfg["gauge_roi"]
        n = int(color_mask(img[y:y + h, x:x + w], cfg["gauge_color"], cfg["gauge_tolerance"]).sum())
        print(f"  -> 가득 찬 게이지 픽셀 {n}")
        if n < 20:
            print("  !! 너무 적음. 게이지 가득 찬 장면이 맞는지 확인하거나 --pick-colors 사용")
        cfg["gauge_full_pixels"] = max(n, 1)

    if want("rod"):
        img = src.pick("4. 핫바 낚싯대 내구도 줄이 보이는 장면")
        cfg["durability_roi"] = select_roi(img, "durability bar")
        x, y, w, h = cfg["durability_roi"]
        print(f"  -> 현재 내구도 색 hue={durability_hue(img[y:y + h, x:x + w])} (None이면 영역 다시)")

    save_config(cfg)
    print("\nconfig.json 저장 완료")


if __name__ == "__main__":
    main()
