"""백그라운드 모드(다른 창 쓰면서 낚시) 시험: 창 이동·크기 변화·캡처 끊김·일시정지 메뉴."""
import tempfile
import unittest
from pathlib import Path


import fakes
import common
import fishing_macro as fm

W, H = fakes.W, fakes.H


class BgScreen(fakes.FakeScreen):
    """WGCScreen 처럼 refresh_geom/stalled 가 있는 가짜 화면."""
    def __init__(self, scene):
        super().__init__(scene)
        self.refreshed, self.dead = 0, False

    def refresh_geom(self):
        self.refreshed += 1

    def stalled(self, sec=3.0):
        return self.dead


def bg_macro(**over):
    sc = fakes.Scene()
    m = fakes.make_macro(sc, background=True, ref_client=[0, 0, W, H], **over)
    m.screen = BgScreen(sc)
    m.bg_mode = True
    m.setups = []
    m.setup_io = lambda reopen=False: m.setups.append(reopen)
    return m, sc


class BgWindow(unittest.TestCase):
    def tearDown(self):
        fakes.sys.modules["winapi"].rect[:] = [0, 0, W, H]

    def test_move_only_keeps_capture_open(self):
        m, _ = bg_macro()
        fakes.sys.modules["winapi"].rect[:] = [40, 30, W, H]        # 창만 옮김
        m.bg_upkeep()
        self.assertEqual(m.setups, [])
        self.assertEqual(m.screen.refreshed, 1)
        self.assertEqual(m.cfg["ref_client"], [40, 30, W, H])        # 기준도 새 위치로

    def test_resize_reopens_capture(self):
        m, _ = bg_macro()
        fakes.sys.modules["winapi"].rect[:] = [0, 0, 1280, 720]
        m.bg_upkeep()
        self.assertEqual(m.setups, [True])

    def test_unfixable_change_is_not_retried_every_cycle(self):
        m, _ = bg_macro()
        fakes.sys.modules["winapi"].rect[:] = [0, 0, 1280, 720]     # setup_io 가 가짜라 기준이 안 바뀜
        for _ in range(5):
            m.bg_upkeep()
        self.assertEqual(m.setups, [True])

    def test_stalled_capture_is_reopened_once(self):
        m, _ = bg_macro()
        m.screen.dead = True
        for _ in range(3):
            m.bg_upkeep()
        self.assertEqual(m.setups, [True])


class PauseMenu(unittest.TestCase):
    def setUp(self):
        fakes.EVENTS.clear()

    def test_menu_closed_before_cast(self):
        m, sc = bg_macro()
        m.bg_guard()                                    # 첫 판: 정상 화면 기준 저장
        self.assertIsNotNone(m.game_ref)
        sc.dim = 0.3                                    # 일시정지 메뉴가 뜸
        m.press = lambda k: (fakes.EVENTS.append(("press", k)), setattr(sc, "dim", 1.0))
        m.bg_guard()
        self.assertIn(("press", "esc"), fakes.EVENTS)

    def test_stops_when_menu_keeps_coming_back(self):
        m, sc = bg_macro()
        m.bg_guard()
        sc.dim = 0.3
        m.press = lambda k: None                        # ESC 가 안 먹음 / 다시 뜸
        with self.assertRaises(fm.Stop):
            m.bg_guard()
        self.assertTrue(any(e[0] == "alert" and "F3+P" in e[1] for e in fakes.EVENTS))

    def test_normal_scene_untouched(self):
        m, sc = bg_macro()
        m.bg_guard()
        m.press = lambda k: fakes.EVENTS.append(("press", k))
        for _ in range(3):
            m.bg_guard()
        self.assertEqual([e for e in fakes.EVENTS if e[0] == "press"], [])

    def test_not_used_in_normal_mode(self):
        m, sc = bg_macro()
        m.bg_mode = False
        m.bg_guard()
        self.assertIsNone(getattr(m, "game_ref", None))


class OptionsTxt(unittest.TestCase):
    def _read(self, text):
        with tempfile.TemporaryDirectory() as d:
            if text is not None:
                (Path(d) / "options.txt").write_text(text, encoding="utf-8")
            return common.pause_on_blur_setting([d])

    def test_values(self):
        self.assertTrue(self._read("version:3955\npauseOnLostFocus:true\n"))
        self.assertFalse(self._read("pauseOnLostFocus:false\n"))
        self.assertIsNone(self._read("version:1\n"))
        self.assertIsNone(self._read(None))


if __name__ == "__main__":
    unittest.main()
