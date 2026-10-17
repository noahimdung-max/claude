"""새 화면(webapp): 매크로 상태 -> 캐릭터 애니메이션, 화면으로 보내는 값, 설정 저장, 영역 지정 좌표."""
import json
import types
import unittest

import fakes
import common
import webapp


class Stub:
    def __init__(self, running, state):
        self.running, self.state = running, state


class AnimKey(unittest.TestCase):
    def test_states(self):
        cases = [(False, "던지는 중", False, "idle"), (True, "던지는 중", False, "cast"),
                 (True, "찌 자리잡는 중", False, "wait"), (True, "입질 기다리는 중 (찌 + 자막)", False, "wait"),
                 (True, "입질 기다리는 중 (자막)", False, "wait"), (True, "미니게임 기다리는 중", False, "bite"),
                 (True, "미니게임 중", False, "reel"), (True, "다시 던지기 대기", True, "caught"),
                 (True, "인벤 확인 중", False, "idle"), (True, "마크 창이 앞에 없어서 일시정지", False, "idle")]
        for running, state, recent, want in cases:
            self.assertEqual(webapp.anim_key(Stub(running, state), recent), want, state)
        self.assertEqual(webapp.anim_key(None, False), "idle")


class App(unittest.TestCase):
    def setUp(self):
        self.saved = []
        webapp.save_config = lambda c: self.saved.append(dict(c))
        self.pushed = []
        self.app = webapp.WebApp.__new__(webapp.WebApp)
        webapp.WebApp.__init__(self.app)
        self.app.cfg = dict(common.DEFAULTS)
        self.app.push = lambda kind, data=None: self.pushed.append((kind, data))

    def test_snapshot_is_json(self):
        a = self.app
        a.macro = fakes.make_macro(fakes.Scene())
        a.cfg = a.macro.cfg
        a.cfg["bar_roi"] = [100, 900, 371, 16]
        a.macro.stats["dura"], a.macro.stats["dura_max"] = (12, "exact"), 64
        a.macro.stats["colors"] = {"파랑": 3}
        a.macro.stats["casts"], a.macro.stats["caught"] = 4, 3
        a.macro.run_caught = 3
        s = a.snapshot()
        json.dumps(s, ensure_ascii=False)
        self.assertEqual(s["caught"], 3)
        self.assertEqual(s["rate"], 75)
        self.assertTrue(s["dura"]["danger"])                    # 12/64 < 20%
        self.assertTrue(s["bar"]["roi"])
        a.macro.stats["caught"] += 1                              # 한 마리 더 -> 잠깐 '낚음' 애니메이션
        self.assertEqual(a.snapshot()["anim"], "caught")
        json.dumps(a.rod_data(), ensure_ascii=False)

    def test_public_cfg_and_status_are_json(self):
        json.dumps(self.app.public_cfg(), ensure_ascii=False)
        st = self.app.status()
        self.assertEqual(set(st), {"subtitle", "bobber", "rod", "bar"})

    def test_set_cfg(self):
        a = self.app
        self.assertTrue(a.set_cfg("goal_count", "120"))
        self.assertEqual(a.cfg["goal_count"], 120)
        self.assertFalse(a.set_cfg("goal_count", ""))            # 입력 중 빈칸은 무시
        self.assertFalse(a.set_cfg("durability_stop_pct", 150))  # 범위 밖
        self.assertEqual(a.cfg["durability_stop_pct"], common.DEFAULTS["durability_stop_pct"])
        self.assertTrue(a.set_cfg("background", 1))
        self.assertIs(a.cfg["background"], True)
        self.assertFalse(a.set_cfg("bite_mode", "nope"))
        self.assertTrue(a.set_cfg("bite_mode", "subtitle"))
        self.assertFalse(a.set_cfg("discord_webhook", "x"))      # 웹후크는 save_hook 으로만
        self.assertTrue(self.saved)

    def test_save_adv(self):
        a = self.app
        vals = {k: str(common.DEFAULTS[k]) for k in webapp.ADV_KEYS}
        vals["max_fails"] = "7"
        vals["lead_sec"] = "0.1"
        self.assertTrue(a.save_adv(dict(vals, sneak_key="ctrl", log_file=True, reel_click_after_game=False)))
        self.assertEqual(a.cfg["max_fails"], 7)
        self.assertIsInstance(a.cfg["max_fails"], int)
        self.assertAlmostEqual(a.cfg["lead_sec"], 0.1)
        self.assertEqual(a.cfg["sneak_key"], "ctrl")
        self.assertFalse(a.save_adv(dict(vals, max_fails="abc")))

    def test_ask_coordinates(self):
        """화면은 원래 그림 좌표로 돌려줌 -> 그림 밖으로 나가지 않게 자름 (tk PickDialog 와 같은 결과)."""
        import numpy as np
        a = self.app
        img = np.zeros((1080, 1920, 3), np.uint8)
        a._wait = lambda kind, data: [1900, 1000, 100, 200]
        self.assertEqual(a.ask(img, "g"), [1900, 1000, 20, 80])
        a._wait = lambda kind, data: [5, 6]
        self.assertEqual(a.ask(img, "g", mode="point"), (5, 6))
        a._wait = lambda kind, data: True
        self.assertTrue(a.ask(img, "g", mode="view"))
        a._wait = lambda kind, data: False
        self.assertFalse(a.ask(img, "g", mode="view"))            # 다시 하기
        a._wait = lambda kind, data: None
        self.assertIsNone(a.ask(img, "g"))                         # 취소

    def test_wait_answer(self):
        import threading
        a = self.app
        a.push = lambda kind, data=None: threading.Timer(0.05, a.answer, (data["token"], [1, 2, 3, 4])).start()
        self.assertEqual(a._wait("pick", {}), [1, 2, 3, 4])

    def test_bridge_hides_app(self):
        """pywebview 는 js_api 의 공개 속성을 화면에 내보냄 -> 앱 객체(설정·웹후크)는 숨겨야 함."""
        b = webapp.Bridge(self.app)
        public = [n for n in vars(b) if not n.startswith("_")]
        self.assertEqual(public, [])
        for n in dir(b):
            if not n.startswith("_"):
                self.assertIsInstance(getattr(b, n), types.MethodType, n)


if __name__ == "__main__":
    unittest.main()
