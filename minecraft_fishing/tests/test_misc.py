"""찌 색·리소스팩·툴팁 숫자·영역 보정·로그 분석 시험."""
import io
import json
import unittest
import zipfile

import cv2
import numpy as np
from PIL import Image

import fakes                      # noqa: F401  (가짜 화면/입력을 먼저 설치)
import analysis
import common
import fishing_macro as fm




class BobberColor(unittest.TestCase):
    def _scene(self, style, k=5, dim=1.0):
        img = np.full((300, 600, 3), (150, 150, 150), np.uint8)
        if style == "vanilla":
            cv2.rectangle(img, (300, 100), (300 + 3 * k - 1, 100 + k - 1), (240, 240, 240), -1)
            cv2.rectangle(img, (300, 100 + k), (300 + 3 * k - 1, 100 + 2 * k - 1), (42, 42, 211), -1)
            cv2.rectangle(img, (300, 100 + 2 * k), (300 + 3 * k - 1, 100 + 3 * k - 1), (240, 240, 240), -1)
        else:
            r, g, b = {"magenta": (255, 0, 255), "lime": (0, 255, 0)}[style]
            cv2.rectangle(img, (300, 100), (300 + 5 * k - 1, 100 + 3 * k - 1), (b, g, r), -1)
        return (img.astype(np.float32) * dim).astype(np.uint8)

    def test_each_style_found_even_when_dark(self):
        for style in ("vanilla", "magenta", "lime"):
            for dim in (1.0, 0.5, 0.25):
                f = common.find_bobber(self._scene(style, dim=dim), (310, 110), None, 6, 80, style)
                self.assertIsNotNone(f, f"{style} {dim}")

    def test_auto_tries_all_colors(self):
        for style in ("vanilla", "magenta", "lime"):
            self.assertIsNotNone(common.find_bobber(self._scene(style), (310, 110), None, 6, 80, "auto"), style)

    def test_object_present_before_cast_is_ignored(self):
        img = self._scene("magenta")
        ignore = np.ones(img.shape[:2], bool)
        self.assertIsNone(common.find_bobber(img, (310, 110), ignore, 6, 80, "magenta"))


class ResourcePack(unittest.TestCase):
    PATH_NEW = "assets/minecraft/textures/entity/fishing/fishing_hook.png"
    PATH_OLD = "assets/minecraft/textures/entity/fishing_hook.png"

    def test_every_pack_has_both_texture_paths(self):
        """마크 26.1 부터(26.3 도 같음) 찌 그림 위치가 entity/fishing/ 아래로 바뀜 -> 새 위치가 꼭 있어야 하고, 옛 위치도 같이"""
        for style in ("magenta", "lime"):
            for ver in common.BOBBER_PACK_VERSIONS:
                files = common.bobber_pack_files(style, ver)
                self.assertIn(self.PATH_NEW, files, (style, ver))
                self.assertIn(self.PATH_OLD, files, (style, ver))
                tex = np.array(Image.open(io.BytesIO(files[self.PATH_NEW])).convert("RGBA"))
                self.assertEqual(tex.shape[:2], (8, 8))
                self.assertEqual(int((tex[..., 3] > 0).sum()), 15 + 6)        # 머리 5x3 + 낚싯줄·바늘 6칸

    def test_version_specific_packs_use_modern_format_only(self):
        """마크 26.x 가 직접 쓰는 팩처럼 pack_format 없이 min_format/max_format 만 (26.1.2 = 84, 26.3 = 97)"""
        for ver, (lo, hi) in (("26.1.2", (84, 87)), ("26.3", (97, 99))):
            meta = json.loads(common.bobber_pack_files("magenta", ver)["pack.mcmeta"].decode("utf-8"))["pack"]
            self.assertEqual((meta["min_format"], meta["max_format"]), (lo, hi))
            self.assertNotIn("pack_format", meta)
            self.assertNotIn("supported_formats", meta)
            self.assertIn(ver, meta["description"])
        self.assertTrue(84 <= 84 <= 87 and 97 <= 97 <= 99)                    # 26.1.2(84.0) / 26.3(97.1) 이 각 범위 안

    def test_all_versions_pack_keeps_old_and_new_fields(self):
        meta = json.loads(common.bobber_pack_files("lime", "all")["pack.mcmeta"].decode("utf-8"))["pack"]
        for k in ("pack_format", "supported_formats", "min_format", "max_format"):
            self.assertIn(k, meta)

    def test_zip_names_and_validity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for ver in common.BOBBER_PACK_VERSIONS:
                p = common.write_bobber_pack(d, "magenta", ver)
                self.assertIsNone(zipfile.ZipFile(p).testzip())
                self.assertEqual(p.name, f"MacroBobber_magenta_{ver}.zip")


class TooltipDigits(unittest.TestCase):
    """실제 서버: '내구도 63/64' 숫자가 초록색이었음 (예전엔 흰색만 읽어서 못 읽었음)"""

    @staticmethod
    def _text(img, text, x, y, s, color):
        cx = x
        for ch in text:
            if ch in common.GLYPHS:
                bm = common.GLYPHS[ch].astype(np.uint8)
                adv = 6
            else:
                bm = np.zeros((7, 4), np.uint8)
                bm[1:6, 1:3] = 1
                adv = 5
            big = np.kron(bm, np.ones((s, s), np.uint8)).astype(bool)
            h, w = big.shape
            for dx, dy, col in ((s, s, tuple(int(c) // 4 for c in color)), (0, 0, color)):
                reg = img[y + dy:y + dy + h, cx + dx:cx + dx + w]
                reg[big[:reg.shape[0], :reg.shape[1]]] = col
            cx += adv * s
        return cx

    def _tooltip(self, color, text="63/64"):
        img = np.full((900, 1400, 3), (30, 30, 30), np.uint8)
        x0, y0 = 600, 300
        img[y0:y0 + 200, x0:x0 + 230] = (16, 0, 16)
        cv2.rectangle(img, (x0, y0), (x0 + 229, y0 + 199), (160, 20, 90), 2)
        self._text(img, "name", x0 + 8, y0 + 10, 2, (255, 255, 85))
        cx = self._text(img, "ab ", x0 + 8, y0 + 60, 2, (255, 255, 255))
        self._text(img, text, cx, y0 + 60, 2, color)
        return img

    def test_reads_every_text_color(self):
        for name, col in (("흰", (255, 255, 255)), ("초록", (85, 255, 85)), ("노랑", (85, 255, 255)), ("빨강", (85, 85, 255)),
                          ("진한 빨강", (0, 0, 170))):
            self.assertEqual(common.read_tooltip_durability(self._tooltip(col)), (63, 64), name)

    def test_other_values(self):
        for t, want in (("1/64", (1, 64)), ("12/64", (12, 64)), ("64/64", (64, 64)), ("250/250", (250, 250))):
            self.assertEqual(common.read_tooltip_durability(self._tooltip((85, 255, 85), t)), want, t)


class RoiSafety(unittest.TestCase):
    def test_bounds(self):
        self.assertTrue(common.roi_in_bounds([10, 10, 50, 20], 2560, 1440))
        self.assertFalse(common.roi_in_bounds([-977, -46, 81, 23], 2560, 1440))      # 실제로 저장돼 있던 화면 밖 골드 영역
        self.assertFalse(common.roi_in_bounds([2500, 10, 100, 20], 2560, 1440))
        self.assertFalse(common.roi_in_bounds([10, 10, 0, 20], 2560, 1440))
        self.assertFalse(common.roi_in_bounds(None, 2560, 1440))

    def test_remap_keeps_hud_anchored(self):
        old, new = [0, 0, 1920, 1080], [0, 0, 1280, 720]
        r = common.remap_rect([1500, 850, 300, 40], old, new)               # 오른쪽 아래 자막: 아래/오른쪽 끝 기준
        self.assertEqual((r[0] + r[2] // 2, r[1] + r[3] // 2), (1280 - (1920 - 1650), 720 - (1080 - 870)))

    def test_sanitize_clears_out_of_screen_roi(self):
        sc = fakes.Scene()
        m = fakes.make_macro(sc, gold_roi=[-977, -46, 81, 23], bite_mode="subtitle", subtitle_roi=[100, 100, 100, 20])
        m.sub_tmpl = np.zeros((6, 30), np.uint8)
        m.sanitize_rois()
        self.assertIsNone(m.cfg["gold_roi"])
        self.assertEqual(m.cfg["subtitle_roi"], [100, 100, 100, 20])


class LogAnalysis(unittest.TestCase):
    @staticmethod
    def _log(cycles):
        """cycles: [(종류, 사유)] 종류 caught/false. 한 번에 입질 대기 10초, 미니게임 4초, 헛챔질은 4초 기다림"""
        lines, t = [], 0.0

        def add(tag, msg, lvl="INFO"):
            h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
            lines.append(f"{h:02d}:{m:02d}:{s:06.3f} [{lvl}] {tag:6} {msg}")
        add("INFO", "[시작] 마크 창으로 전환해서 시작")
        for kind, why in cycles:
            t += 1.2
            add("BITE", "입질 대기 시작: 모드=bobber (설정 bobber)", "DEBUG")
            t += 10
            add("BITE", f"결과=입질 모드=bobber 사유={why} 예전판정도반응=예 자막최고=-", "DEBUG")
            if kind == "caught":
                t += 0.2
                add("INFO", "미니게임 시작 (초록 물고기)")
                t += 4.4
                add("INFO", "미니게임 끝 (총 1회, 4.4초, 초당 95번 확인)")
            else:
                t += 4.1
                add("INFO", "미니게임 안 뜸 (헛챔질이었거나, 바 위치가 틀렸으면 '자동'으로 다시 찾기)")
        return "\n".join(lines)

    def test_counts_and_times(self):
        text = self._log([("caught", "픽셀감소")] * 6 + [("false", "가라앉음(속도)")] * 3 + [("caught", "픽셀감소")])
        s = analysis.summarize(analysis.parse_text(text))
        self.assertEqual((s["done"], s["caught"], s["false"]), (10, 7, 3))
        self.assertAlmostEqual(s["wait"]["mean"], 10.0, places=1)
        self.assertAlmostEqual(s["mg"]["mean"], 4.4, places=1)
        self.assertAlmostEqual(s["lost"], 3 * (10 + 4.1), places=0)

    def test_advice_names_the_cause(self):
        text = self._log([("caught", "픽셀감소")] * 6 + [("false", "가라앉음(속도)")] * 4)
        rep = analysis.report(analysis.parse_text(text))
        self.assertIn("헛챔질", rep)
        self.assertIn("속도 규칙", rep)
        self.assertIn("v1.6.6", rep)

    def test_clean_run_has_no_complaints(self):
        rep = analysis.report(analysis.parse_text(self._log([("caught", "픽셀감소")] * 10)))
        self.assertIn("눈에 띄는 문제 없음", rep)

    def test_memory_log_feeds_analysis(self):
        fm.MEMLOG.clear()
        log = fm.NullLog()
        log.write("BITE", "입질 대기 시작: 모드=bobber (설정 bobber)")
        self.assertEqual(len(fm.MEMLOG), 1)
        log.write("GAME", "프레임")                              # 프레임별 기록은 메모리에도 안 남김
        self.assertEqual(len(fm.MEMLOG), 1)


if __name__ == "__main__":
    unittest.main()
