"""찌 인식·입질 판정 시험 (가짜 화면). 실제 로그에서 찾은 문제를 다시 안 만들려고 넣은 것들 포함."""
import random
import unittest

from fakes import Scene, run_bite


class BiteJudgement(unittest.TestCase):
    def setUp(self):
        self.sc = Scene()

    def test_vanishing_bobber_is_a_bite_vanilla(self):
        self.assertTrue(run_bite(self.sc, "bite", "vanilla")[0])

    def test_vanishing_bobber_is_a_bite_neon(self):
        for style in ("magenta", "lime"):
            self.sc.style = style
            self.assertTrue(run_bite(self.sc, "bite", style)[0], style)

    def test_auto_style_finds_any_color(self):
        for style in ("vanilla", "magenta", "lime"):
            self.sc.style = style
            self.assertTrue(run_bite(self.sc, "bite", "auto")[0], style)

    def test_dark_scene_is_still_found(self):
        self.sc.dim = 0.35
        self.assertTrue(run_bite(self.sc, "bite", "vanilla")[0])

    @staticmethod
    def _jitter(t):
        """평소 찌의 잔떨림 (±1px)"""
        return random.Random(int(t * 30)).uniform(-1.0, 1.0)

    @classmethod
    def _twitch(cls, amp, hold, t0=2.6, up=0.12, down=0.2):
        """평소엔 잔떨림만 있다가 갑자기 amp px 움찔 (hold 초 머물렀다가 돌아옴)"""
        def f(t):
            u = t - t0
            if u < 0:
                return cls._jitter(t)
            if u < up:
                return cls._jitter(t) + amp * u / up
            if u < up + hold:
                return cls._jitter(t) + amp
            if u < up + hold + down:
                return cls._jitter(t) + amp * (1 - (u - up - hold) / down)
            return cls._jitter(t)
        return f

    def test_real_world_twitch_is_not_a_bite(self):
        """올려준 실제 로그: 찌가 갑자기 7~15px 움찔했다 돌아오는 걸 입질로 본 17번이 전부 헛챔질이었음 (진짜 입질은 찌가 물에 잠겨 안 보임)"""
        for amp in (7, 12, 15):
            self.sc.wobble = self._twitch(amp, hold=0.15)
            ok, _ = run_bite(self.sc, "none", "vanilla", bite_timeout_sec=4.0)
            self.assertFalse(ok, f"{amp}px 움찔")

    def test_twitch_then_vanish_is_a_bite(self):
        self.sc.wobble = self._twitch(9, hold=0.15)
        self.assertTrue(run_bite(self.sc, "bite", "vanilla")[0])

    def test_staying_low_is_a_bite(self):
        """움찔이 아니라 낮아진 채로 머무르면(일반 서버의 입질) 입질"""
        self.sc.wobble = self._twitch(14, hold=3.0)
        self.assertTrue(run_bite(self.sc, "none", "vanilla")[0])

    def test_short_particle_occlusion_is_not_a_bite(self):
        self.assertFalse(run_bite(self.sc, "particle", "vanilla", bite_timeout_sec=4.0)[0])


if __name__ == "__main__":
    unittest.main()
