"""마크 창 고르기: 제목에 Minecraft 가 없는 클라이언트(루나 등)에서 크롬 탭·디스코드를 고르던 문제.
(백그라운드 모드는 고른 창에만 우클릭을 보내서, 엉뚱한 창을 고르면 아예 안 던졌음)"""
import importlib.util
import unittest
from pathlib import Path

# fakes 가 sys.modules['winapi'] 를 가짜로 바꿔 두므로 진짜 파일을 따로 불러옴
_spec = importlib.util.spec_from_file_location("winapi_real", Path(__file__).resolve().parent.parent / "winapi.py")
winapi_real = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(winapi_real)
pick = winapi_real.pick_game_window


class PickWindow(unittest.TestCase):
    def test_minecraft_26_sdl_window(self):
        """실제 26.3 창: 종류가 GLFW 가 아니라 SDL_app (v1.9.1 이 이걸 못 찾았음)."""
        cands = [("Minecraft* 26.3 - 멀티플레이 (제3자 서버)", "SDL_app", "javaw.exe", 2560 * 1369, 3),
                 ("Minecraft 위키 - Chrome", "Chrome_WidgetWin_1", "chrome.exe", 1920 * 1000, 4)]
        self.assertEqual(pick(cands), 3)

    def test_java_window_unknown_class(self):
        """창 종류가 처음 보는 것이어도 자바로 돌면 후보."""
        self.assertEqual(pick([("Minecraft 27.1", "NewToolkitWnd", "javaw.exe", 800 * 600, 6)]), 6)

    def test_lunar_without_minecraft_title(self):
        cands = [("Lunar Client 1.21.4 (v2.18)", "GLFW30", "javaw.exe", 2560 * 1369, 1)]
        self.assertEqual(pick(cands), 1)

    def test_browser_tab_never_picked(self):
        """제목에 Minecraft 가 있어도 게임 창 종류가 아니면 안 고름 (예전엔 이게 골라졌음)."""
        cands = [("Minecraft 낚시 - YouTube - Chrome", "Chrome_WidgetWin_1", "chrome.exe", 1920 * 1000, 7),
                 ("#minecraft - Discord", "Chrome_WidgetWin_1", "Discord.exe", 1200 * 800, 8)]
        self.assertIsNone(pick(cands))
        cands.append(("Feather Client", "GLFW30", "javaw.exe", 854 * 480, 9))
        self.assertEqual(pick(cands), 9)

    def test_vanilla_preferred(self):
        cands = [("Some GLFW tool", "GLFW30", "tool.exe", 3000 * 2000, 1),
                 ("Minecraft* 26.3 - 멀티플레이 (서드파티 서버)", "GLFW30", "javaw.exe", 854 * 480, 2)]
        self.assertEqual(pick(cands), 2)

    def test_launcher_skipped(self):
        cands = [("Minecraft Launcher", "GLFW30", "Minecraft.exe", 1000 * 700, 1),
                 ("Minecraft 1.21.4", "GLFW30", "javaw.exe", 800 * 600, 2)]
        self.assertEqual(pick(cands), 2)

    def test_old_lwjgl(self):
        self.assertEqual(pick([("Minecraft 1.8.9", "LWJGL", "javaw.exe", 854 * 480, 5)]), 5)

    def test_none(self):
        self.assertIsNone(pick([]))


if __name__ == "__main__":
    unittest.main()
