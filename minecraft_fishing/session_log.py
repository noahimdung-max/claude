"""문제 분석용 기록. logs 폴더에 실행할 때마다 로그 파일 + 이상할 때 화면 캡처를 남김.
'로그 보내기용 압축'을 누르면 이번 기록을 zip 하나로 묶어줌."""
import json
import threading
import time
import zipfile
from pathlib import Path

import numpy as np

LOG_DIR = Path(__file__).with_name("logs")
KEEP_SESSIONS = 10
MAX_SNAPS = 150


class SessionLog:
    def __init__(self):
        LOG_DIR.mkdir(exist_ok=True)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"session_{self.stamp}.log"
        self.f = open(self.path, "a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()
        self.snaps = []
        self._cleanup()

    def _cleanup(self):
        """오래된 기록 지우기 (최근 KEEP_SESSIONS 번만 남김)."""
        sessions = sorted(LOG_DIR.glob("session_*.log"))
        for old in sessions[:-KEEP_SESSIONS]:
            stamp = old.stem[len("session_"):]
            for p in LOG_DIR.glob(f"snap_{stamp}_*.png"):
                p.unlink(missing_ok=True)
            old.unlink(missing_ok=True)

    def write(self, level, msg):
        t = time.time()
        line = f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t * 1000) % 1000:03d} [{level}] {msg}\n"
        with self.lock:
            try:
                self.f.write(line)
            except ValueError:          # 닫힌 뒤
                pass

    def config(self, cfg):
        self.write("CONFIG", json.dumps(cfg, ensure_ascii=False))

    def snap(self, img, tag):
        """이상할 때 화면 일부 저장 (BGR)."""
        if img is None or len(self.snaps) >= MAX_SNAPS:
            return
        from PIL import Image
        name = f"snap_{self.stamp}_{len(self.snaps) + 1:03d}_{tag}.png"
        try:
            Image.fromarray(np.ascontiguousarray(img[:, :, ::-1])).save(LOG_DIR / name)
        except Exception as e:
            self.write("ERROR", f"캡처 저장 실패 {name}: {e}")
            return
        self.snaps.append(name)
        self.write("SNAP", name)

    def pack(self, extra=()):
        """이번 기록(로그+캡처+설정)을 zip 하나로. 반환: zip 경로"""
        out = LOG_DIR / f"보내기_{self.stamp}.zip"
        with self.lock:
            self.f.flush()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(self.path, self.path.name)
            for name in self.snaps:
                p = LOG_DIR / name
                if p.exists():
                    z.write(p, name)
            for p in extra:
                p = Path(p)
                if p.exists():
                    z.write(p, p.name)
        return out

    def close(self):
        with self.lock:
            self.f.close()
