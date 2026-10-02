import json
from pathlib import Path

import cv2
import mss
import numpy as np

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
SUBTITLE_PATH = HERE / "subtitle.png"

DEFAULTS = {
    "monitor": 1,
    "bite_mode": "subtitle",     # subtitle = 자막 '낚시찌 첨벙' 감지(추천) / bobber = 찌 화면 감시(예비)
    "subtitle_roi": None,        # [x, y, w, h] 자막을 찾을 영역 (자막 지정 시 자동 계산)
    "subtitle_threshold": 0.8,   # 자막 글자 일치도 기준 (0~1)
    "bite_confirm_frames": 2,    # 연속 몇 번 감지돼야 입질로 볼지
    "bobber_roi": None,          # [x, y, w, h] 찌가 떨어질 수 있는 물 영역 (찌 모드)
    "bobber_color": None,        # [B, G, R] 찌 빨간 부분
    "bar_roi": None,             # [x, y, w, h] 미니게임 바 영역. 비워두면 첫 미니게임 때 자동 탐색 후 저장
    "bar_search_roi": None,      # 자동 탐색 범위. 비워두면 화면 아래쪽 가운데
    "bar_color": [226, 196, 145],    # [B, G, R] 잡는 구간 양쪽 괄호 ( ) 하늘색
    "fish_color": [115, 227, 109],   # [B, G, R] 물고기 연두색
    "gauge_roi": None,           # [x, y, w, h] 바 위 원형 게이지 (선택: 가득 찼는지 판정용)
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
    "bite_drop_ratio": 0.5,      # (찌 모드) 찌 픽셀 수가 기준치의 이 비율 아래로 떨어지면 입질
    "bite_dip_px": 4,            # (찌 모드) 찌가 최소 이만큼 내려가야 입질 (흔들림이 크면 자동으로 더 크게)
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


def bobber_mask(img, cfg):
    """찌 빨간 부분. 지정 색 근처 + 진한 빨강 규칙 (주황 랜턴 등은 제외)."""
    b, g, r = _bgr(img)
    rule = (r > 130) & (r > g + 90) & (r > b + 90) & (g < 110)
    if cfg["bobber_color"]:
        rule |= color_mask(img, cfg["bobber_color"], cfg["tolerance"])
    return rule


def fish_mask(img, cfg):
    """밝은 연두 (미니게임 물고기, 원형 게이지)."""
    b, g, r = _bgr(img)
    rule = (g > 150) & (g > r + 60) & (g > b + 50)
    return rule | color_mask(img, cfg["fish_color"], cfg["tolerance"])


def bracket_mask(img, cfg):
    """잡는 구간 괄호 ( ) 하늘색."""
    b, g, r = _bgr(img)
    rule = (b > 170) & (g > 140) & (r > 80) & (b > r + 40) & (b - g >= 10) & (b - g <= 80)
    return rule | color_mask(img, cfg["bar_color"], cfg["bar_tolerance"])


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


def fish_blob_x(bar, cfg):
    """바 안에서 가장 큰 연두 덩어리(물고기)의 가운데 x. 너무 길쭉한 띠는 물고기가 아님."""
    m = fish_mask(bar, cfg).astype(np.uint8)
    n, _, st, cent = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    if st[i, cv2.CC_STAT_AREA] < cfg["min_pixels"] or st[i, cv2.CC_STAT_WIDTH] > 4 * bar.shape[0]:
        return None
    return float(cent[i][0])


def gauge_present(above, cfg):
    """바 위 가운데에 초록 원형 게이지가 있는지. 평소 화면(경험치 숫자)엔 없음."""
    return int(fish_mask(above, cfg).sum()) >= 10


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
    """화면에서 미니게임 바 위치 자동 탐색. 물고기와 괄호가 같은 줄에 있고, 그 위 가운데에 게이지가 있는 곳.
    반환: img 기준 [x, y, w, h] 또는 None."""
    fish = fish_mask(img, cfg)
    br = bracket_mask(img, cfg)
    rows = np.nonzero((fish.sum(axis=1) >= 2) & (br.sum(axis=1) >= 1))[0]
    groups = runs(rows, 1)
    if not groups:
        return None
    y0, y1 = max(groups, key=lambda g: g[1] - g[0])
    band = img[y0:y1 + 1].astype(np.int16)
    b, r = band[..., 0], band[..., 2]
    track = ((b > r + 40) & (b > 40)) | fish[y0:y1 + 1] | br[y0:y1 + 1]
    good = track.mean(axis=0) >= 0.5

    # 마크 HUD는 화면 가운데 정렬 -> 가운데에서 양쪽으로 바 끝까지 넓혀감
    H, W = img.shape[:2]
    cx = W // 2
    gap = max(3, 2 * (y1 - y0 + 1))

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
        return None
    half = max(cx - left, right - cx)
    if 2 * half < 10 * (y1 - y0 + 1):
        return None
    pad = 3
    x0, x1 = max(0, cx - half - pad), min(W - 1, cx + half + pad)
    yy0, yy1 = max(0, y0 - pad), min(H - 1, y1 + pad)
    roi = [x0, yy0, x1 - x0 + 1, yy1 - yy0 + 1]

    # 검증: 얇은 괄호가 있고, 바 위 가운데에 게이지가 있어야 함
    vr, bar_row = view_roi(roi)
    vx, vy, vw, vh = vr
    bar_img, above = split_view(img[vy:vy + vh, vx:vx + vw], bar_row)
    if not bracket_runs(bar_img, cfg) or not gauge_present(above, cfg):
        return None
    return roi


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


def match_score(img, tmpl):
    """img(BGR) 안에서 자막 템플릿(흰 글자)과 가장 비슷한 곳의 일치도 (0~1)."""
    g = text_binary(to_gray(img))
    th, tw = tmpl.shape[:2]
    if g.shape[0] < th or g.shape[1] < tw:
        return 0.0
    res = cv2.matchTemplate(g, tmpl, cv2.TM_CCOEFF_NORMED)
    return float(np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0).max())
