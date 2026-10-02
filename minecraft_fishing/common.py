import json
from pathlib import Path

import mss
import numpy as np

CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULTS = {
    "monitor": 1,
    "bobber_roi": None,          # [x, y, w, h] 찌 주변 영역
    "bobber_color": None,        # [B, G, R] 찌 빨간 부분
    "bar_roi": None,             # [x, y, w, h] 미니게임 바 영역
    "bar_color": None,           # [B, G, R] 플레이어가 움직이는 바(커서)
    "fish_color": None,          # [B, G, R] 물고기 아이콘
    "tolerance": 30,             # 색 허용 오차(채널별)
    "min_pixels": 6,             # 검출로 인정할 최소 픽셀 수
    "cast_settle_sec": 2.0,      # 던진 뒤 찌가 자리잡을 때까지 대기
    "bite_timeout_sec": 45.0,    # 입질 안 오면 다시 던짐
    "bite_drop_ratio": 0.4,      # 찌 픽셀 수가 기준치의 이 비율 아래로 떨어지면 입질
    "bite_dip_px": 6,            # 찌 중심 y가 이만큼 내려가면 입질
    "minigame_start_timeout_sec": 2.5,
    "minigame_end_missing_sec": 0.6,
    "deadzone_px": 3,            # 바-물고기 오차 허용 범위
    "lead_sec": 0.05,            # 바 속도 기반 예측 시간
    "reel_click_after_game": False,  # 미니게임 끝나고 우클릭 한 번 더 필요하면 true
    "recast_delay_sec": 1.0,
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


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
