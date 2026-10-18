"""낚시 연결 모드(fishbridge): 가짜 모드 서버로 매크로가 모드를 쓰는지, 끊기면 예전 방식으로 돌아가는지.
(진짜 모드는 개발용 마크 26.3 에서 따로 확인: 마크가 뒤에 있어도 웅크리기·던지기·인벤 정보 됨)"""
import json
import socket
import socketserver
import threading
import time
import unittest

import fakes
import bridge


class FakeMod(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.got = []
        self.sneaking = False
        super().__init__(("127.0.0.1", 0), Handler)
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            line = raw.decode().strip()
            srv = self.server
            srv.got.append(line)
            if line == "ping":
                ans = {"ok": True, "mod": "fishbridge", "ver": "1.0.0", "mc": "26.3"}
            elif line.startswith("sneak"):
                srv.sneaking = line.endswith("1")
                ans = {"ok": True}
            elif line.startswith("inv"):
                ans = {"ok": True, "empty": 30, "map": [True] * 30 + [False] * 6, "sel": 1, "dur": [53, 64]}
            elif line == "state":
                ans = {"ok": True, "focused": False, "screen": None, "paused": False, "inWorld": True}
            else:
                ans = {"ok": True}
            self.wfile.write((json.dumps(ans) + "\n").encode())


def bridged_macro(**over):
    sc = fakes.Scene()
    m = fakes.make_macro(sc, background=True, **over)
    m.bg_mode = True
    srv = FakeMod()
    m.bridge = bridge.Bridge(srv.port)
    m.bridge.connect()
    m.said = []
    m.out = m.said.append
    return m, srv


class UsesMod(unittest.TestCase):
    def setUp(self):
        fakes.EVENTS.clear()

    def test_click_and_shift_go_to_mod(self):
        m, srv = bridged_macro()
        m.right_click()
        m.set_shift(True)
        time.sleep(0.05)
        self.assertTrue(srv.sneaking)
        m.set_shift(False)
        time.sleep(0.05)
        self.assertFalse(srv.sneaking)
        self.assertIn("use", srv.got)
        names = [e[0] for e in fakes.EVENTS]                 # 진짜 입력·창 메시지는 안 씀
        self.assertNotIn("mouseDown", names)
        self.assertNotIn("keyDown", names)
        self.assertFalse(any(n.startswith("win.post") for n in names))
        m.bridge.close()

    def test_sneak_kept_alive_while_held(self):
        m, srv = bridged_macro()
        m.set_shift(True)
        time.sleep(1.2)                                       # 0.5초마다 다시 알림 (모드는 1.5초 소식 없으면 뗌)
        self.assertGreaterEqual(srv.got.count("sneak 1"), 3)
        m.set_shift(False)
        m.bridge.close()

    def test_inventory_from_mod(self):
        m, srv = bridged_macro(exact_durability=True)
        m.inventory_check()
        self.assertEqual(m.inv_empty, 30)
        self.assertEqual(len(m.inv_map), 36)
        self.assertEqual(m.exact["cur"], 53)
        self.assertNotIn("press e", srv.got)                  # 인벤을 열지 않음
        m.bridge.close()

    def test_falls_back_when_mod_dies(self):
        m, srv = bridged_macro()
        srv.shutdown()
        srv.server_close()
        m.bridge.sock.shutdown(socket.SHUT_RDWR)              # 마크가 꺼짐
        fakes.sys.modules["winapi"].is_foreground = lambda h: False
        try:
            m.right_click()
            m.set_shift(True)
            names = [e[0] for e in fakes.EVENTS]
            self.assertIn("win.post_right_click", names)      # 예전 방식(창 메시지)으로
            self.assertIn("win.post_shift", names)
            self.assertIsNone(m.bridge)
            self.assertTrue(any("연결이 끊겼" in s for s in m.said))
            m.set_shift(False)
            self.assertEqual(fakes.EVENTS[-1][0], "win.post_shift")   # 같은 방식으로 뗌
        finally:
            fakes.sys.modules["winapi"].is_foreground = lambda h: True

    def test_no_mod_running(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                             # 아무도 안 듣는 포트
        self.assertIsNone(bridge.try_connect(port))


if __name__ == "__main__":
    unittest.main()
