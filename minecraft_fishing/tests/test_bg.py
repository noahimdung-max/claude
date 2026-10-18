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


class RightClick(unittest.TestCase):
    """실제 v1.9.2 로그: 백그라운드 모드인데 마크가 앞에 있으면 창 메시지 우클릭을 마크(SDL)가 무시해서 안 던짐."""
    def setUp(self):
        fakes.EVENTS.clear()
        self.win = fakes.sys.modules["winapi"]

    def tearDown(self):
        self.win.is_foreground = lambda h: True

    def test_front_uses_real_click(self):
        m, _ = bg_macro()
        self.win.is_foreground = lambda h: True
        m.right_click()
        names = [e[0] for e in fakes.EVENTS]
        self.assertIn("mouseDown", names)
        self.assertNotIn("win.post_right_click", names)

    def test_behind_posts_to_window(self):
        m, _ = bg_macro()
        self.win.is_foreground = lambda h: False
        m.right_click()
        names = [e[0] for e in fakes.EVENTS]
        self.assertIn("win.post_right_click", names)
        self.assertNotIn("mouseDown", names)


class FpsWatch(unittest.TestCase):
    """실제 로그: 캡처를 다시 연 뒤 '초당 -3번 / -957번만 그려져서' 헛알림."""
    def _macro(self, frames):
        m, _ = bg_macro()
        m.screen.frames = frames
        m.said = []
        m.out = m.said.append
        return m

    def test_reopened_capture_gives_no_negative_fps(self):
        m = self._macro(1000)
        m._fps_mark = (fm.time.perf_counter() - 3, 1000, m.screen)
        new, _ = bg_macro()
        m.screen = new.screen                          # 새 캡처: 0부터 다시 셈
        m.screen.frames = 3
        m.watch_fps()
        self.assertEqual(m.said, [])
        self.assertNotIn("fps", m.stats)

    def test_really_low_fps_still_warns(self):
        m = self._macro(0)
        m._fps_mark = (fm.time.perf_counter() - 3, 0, m.screen)
        m.screen.frames = 24                           # 3초에 24번 = 초당 8번 (실제 로그의 Dynamic FPS 상황)
        m.watch_fps()
        self.assertEqual(len(m.said), 1)
        self.assertIn("초당 8번", m.said[0])


class DebugImages(unittest.TestCase):
    """실제 v1.8.1 로그: '바 못 찾음' 6번인데 그림이 하나도 안 남아서 원인을 못 봤음."""
    def test_bar_not_found_saves_picture(self):
        m, _ = bg_macro()
        fakes.SAVED.clear()
        self.assertFalse(m.find_bar(save_debug=True))   # 미니게임 없는 화면
        self.assertEqual(fakes.SAVED, ["bar_debug.png"])

    def test_file_log_snap_saves_named_picture(self):
        fakes.SAVED.clear()
        fm.FileLog.snap(None, None, "미니게임_안뜸")
        self.assertEqual(fakes.SAVED, ["snap_미니게임_안뜸.png"])


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
