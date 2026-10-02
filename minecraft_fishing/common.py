import json
from pathlib import Path

import mss
import numpy as np

CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULTS = {
    "monitor": 1,
    "bobber_roi": None,          # [x, y, w, h] 찌 주변 영역
    "bobber_color": None,        # [B, G, R] 찌 빨간 부분
    "bar_roi": None,             # [x, y, w, h] 미니게임 바 영역. 비워두면 첫 미니게임 때 자동 탐색 후 저장
    "bar_search_roi": None,      # 자동 탐색 범위. 비워두면 화면 아래쪽 가운데
    "bar_color": [226, 196, 145],    # [B, G, R] 잡는 구간 양쪽 괄호 ( ) 하늘색
    "fish_color": [115, 227, 109],   # [B, G, R] 물고기 연두색
    "gauge_roi": None,           # [x, y, w, h] 바 위 원형 게이지
    "gauge_color": [104, 217, 139],  # [B, G, R] 게이지 채워진 테두리 밝은 초록
    "gauge_full_pixels": 80,     # 게이지 가득 찼을 때 픽셀 수(캘리브레이션 시 자동 측정)
    "gauge_full_ratio": 0.95,
    "durability_roi": None,      # [x, y, w, h] 핫바 낚싯대 칸의 내구도 줄만
    "durability_red_hue": 15,    # 내구도 바 색상(hue, 도) 이하면 빨강으로 판단
    "tolerance": 30,             # 색 허용 오차(채널별)
    "bar_tolerance": 45,         # 괄호는 픽셀마다 밝기 차이가 커서 넉넉히
    "gauge_tolerance": 20,
    "min_pixels": 6,             # 검출로 인정할 최소 픽셀 수
    "cast_settle_sec": 2.0,      # 던진 뒤 찌가 자리잡을 때까지 대기
    "bite_timeout_sec": 45.0,    # 입질 안 오면 다시 던짐
    "bite_drop_ratio": 0.5,      # 찌 픽셀 수가 기준치의 이 비율 아래로 떨어지면 입질
    "bite_dip_px": 3,            # 찌 중심 y가 이만큼 내려가면 입질
    "minigame_start_timeout_sec": 4.0,
    "minigame_end_missing_sec": 0.6,
    "deadzone_px": 3,            # 바-물고기 오차 허용 범위
    "lead_sec": 0.05,            # 바 속도 기반 예측 시간
    "reel_click_after_game": False,  # 미니게임 끝나고 우클릭 한 번 더 필요하면 true
    "recast_delay_sec": 1.0,
    "start_delay_sec": 3.0,      # F8 누른 뒤 게임 창 클릭할 시간
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def durability_hue(img):
    """내구도 바 색의 hue(0~360). 바가 안 보이면(내구도 가득) None."""
    f = img.astype(np.float32)
    mx, mn = f.max(axis=2), f.min(axis=2)
    m = (mx > 150) & (mx - mn > 80)
    if m.sum() < 3:
        return None
    b, g, r = (f[..., i][m].mean() for i in range(3))
    hi, lo = max(r, g, b), min(r, g, b)
    d = hi - lo
    if hi == r:
        h = 60 * (((g - b) / d) % 6)
    elif hi == g:
        h = 60 * ((b - r) / d + 2)
    else:
        h = 60 * ((r - g) / d + 4)
    return float(h)


def color_mask(img, color, tol):
    diff = np.abs(img.astype(np.int16) - np.array(color, dtype=np.int16))
    return np.all(diff <= tol, axis=2)


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


def bobber_mask(img, cfg):
    """찌 빨간 부분. 지정 색 근처 + 진한 빨강 규칙 (주황 랜턴 등은 제외)."""
    f = img.astype(np.int16)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    rule = (r > 130) & (r > g + 90) & (r > b + 90) & (g < 110)
    return rule | color_mask(img, cfg["bobber_color"], cfg["tolerance"])


def fish_mask(img, cfg):
    """물고기(밝은 연두). 지정 색 근처 + 색 규칙 둘 다 허용 (화면마다 색이 조금 달라도 잡히게)."""
    f = img.astype(np.int16)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    rule = (g > 150) & (g > r + 60) & (g > b + 50)
    return rule | color_mask(img, cfg["fish_color"], cfg["tolerance"])


def bracket_mask(img, cfg):
    """잡는 구간 괄호 ( ) 하늘색."""
    f = img.astype(np.int16)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    rule = (b > 170) & (g > 140) & (r > 80) & (b > r + 40) & (b - g >= 10) & (b - g <= 80)
    return rule | color_mask(img, cfg["bar_color"], cfg["bar_tolerance"])


def _longest_run(idx, max_gap):
    if idx.size == 0:
        return None
    groups = np.split(idx, np.nonzero(np.diff(idx) > max_gap)[0] + 1)
    g = max(groups, key=lambda a: a[-1] - a[0])
    return int(g[0]), int(g[-1])


def locate_bar(img, cfg):
    """화면에서 미니게임 바 위치 자동 탐색. 물고기와 괄호가 같은 줄에 있는 곳을 찾음.
    반환: img 기준 [x, y, w, h] 또는 None."""
    fish = fish_mask(img, cfg)
    br = bracket_mask(img, cfg)
    rows = np.nonzero((fish.sum(axis=1) >= 2) & (br.sum(axis=1) >= 1))[0]
    yr = _longest_run(rows, 1)
    if yr is None:
        return None
    y0, y1 = yr
    band = img[y0:y1 + 1].astype(np.int16)
    b, r = band[..., 0], band[..., 2]
    track = ((b > r + 40) & (b > 40)) | fish[y0:y1 + 1] | br[y0:y1 + 1]
    good = track.mean(axis=0) >= 0.5

    # 마크 HUD는 화면 가운데 정렬 -> 가운데에서 양쪽으로 바 끝까지 넓혀감
    w = img.shape[1]
    cx = w // 2
    gap = max(3, 2 * (y1 - y0 + 1))

    def reach(step):
        last, miss, x = None, 0, cx
        while 0 <= x < w:
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
        return None
    half = max(cx - left, right - cx)
    if 2 * half < 10 * (y1 - y0 + 1):
        return None
    x0, x1 = max(0, cx - half), min(w - 1, cx + half)
    pad = 3
    h, w = img.shape[:2]
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    return [x0, y0, x1 - x0 + 1, y1 - y0 + 1]
