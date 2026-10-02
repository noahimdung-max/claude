"""영역/색상 캘리브레이션.

사용 예:
  python calibrate.py --video "C:/Users/tyt18/Videos/NVIDIA/Minecraft/Minecraft 2026.10.02 - 20.22.59.02.mp4" --bobber-time 5 --game-time 12
  python calibrate.py --delay 5          # 실제 게임 화면을 5초 뒤 캡처

녹화 해상도와 실제 게임 해상도(전체화면 여부 포함)가 같아야 좌표가 맞는다.
"""
import argparse
import sys
import time

import cv2

from common import Screen, load_config, save_config


def frame_from_video(path, sec):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit(f"영상 열기 실패: {path}")
    cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"{sec}초 프레임 읽기 실패")
    return frame


def live_frame(monitor, delay):
    print(f"{delay}초 뒤 화면 캡처. 게임 창으로 전환해.")
    time.sleep(delay)
    return Screen(monitor).full()


def select_roi(img, title):
    print(f"[{title}] 드래그로 영역 선택 후 Enter/Space. 취소는 c")
    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI(title, img, showCrosshair=True)
    cv2.destroyWindow(title)
    if w == 0 or h == 0:
        sys.exit("영역 선택 취소됨")
    return [int(x), int(y), int(w), int(h)]


def pick_color(img, roi, title):
    print(f"[{title}] 확대된 화면에서 해당 색 위를 클릭. ESC 취소")
    x, y, w, h = roi
    crop = img[y:y + h, x:x + w].copy()
    scale = max(1, 800 // max(w, h))
    view = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
    picked = {}

    def on_mouse(event, mx, my, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            picked["c"] = [int(v) for v in crop[min(my // scale, h - 1), min(mx // scale, w - 1)]]

    cv2.namedWindow(title)
    cv2.setMouseCallback(title, on_mouse)
    while "c" not in picked:
        cv2.imshow(title, view)
        if cv2.waitKey(20) == 27:
            sys.exit("색 선택 취소됨")
    cv2.destroyWindow(title)
    print(f"  -> BGR {picked['c']}")
    return picked["c"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="녹화 파일 경로")
    ap.add_argument("--bobber-time", type=float, help="찌가 떠 있는 장면(초)")
    ap.add_argument("--game-time", type=float, help="미니게임 바가 보이는 장면(초)")
    ap.add_argument("--delay", type=float, default=5, help="실시간 캡처 대기 시간")
    ap.add_argument("--only", choices=["bobber", "bar"], help="한쪽만 다시 설정")
    args = ap.parse_args()

    cfg = load_config()

    def get_frame(sec, label):
        if args.video:
            if sec is None:
                sys.exit(f"--video 사용 시 {label} 시간 지정 필요")
            return frame_from_video(args.video, sec)
        print(f"{label} 장면을 띄워둬.")
        return live_frame(cfg["monitor"], args.delay)

    if args.only in (None, "bobber"):
        img = get_frame(args.bobber_time, "--bobber-time")
        cfg["bobber_roi"] = select_roi(img, "bobber area (찌 주변, 넉넉히)")
        cfg["bobber_color"] = pick_color(img, cfg["bobber_roi"], "bobber color (찌 빨간 부분)")

    if args.only in (None, "bar"):
        img = get_frame(args.game_time, "--game-time")
        cfg["bar_roi"] = select_roi(img, "minigame bar area (바 전체)")
        cfg["bar_color"] = pick_color(img, cfg["bar_roi"], "player bar color (움직이는 바)")
        cfg["fish_color"] = pick_color(img, cfg["bar_roi"], "fish color (물고기)")

    save_config(cfg)
    print("config.json 저장 완료")


if __name__ == "__main__":
    main()
