import colorsys
import json
import re
import sys
from pathlib import Path

import cv2
import mss
import numpy as np

HERE = Path(__file__).parent
# exe 로 실행하면 설정은 exe 옆에 저장 (임시 폴더에 두면 끌 때 사라짐)
DATA_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else HERE
CONFIG_PATH = DATA_DIR / "config.json"
SUBTITLE_PATH = DATA_DIR / "subtitle.png"
HISTORY_PATH = DATA_DIR / "history.json"
ANVIL_PATH = DATA_DIR / "anvil_view.png"     # 모루를 정확히 바라본 화면 (돌아갈 때 맞춤 기준)

DEFAULTS = {
    "monitor": 1,
    "bite_mode": "both",         # both = 자막 또는 찌 둘 중 먼저 잡히는 것(기본) / subtitle = 자막만 / bobber = 찌만
    "subtitle_roi": None,        # [x, y, w, h] 자막을 찾을 영역 (자막 지정 시 자동 계산)
    "subtitle_threshold": 0.8,   # 자막 글자 일치도 기준 (0~1)
    "bite_confirm_frames": 2,    # 연속 몇 번 감지돼야 입질로 볼지
    "bobber_roi": None,          # [x, y, w, h] 찌가 떨어질 수 있는 물 영역 (찌 모드)
    "bobber_color": None,        # [B, G, R] 찌 빨간 부분
    "bar_roi": None,             # [x, y, w, h] 미니게임 바 영역. 비워두면 첫 미니게임 때 자동 탐색 후 저장
    "bar_search_roi": None,      # 자동 탐색 범위. 비워두면 화면 아래쪽 가운데
    "bar_color": [226, 196, 145],    # [B, G, R] 잡는 구간 양쪽 괄호 ( ) 하늘색
    "fish_color": [115, 227, 109],   # [B, G, R] 물고기 연두색
    "sneak_key": "shift",
    "win_h": None,
    "ref_client": None,          # 위치들을 지정할 때 마크 창 [x, y, w, h] (창이 바뀌면 이걸 기준으로 옮김)
    "ref_gui": None,             # 그때 GUI 배율               # 프로그램 창 높이 (사용자가 조절한 값)        # 미니게임 웅크리기 키: shift / ctrl
    "durability_roi": None,      # [x, y, w, h] 핫바 낚싯대 칸의 내구도 줄만
    "durability_max": 64,        # 낚싯대 최대 내구도
    "durability_stop_pct": 20,   # 내구도가 최대의 이 % 이하가 되면 멈춤
    "durability_ignore": False,  # True 면 내구도 안 봄 (수선 낚싯대)
    "exact_durability": False,   # (실험) 인벤 툴팁(F3+H)으로 정확한 내구도 읽기
    "exact_slot": 0,             # 정밀 내구도로 읽을 핫바 칸 (0 = 지금 들고 있는 칸, 1~9 = 그 칸)
    "inv_check_every": 10,       # 몇 마리마다 인벤 열어서 확인할지
    "inv_full_stop": False,      # 인벤 빈칸이 기준 이하면 멈춤
    "inv_min_empty": 0,          # 빈칸이 이 개수 이하면 '가득 참'
    "log_file": False,           # 세부 탭: exe 옆 macro.log 에 단계별 기록
    "repair_on": False,          # (실험) 모루 자동 수리
    "repair_rod_slot": 1,        # 수리할 낚싯대 핫바 칸
    "repair_string_slot": 2,     # 실 핫바 칸
    "repair_cost": 400,          # 수리비 (골드)
    "repair_turn": None,         # [dx, dy] 물 -> 모루 마우스 이동량 (기록)
    "repair_points": None,       # 수리 창 위치 {"in1","in2","ok","out","hot1","hot9": [x, y]} (화면 기준)
    "gold_roi": None,            # 화면의 골드 숫자 영역
    "repair_yaw": None,          # 기록 대신 각도로: 좌우(도, 오른쪽 +)
    "repair_pitch": 0,           # 위아래(도, 아래 +)
    "mouse_sens_pct": 100,       # 마크 마우스 감도 % (설정 화면 숫자)
    "subtitle_scale": None,      # 자막 지정 때 마크 GUI 배율
    "bar_scale": None,           # 미니게임 바 찾을 때 GUI 배율
    "rod_swap": False,           # 내구도 기준 아래면 다른 칸 낚싯대로 교체
    "rod_slots": [1, 2, 3],      # 낚싯대가 들어 있는 핫바 칸 (1~9)
    "background": False,         # True 면 다른 창 써도 낚시 (마크 창만 캡처/입력, F3+P 필요)
    "max_fails": 5,              # 연속으로 이만큼 못 낚으면 멈춤
    "goal_count": 0,             # 이만큼 낚으면 멈춤 (0 = 끔)
    "goal_minutes": 0,           # 이만큼 지나면 멈춤 (0 = 끔)
    "discord_webhook": "",       # 디스코드 웹훅 주소 (멈출 때 알림)
    "notify_each_catch": False,  # 낚을 때마다 디스코드 알림
    "total_caught": 0,           # 지금까지 낚은 총 수 (계속 누적)
    "tolerance": 30,             # 색 허용 오차(채널별)
    "bar_tolerance": 45,         # 괄호는 픽셀마다 밝기 차이가 커서 넉넉히
    "min_pixels": 6,             # 검출로 인정할 최소 픽셀 수
    "cast_settle_sec": 2.0,      # 던진 뒤 찌가 자리잡을 때까지 대기
    "bite_timeout_sec": 45.0,    # 입질 안 오면 다시 던짐
    "bite_drop_ratio": 0.5,      # (찌 모드) 찌 픽셀 수가 기준치의 이 비율 아래로 떨어지면 입질
    "bite_dip_px": 4,            # (찌 모드) 찌가 최소 이만큼 내려가야 입질 (흔들림이 크면 자동으로 더 크게)
    "minigame_start_timeout_sec": 4.0,
    "minigame_end_missing_sec": 0.6,
    "deadzone_px": 3,            # 바-물고기 오차 허용 범위
    "left_click_cps": 10,        # 미니게임 중 좌클릭 연타 (초당 횟수, 0 = 끔)
    "lead_sec": 0.05,            # 바 속도 기반 예측 시간
    "reel_click_after_game": False,  # 미니게임 끝나고 우클릭 한 번 더 필요하면 true
    "recast_delay_sec": 1.0,
    "start_delay_sec": 1.0,      # 시작 버튼 후 대기 (마크 창은 자동으로 앞으로 옴)
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


class Screen:
    def __init__(self, monitor=1):
        self.sct = mss.mss()
        self.mon = self.sct.monitors[monitor]

    def full(self):
        return np.ascontiguousarray(np.array(self.sct.grab(self.mon))[:, :, :3])

    def grab(self, roi):
        x, y, w, h = roi
        box = {"left": self.mon["left"] + x, "top": self.mon["top"] + y, "width": w, "height": h}
        return np.ascontiguousarray(np.array(self.sct.grab(box))[:, :, :3])


# ---------------------------------------------------------------- 색 판정
def color_mask(img, color, tol):
    diff = np.abs(img.astype(np.int16) - np.array(color, dtype=np.int16))
    return np.all(diff <= tol, axis=2)


def _bgr(img):
    f = img.astype(np.int16)
    return f[..., 0], f[..., 1], f[..., 2]


def bobber_mask(img, cfg=None):
    """찌 빨간 부분: 선명한 빨강 (어두울 때도 잡히게 밝기 기준은 낮게). 고른 색은 안 씀
    (해질녘 하늘까지 잡혀서). 하늘 같은 큰 덩어리는 find_bobber 의 모양 검사로 걸러냄."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return ((h <= 10) | (h >= 170)) & (s >= 150) & (v >= 60)


def find_bobber(img, center, ignore=None, min_px=6, max_side=80):
    """찌 찾기: '작은 빨간 덩어리 + 바로 위나 아래에 붙은 흰 부분' 중 center(조준점)에 가장 가까운 것.
    ignore: 던지기 전부터 있던 빨간 물체 마스크. 반환 (x, y, w, h) 또는 None"""
    red = bobber_mask(img)
    if ignore is not None and ignore.shape == red.shape:
        red &= ~ignore
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    light = (hsv[..., 1] <= 110) & (hsv[..., 2] >= 110)       # 흰 부분 (노을에 물들어도)
    n, _, st, cent = cv2.connectedComponentsWithStats(
        cv2.dilate(red.astype(np.uint8), np.ones((3, 3), np.uint8)))
    best, best_d = None, None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if area < min_px or w > max_side or h > max_side:
            continue
        band = max(2, h)
        near_light = light[max(0, y - band):y, x:x + w].sum() + light[y + h:y + h + band, x:x + w].sum()
        if near_light < 0.3 * area:
            continue
        d = (cent[i][0] - center[0]) ** 2 + (cent[i][1] - center[1]) ** 2
        if best_d is None or d < best_d:
            best, best_d = (x, y, w, h), d
    return best


def fish_mask(img, cfg):
    """밝은 연두 (미니게임 물고기, 원형 게이지)."""
    b, g, r = _bgr(img)
    rule = (g > 150) & (g > r + 60) & (g > b + 50)
    return rule | color_mask(img, cfg["fish_color"], cfg["tolerance"])


def track_mask(img):
    """미니게임 바 트랙 (파랑/청록). 트랙 색은 빨강 성분이 0 이라 게임 배경과 구분됨."""
    b, g, r = _bgr(img)
    return (r <= 25) & (b > 40) & (b > r + 40)


def fishlike_mask(img):
    """파란 계열이 아닌 선명한 색 (물고기는 종류마다 색이 다름: 초록, 노랑 ...)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    blue = (h >= 85) & (h <= 115)
    return (s >= 90) & (v >= 115) & ~blue


def bracket_mask(img, cfg):
    """잡는 구간 괄호 ( ) 하늘색."""
    b, g, r = _bgr(img)
    rule = (b > 170) & (g > 140) & (r > 80) & (b > r + 40) & (b - g >= 10) & (b - g <= 80)
    return rule | color_mask(img, cfg["bar_color"], cfg["bar_tolerance"])


def durability_value(img, max_dur=64):
    """핫바 낚싯대 내구도를 숫자로. 마크 공식: 바 색 hue = 120° x 남은/최대, 바 길이 = 13칸 x 남은/최대.
    반환 (값, 종류)
      종류 'color': 바 색으로 계산한 값
      종류 'low'  : 검은 바탕 줄만 있고 색 바가 없음 = 남은 내구도 1~2 (마크가 너무 짧아서 안 그림)
      종류 'full' : 내구도 바 자체가 없음 = 최대 (닳지 않음)"""
    f = img.astype(np.int16)
    mx, mn = f.max(axis=2), f.min(axis=2)
    pure = (mx >= 200) & (mn <= 40)          # 내구도 바는 채도 100% 색 (아이템 그림은 이렇게 안 쨍함)
    per_row = pure.sum(axis=1)
    if per_row.max() >= 2:
        y = int(per_row.argmax())
        px = img[y][pure[y]].astype(np.float32) / 255
        b, g, r = px[:, 0].mean(), px[:, 1].mean(), px[:, 2].mean()
        hue = colorsys.rgb_to_hsv(r, g, b)[0] * 360
        if hue > 300:                        # 빨강 근처 (360 = 0)
            hue = 0.0
        val = min(max_dur, max(0, round(hue / 120 * max_dur)))
        return int(val), "color"
    # 1~2 남으면 색 바 없이 검은 바탕 줄(칸 폭의 13/16)만 그려짐 -> 길게 이어진 검은 가로줄이 있어야 인정
    # (아이템 그림의 어두운 점들을 '거의 다 닳음'으로 잘못 보지 않게)
    black = mx <= 25
    need = max(4, int(img.shape[1] * 0.7))
    for row in black:
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
        if idx.size and (idx[1::2] - idx[::2]).max() >= need:
            return 2, "low"
    return int(max_dur), "full"


# ---------------------------------------------------------------- 미니게임 바
def runs(idx, max_gap=1):
    """정렬된 인덱스 -> 연속 구간 [(시작, 끝), ...]"""
    if idx.size == 0:
        return []
    groups = np.split(idx, np.nonzero(np.diff(idx) > max_gap)[0] + 1)
    return [(int(g[0]), int(g[-1])) for g in groups]


def bracket_runs(bar, cfg):
    """바 이미지에서 얇은 세로 괄호들의 열 구간. 넓은 하늘색 띠(경험치 바 등)는 제외."""
    cols = np.nonzero(bracket_mask(bar, cfg).any(axis=0))[0]
    max_w = max(3, bar.shape[0] // 2)
    return [(a, b) for a, b in runs(cols) if b - a + 1 <= max_w]


def track_extent(bar):
    """바 이미지에서 파란 트랙이 있는 (행 범위, 열 범위). 없으면 None.
    바 영역이 실제 바보다 넓어도 바깥 게임 화면(배경)을 무시하기 위해 씀."""
    t = track_mask(bar)
    rows = np.nonzero(t.mean(axis=1) >= 0.3)[0]
    if rows.size == 0:
        return None
    r0, r1 = int(rows.min()), int(rows.max())
    cols = np.nonzero(t[r0:r1 + 1].mean(axis=0) >= 0.5)[0]
    if cols.size == 0:
        return None
    gap = 8 * (r1 - r0 + 1)              # 물고기/괄호가 트랙을 가리는 폭까지는 이어진 걸로 봄
    groups = runs(cols, gap)
    c0, c1 = max(groups, key=lambda g: g[1] - g[0])
    return (r0, r1), (c0, c1)


def fish_blob_x(bar, cfg):
    """트랙 위의 '파랑이 아닌 선명한 덩어리'(물고기) 가운데 x. 물고기 색은 판마다 다름.
    트랙 가로 범위 밖(게임 배경)과, 크기/높이가 물고기답지 않은 덩어리는 제외."""
    ext = track_extent(bar)
    if ext is None:
        return None
    (r0, r1), (c0, c1) = ext
    core_h = r1 - r0 + 1
    m = np.zeros(bar.shape[:2], bool)
    y0, y1 = max(0, r0 - 2), r1 + 3
    m[y0:y1, c0:c1 + 1] = fishlike_mask(bar[y0:y1, c0:c1 + 1])
    n, _, st, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    best, best_area = None, 0
    for i in range(1, n):
        w, h, area = (int(v) for v in st[i, 2:5])
        cy = cent[i][1]
        if (area >= cfg["min_pixels"] and area > best_area and h >= 0.5 * core_h and w <= 4 * bar.shape[0]
                and r0 - 1 <= cy <= r1 + 1):
            best, best_area = float(cent[i][0]), area
    return best


FISH_COLORS = [(15, "빨강"), (40, "주황"), (70, "노랑"), (165, "초록"), (185, "하늘"), (260, "파랑"),
               (300, "보라"), (345, "분홍"), (360, "빨강")]


def fish_color_name(above):
    """바 위 가운데 아이콘(물고기 등급 표시) 색 -> '초록', '주황', '파랑' 같은 이름.
    바 위를 지나가는 물고기 그림은 항상 같은 색이라 아이콘 색으로 구분함."""
    if above is None or above.size == 0:
        return None
    hsv = cv2.cvtColor(above, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 1] >= 160) & (hsv[..., 2] >= 80)        # 아이콘만 (뒤 배경은 채도·밝기가 낮음)
    if m.sum() < 12:
        return None
    hue = hsv[..., 0][m].astype(np.float32) * 2
    # 아이콘 안 작은 그림(빨간 낚싯대 등)보다 바탕색이 많음 -> 가장 많은 색 구간
    names = [next(n for lim, n in FISH_COLORS if h <= lim) for h in hue]
    vals, cnt = np.unique(names, return_counts=True)
    k = int(np.argmax(cnt))
    if cnt[k] < 0.8 * (above.shape[0] / 3) ** 2:        # 아이콘이 없으면(색 조각만) 이름 안 붙임
        return None
    return str(vals[k])


def gauge_present(above, bar_h):
    """바 위 가운데에 원형 게이지가 있는지. 게이지 색은 물고기마다 다름(초록/파랑/...) -> 색이 아니라
    '바 높이보다 큰 선명한 동그라미'로 판단. 평소 화면의 경험치 숫자는 이보다 작음."""
    hsv = cv2.cvtColor(above, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 1] >= 80) & (hsv[..., 2] >= 80)).astype(np.uint8)
    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return False
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    w, h, area = (int(v) for v in st[i, 2:5])
    return w >= 1.5 * bar_h and h >= 1.2 * bar_h and area >= 1.5 * bar_h * bar_h


def view_roi(bar_roi):
    """바 + 그 위 게이지까지 한 번에 캡처할 영역. 반환: (영역, 바가 시작하는 행)"""
    x, y, w, h = bar_roi
    top = max(0, y - 3 * h)
    return [x, top, w, y + h - top], y - top


def split_view(img, bar_row):
    """view_roi 로 캡처한 이미지 -> (바 부분, 게이지 자리)"""
    bar = img[bar_row:]
    h = bar.shape[0]
    cx = img.shape[1] // 2
    above = img[:bar_row, max(0, cx - 2 * h): cx + 2 * h]
    return bar, above


def locate_bar(img, cfg):
    """화면에서 미니게임 바 위치 자동 탐색.
    가운데를 가로지르는 파란 트랙 띠 + 얇은 괄호 + 그 위 가운데 초록 게이지가 있는 곳. 물고기 색과 무관.
    반환: img 기준 [x, y, w, h] 또는 None."""
    H, W = img.shape[:2]
    cx = W // 2
    q = max(20, W // 10)
    track = track_mask(img)
    good_px = track | bracket_mask(img, cfg)     # 물고기는 gap 으로 건너뜀 (배경 색에 끌려 넓어지지 않게)
    rows = np.nonzero(track[:, cx - q:cx + q].mean(axis=1) >= 0.4)[0]

    for y0, y1 in sorted(runs(rows, 1), key=lambda g: g[0] - g[1]):     # 두꺼운 띠부터
        bh = y1 - y0 + 1
        if bh < 2 or bh > H // 4:
            continue
        good = good_px[y0:y1 + 1].mean(axis=0) >= 0.5
        gap = 4 * bh

        def reach(step):
            last, miss, x = None, 0, cx
            while 0 <= x < W:
                if good[x]:
                    last, miss = x, 0
                else:
                    miss += 1
                    if miss > gap:
                        break
                x += step
            return last

        left, right = reach(-1), reach(1)
        if left is None or right is None:
            continue
        half = max(cx - left, right - cx)
        if 2 * half < 10 * bh:
            continue
        pad = 3
        x0, x1 = max(0, cx - half - pad), min(W - 1, cx + half + pad)
        yy0, yy1 = max(0, y0 - pad), min(H - 1, y1 + pad)
        roi = [x0, yy0, x1 - x0 + 1, yy1 - yy0 + 1]

        # 검증: 얇은 괄호가 있고, 바 위 가운데에 게이지가 있어야 함 (평소 경험치 바 등 제외)
        vr, bar_row = view_roi(roi)
        vx, vy, vw, vh = vr
        bar_img, above = split_view(img[vy:vy + vh, vx:vx + vw], bar_row)
        if bracket_runs(bar_img, cfg) and gauge_present(above, roi[3]):
            return roi
    return None


# ---------------------------------------------------------------- 자막
TEXT_LEVEL = 170   # 새로 뜬 자막 글자는 흰색. 배경(반투명 검정 상자)은 이보다 어두움


def to_gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def text_binary(gray):
    """흰 글자만 남김 (배경 무늬 영향 제거)."""
    return np.where(gray >= TEXT_LEVEL, 255, 0).astype(np.uint8)


def make_subtitle_template(crop):
    """드래그한 자막 영역(BGR) -> (글자만 꽉 맞춘 흑백 템플릿, 크롭 안에서의 [x, y, w, h]). 글자 없으면 None."""
    b = to_gray(crop) >= TEXT_LEVEL
    if b.sum() < 10:
        return None
    ys, xs = np.nonzero(b)
    h, w = b.shape
    x0, y0 = max(0, xs.min() - 1), max(0, ys.min() - 1)
    x1, y1 = min(w - 1, xs.max() + 1), min(h - 1, ys.max() + 1)
    tmpl = np.where(b[y0:y1 + 1, x0:x1 + 1], 255, 0).astype(np.uint8)
    return tmpl, [int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)]


def load_subtitle_template():
    if not SUBTITLE_PATH.exists():
        return None
    from PIL import Image
    return text_binary(np.array(Image.open(SUBTITLE_PATH).convert("L")))


def save_subtitle_template(tmpl):
    from PIL import Image
    Image.fromarray(tmpl).save(SUBTITLE_PATH)


def subtitle_search_roi(rect, img_w, img_h):
    """자막 글자 위치 -> 찾을 영역. 자막은 오른쪽 아래에 쌓이고 줄 위치/폭이 바뀌니 넉넉히."""
    x, y, w, h = rect
    x0, y0 = max(0, x - 2 * w), max(0, y - 10 * h)
    x1, y1 = img_w, min(img_h, y + 7 * h)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def match_bin(g, tmpl):
    """이진화된 화면 g 안에서 템플릿과 가장 비슷한 곳: (일치도 0~1, (x, y) 왼쪽 위). 못 찾으면 (0.0, None)."""
    th, tw = tmpl.shape[:2]
    if g.shape[0] < th or g.shape[1] < tw:
        return 0.0, None
    res = np.nan_to_num(cv2.matchTemplate(g, tmpl, cv2.TM_CCOEFF_NORMED), nan=0.0, posinf=0.0, neginf=0.0)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return float(mx), (int(loc[0]), int(loc[1]))


def match_best(img, tmpl):
    """img(BGR) 안에서 자막 템플릿(흰 글자)과 가장 비슷한 곳: (일치도 0~1, (x, y) 왼쪽 위)."""
    return match_bin(text_binary(to_gray(img)), tmpl)


def scale_template(tmpl, ratio):
    """이진 자막 템플릿을 ratio 배로 (줄일 땐 AREA, 늘릴 땐 LINEAR 로 부드럽게 줄인/늘린 뒤 다시 이진화).
    크기가 안 바뀌면 원본 그대로."""
    h, w = tmpl.shape[:2]
    nw, nh = max(1, round(w * ratio)), max(1, round(h * ratio))
    if (nw, nh) == (w, h):
        return tmpl
    out = cv2.resize(tmpl, (nw, nh), interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR)
    return ((out > 127) * 255).astype(np.uint8)


def match_score(img, tmpl):
    """img(BGR) 안에서 자막 템플릿(흰 글자)과 가장 비슷한 곳의 일치도 (0~1)."""
    return match_best(img, tmpl)[0]


# ---------------------------------------------------------------- 핫바
def selected_slot(img):
    """화면 아래쪽에서 핫바의 '선택된 칸'(밝은 네모 테두리)을 찾음. 반환 img 기준 (x, y, w, h) 또는 None."""
    f = img.astype(np.int16)
    mx, mn = f.max(axis=2), f.min(axis=2)
    m = ((mn >= 190) & (mx - mn <= 45)).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if w < 16 or h < 16 or abs(w - h) > 0.25 * w or area > 0.6 * w * h:
            continue                      # 네모 '테두리'만 (글자/꽉 찬 덩어리 제외)
        if best is None or w * h > best[2] * best[3]:
            best = (x, y, w, h)
    return best


def durability_roi_in_slot(slot):
    """선택된 칸 안에서 내구도 줄이 그려지는 아래쪽 부분."""
    x, y, w, h = slot
    return [int(x + 0.08 * w), int(y + 0.70 * h), max(1, int(0.84 * w)), max(1, int(0.22 * h))]


# ---------------------------------------------------------------- 날짜별 기록
def load_history():
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_history(hist):
    try:
        tmp = HISTORY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        tmp.replace(HISTORY_PATH)
    except OSError:
        pass


def history_day(hist, day):
    d = hist.setdefault(day, {})
    for k in ("caught", "casts", "games", "seconds"):
        d.setdefault(k, 0)
    d.setdefault("colors", {})
    return d


# ---------------------------------------------------------------- 인벤토리 (정밀 내구도 / 빈칸)
# 마크 기본 글꼴(ascii.png)의 숫자와 '/' (5x7)
_GLYPHS = {
    "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    "1": "..#..|.##..|..#..|..#..|..#..|..#..|#####",
    "2": ".###.|#...#|....#|..##.|.#...|#...#|#####",
    "3": ".###.|#...#|....#|..##.|....#|#...#|.###.",
    "4": "...##|..#.#|.#..#|#...#|#####|....#|....#",
    "5": "#####|#....|####.|....#|....#|#...#|.###.",
    "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
    "7": "#####|#...#|....#|...#.|..#..|..#..|..#..",
    "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
    "/": "....#|...#.|...#.|..#..|.#...|.#...|#....",
}
GLYPHS = {k: np.array([[c == "#" for c in row] for row in v.split("|")]) for k, v in _GLYPHS.items()}

INV_W, INV_H = 176, 166          # 인벤 창 크기 (GUI 픽셀)
INV_FILL = 198                   # 인벤 창 바탕 회색
SLOT_EMPTY = 139                 # 빈 칸 회색


def find_inventory(img):
    """열린 인벤(서바이벌) 창을 찾음. 반환 (왼쪽, 위, GUI 배율) 또는 None.
    바탕 회색(198) 덩어리 = 창에서 테두리 2칸씩 뺀 172x162."""
    m = (np.abs(img.astype(np.int16) - INV_FILL).max(axis=2) <= 3).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _ = (int(v) for v in st[i])
    s = round(w / (INV_W - 4))
    if s < 1 or abs(w - (INV_W - 4) * s) > s or abs(h - (INV_H - 4) * s) > 2 * s:
        return None
    return x - 2 * s, y - 2 * s, s


def guess_inventory(w, h, s):
    """인벤 창 위치를 계산으로 (마크는 화면 가운데에 둠). find_inventory 가 실패할 때 대신."""
    gw, gh = -(-w // s), -(-h // s)
    return ((gw - INV_W) // 2) * s, ((gh - INV_H) // 2) * s, s


def screen_changed(a, b, thr=12.0):
    """두 화면이 크게 달라졌는지 (인벤 같은 창이 열리면 뒤가 어두워짐)."""
    if a is None or b is None or a.shape != b.shape:
        return False
    sa = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
    sb = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
    return float(np.abs(sa.astype(np.int16) - sb).mean()) > thr


def _edge_brightness(img):
    """화면 가장자리(창 GUI 가 안 덮는 곳) 밝기."""
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bw, bh = max(2, w // 8), max(2, h // 8)
    return float(np.concatenate([g[:, :bw].ravel(), g[:, -bw:].ravel(), g[:bh].ravel(), g[-bh:].ravel()]).mean())


def gui_overlay(before, after, ratio=0.8):
    """마크에서 창(인벤·모루·일시정지 메뉴 등)이 떠 있는지: 창이 열리면 뒤 게임 화면이 어두워짐.
    찌·물결 움직임처럼 화면만 조금 바뀐 건 '열림'으로 안 봄."""
    if before is None or after is None or before.shape != after.shape:
        return False
    b0, b1 = _edge_brightness(before), _edge_brightness(after)
    return b0 > 8 and b1 < b0 * ratio and screen_changed(before, after, 8)


def save_debug_image(img, name):
    """문제 생겼을 때 화면을 exe 옆에 저장 (보내주면 원인 확인용). 한글 경로 지원."""
    if img is None:
        return
    try:
        ok, buf = cv2.imencode(".png", img)
        if ok:
            (DATA_DIR / name).write_bytes(buf.tobytes())
    except OSError:
        pass


def inventory_slots(inv):
    """칸 36개 (위 3줄 27 + 핫바 9) 의 (x, y, 크기). 핫바는 뒤 9개 = 1~9번 칸."""
    x0, y0, s = inv
    out = [(x0 + (8 + 18 * c) * s, y0 + (84 + 18 * r) * s, 16 * s) for r in range(3) for c in range(9)]
    out += [(x0 + (8 + 18 * c) * s, y0 + 142 * s, 16 * s) for c in range(9)]
    return out


def slot_is_empty(img, slot):
    x, y, size = slot
    a = img[y:y + size, x:x + size].astype(np.int16)
    if a.size == 0:
        return False
    return float((np.abs(a - SLOT_EMPTY).max(axis=2) <= 6).mean()) >= 0.97


def _glyph_of(seg, s):
    """흰 글자 덩어리 하나를 5x7 로 줄여 숫자/'/' 판별. 아니면 None."""
    h, w = seg.shape
    if abs(h - 7 * s) > max(1, s // 2) or abs(w - 5 * s) > max(1, s // 2):
        return None
    small = seg[s // 2::s, s // 2::s][:7, :5]
    if small.shape != (7, 5):
        return None
    best, bd = None, 99
    for k, g in GLYPHS.items():
        d = int((small != g).sum())
        if d < bd:
            best, bd = k, d
    return best if bd <= 2 else None


def find_tooltip(img, with_mask=False):
    """툴팁 상자(거의 검은 보라색 바탕) 영역 (x, y, w, h). 없으면 None.
    with_mask=True 면 (상자, 상자 모양 마스크) - 상자 밖 인벤 테두리 글자처럼 보이는 것 제외용."""
    f = img.astype(np.int16)
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    m = ((g <= 22) & (r >= 8) & (r <= 45) & (b >= 8) & (b <= 45) & (r - g >= 6)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))   # 글자 구멍 메움
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, area = (int(v) for v in st[i])
    if w < 30 or h < 15:
        return None
    if not with_mask:
        return x, y, w, h
    inside = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
    inside = cv2.morphologyEx(inside, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))   # 글자 자리까지 덮기
    return (x, y, w, h), inside > 0


def read_tooltip_durability(img):
    """툴팁의 '내구도: 57 / 64' 에서 (57, 64). 글자 언어 상관없이 '숫자 / 숫자' 를 찾음."""
    found = find_tooltip(img, with_mask=True)
    if found is None:
        return None
    (x, y, w, h), inside = found
    img = img[y:y + h, x:x + w]
    f = img.astype(np.int16)
    mn, mx = f.min(axis=2), f.max(axis=2)
    white = ((mn >= 150) & (mx - mn <= 25) & inside).astype(np.uint8)   # 흰/회색 글자 (그림자는 어두워서 빠짐)
    n, _, st, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    chars = []                                    # 글자 하나 = 덩어리 하나 (숫자, '/' 는 한 덩어리)
    for i in range(1, n):
        x0, y0, w0, h0, _ = (int(v) for v in st[i])
        sc = round(h0 / 7)
        if sc < 1 or sc > 8:
            continue
        k = _glyph_of(white[y0:y0 + h0, x0:x0 + w0], sc)
        if k:
            chars.append((y0, x0, x0 + w0, sc, k))
    chars.sort()
    lines = []                                    # 같은 줄 = 윗변 높이가 같음
    for ch in chars:
        if lines and abs(lines[-1][0][0] - ch[0]) <= ch[3]:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    for ln in lines:
        ln.sort(key=lambda c: c[1])
        text, prev = "", None
        for y0, x0, x1, sc, k in ln:
            if prev is not None:
                text += "" if x0 - prev <= 2 * sc else (" " if x0 - prev <= 8 * sc else " | ")
            text += k
            prev = x1
        m = re.search(r"(\d+) ?/ ?(\d+)", text)
        if m:
            cur, mx_ = int(m.group(1)), int(m.group(2))
            if 0 < mx_ and 0 <= cur <= mx_:
                return cur, mx_
    return None


def hotbar_index(slot, client_w):
    """선택 칸 테두리(24x24 GUI) 위치로 핫바 몇 번째 칸인지 (0~8)."""
    x, y, w, h = slot
    s = w / 24
    left = client_w / 2 - 91 * s
    return int(min(8, max(0, round((x + w / 2 - left - 11 * s) / (20 * s)))))


def read_number(img):
    """HUD 숫자 읽기 (예: 골드 '30,979' -> 30979). 마크 글꼴 숫자만 골라 왼쪽부터. 못 읽으면 None.
    글자가 어둡거나 옆에 밝은 아이콘이 있어도 되게 밝기 기준을 몇 단계로 바꿔 보고 숫자가 가장 많이 읽힌 걸 씀."""
    if img is None or img.size == 0:
        return None
    v = img.astype(np.int16).max(axis=2)
    best = []
    for level in sorted(set(int(t) for t in np.unique(v) if t >= 40), reverse=True)[:40]:
        mask = (v >= level * 0.85).astype(np.uint8)           # 그림자(1/4 밝기)는 빠짐
        n, _, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        digits = []
        for i in range(1, n):
            x, y, w, h, _ = (int(t) for t in st[i])
            sc = round(h / 7)
            if sc < 1:
                continue
            k = _glyph_of(mask[y:y + h, x:x + w], sc)
            if k and k.isdigit():
                digits.append((x, k))
        if len(digits) > len(best):
            best = digits
    if not best:
        return None
    best.sort()
    return int("".join(k for _, k in best))


def turn_pixels(yaw_deg, pitch_deg, sens_pct):
    """마크 회전 공식: 마우스 1칸 = 0.15 x ((감도*0.6+0.2)^3 x 8) 도. 감도는 설정 화면 %/200."""
    s = sens_pct / 200
    deg = 0.15 * ((s * 0.6 + 0.2) ** 3 * 8)
    return round(yaw_deg / deg), round(pitch_deg / deg)


def view_shift(ref, cur, width=320):
    """두 게임 화면에서 풍경이 몇 px 밀렸는지 (dx, dy, 신뢰도). 손·핫바·자막이 없는 가운데 위쪽만 봄.
    시점이 오른쪽으로 더 돌아가 있으면 풍경이 왼쪽으로 밀려서 dx < 0."""
    h, w = ref.shape[:2]
    if cur.shape[:2] != (h, w):
        return None
    y0, y1, x0, x1 = int(h * 0.08), int(h * 0.62), int(w * 0.12), int(w * 0.88)
    k = min(1.0, width / (x1 - x0))

    def prep(img):
        g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        return g - g.mean()

    a, b = prep(ref), prep(cur)
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, win)
    return dx / k, dy / k, resp


def view_focal_px(height, fov=70):
    """마크 시야(FOV, 세로)로 화면 1도당 픽셀 계산용 초점거리(px)."""
    import math
    return (height / 2) / math.tan(math.radians(fov) / 2)


def _remap_axis(c, old_size, new_size, r, anchor=None):
    """한 축 좌표 c (창 안쪽 기준)를 창 크기가 old -> new 로 바뀐 뒤 위치로.
    마크 HUD 는 가까운 끝(왼/위, 가운데, 오른/아래)에 붙어 있음 -> 3등분으로 판단. r = GUI 배율 변화."""
    if anchor is None:
        anchor = "lo" if c < old_size / 3 else "hi" if c > old_size * 2 / 3 else "mid"
    if anchor == "lo":
        return c * r
    if anchor == "hi":
        return new_size - (old_size - c) * r
    return new_size / 2 + (c - old_size / 2) * r


def remap_rect(roi, old, new, r=1.0, anchor=None):
    """화면 영역 [x, y, w, h] 를 마크 창(old -> new, 둘 다 [x, y, w, h])에 맞춰 옮김."""
    x, y, w, h = roi
    cx = _remap_axis(x + w / 2 - old[0], old[2], new[2], r, anchor)
    cy = _remap_axis(y + h / 2 - old[1], old[3], new[3], r, anchor)
    nw, nh = max(1, w * r), max(1, h * r)
    return [int(round(new[0] + cx - nw / 2)), int(round(new[1] + cy - nh / 2)), int(round(nw)), int(round(nh))]


def remap_point(pt, old, new, r=1.0, anchor=None):
    return [int(round(new[0] + _remap_axis(pt[0] - old[0], old[2], new[2], r, anchor))),
            int(round(new[1] + _remap_axis(pt[1] - old[1], old[3], new[3], r, anchor)))]


def detect_gui_scale(img):
    """화면에서 마크 GUI 배율 (핫바 선택 칸 테두리 = 24 GUI 픽셀). 못 찾으면 None."""
    h, w = img.shape[:2]
    sy = int(h * 0.7)
    slot = selected_slot(img[sy:, int(w * 0.2):int(w * 0.8)])
    return max(1, round(slot[2] / 24)) if slot else None


def snap_slot(img, pt, pitch):
    """클릭한 점을 그 칸의 진짜 가운데로 맞춤 (칸 테두리를 눌렀거나 살짝 빗나가도).
    점 주변에서 칸 바탕색(가장 흔한 색) 덩어리를 찾아 그 가운데."""
    x, y = int(pt[0]), int(pt[1])
    r = max(4, int(pitch * 0.7))
    x0, y0 = max(0, x - r), max(0, y - r)
    crop = img[y0:y + r, x0:x + r]
    if crop.size == 0:
        return [x, y]
    q = (crop.astype(np.int16) // 8)
    key = q[..., 0] * 1024 + q[..., 1] * 32 + q[..., 2]
    c = key[key.shape[0] // 4: 3 * key.shape[0] // 4, key.shape[1] // 4: 3 * key.shape[1] // 4]
    vals, cnt = np.unique(c, return_counts=True)
    mode = vals[int(np.argmax(cnt))]
    m = (key == mode).astype(np.uint8)
    n, lab, st, cent = cv2.connectedComponentsWithStats(m)
    best, bd = None, 1e9
    for i in range(1, n):
        bw, bh, area = st[i, 2], st[i, 3], st[i, 4]
        if area < 0.15 * pitch * pitch or bw > 1.3 * pitch or bh > 1.3 * pitch:
            continue                                   # 칸 하나 크기쯤인 덩어리만
        cx, cy = st[i, 0] + bw / 2 + x0, st[i, 1] + bh / 2 + y0
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < bd:
            best, bd = [int(round(cx)), int(round(cy))], d
    return best if best and bd <= (0.8 * pitch) ** 2 else [x, y]


def hotbar_points(img, p1, p9):
    """핫바 1번·9번 칸 클릭 -> 9칸 가운데 전부 (같은 줄로 맞추고 칸마다 정확히 맞춤)."""
    pitch = abs(p9[0] - p1[0]) / 8
    y = (p1[1] + p9[1]) / 2                            # 1번·9번 높이가 살짝 달라도 같은 줄
    return [snap_slot(img, (p1[0] + (p9[0] - p1[0]) * k / 8, y), pitch) for k in range(9)]
