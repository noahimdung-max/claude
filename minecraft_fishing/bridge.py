"""낚시 연결 모드(Fabric 'fishbridge')와 이야기하기.

마크 26.x(SDL)는 창이 뒤에 있으면 매크로가 보낸 키(Shift·E)를 버려서 백그라운드 모드에서 미니게임을 못 했음.
모드는 게임 안에서 웅크리기·우클릭·좌클릭·인벤 정보를 직접 처리해서 창이 앞에 있든 뒤에 있든 됨.
같은 PC 안(127.0.0.1)에서만 연결. 한 줄 명령 -> 한 줄 JSON 답.
"""
import json
import socket
import threading

PORT = 47321
HOLD_REFRESH = 0.5          # 웅크리기를 누르고 있는 동안 이 간격으로 다시 알림 (모드는 1.5초 동안 소식이 없으면 스스로 뗌)


class BridgeError(Exception):
    pass


class Bridge:
    def __init__(self, port=PORT, timeout=1.0):
        self.port, self.timeout = port, timeout
        self.sock = None
        self.rfile = None
        self.lock = threading.Lock()
        self.info = {}
        self._sneak = False
        self._stop = threading.Event()
        self._keeper = None

    # ---------- 연결 ----------
    def connect(self):
        """연결하고 ping. 모드가 없으면 BridgeError."""
        self.close()
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        except OSError as e:
            raise BridgeError(f"연결 모드가 안 켜져 있어 ({e.__class__.__name__})")
        s.settimeout(self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock, self.rfile = s, s.makefile("r", encoding="utf-8", newline="\n")
        self.info = self.call("ping")
        if self.info.get("mod") != "fishbridge":
            self.close()
            raise BridgeError("다른 프로그램이 응답함")
        self._stop.clear()
        self._keeper = threading.Thread(target=self._keep, daemon=True)
        self._keeper.start()
        return self.info

    def close(self):
        self._stop.set()
        if self.sock:
            try:
                if self._sneak:
                    self._send_line("sneak 0")
            except Exception:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = self.rfile = None
        self._sneak = False

    @property
    def alive(self):
        return self.sock is not None

    def _send_line(self, line):
        self.sock.sendall((line + "\n").encode("utf-8"))

    def call(self, line):
        """명령 한 줄 보내고 답(JSON) 받기. 끊기면 BridgeError (호출한 쪽에서 예전 방식으로 돌아감)."""
        with self.lock:
            if not self.sock:
                raise BridgeError("연결 안 됨")
            try:
                self._send_line(line)
                ans = self.rfile.readline()
            except OSError as e:
                self.sock = None
                raise BridgeError(f"연결 끊김 ({e.__class__.__name__})")
        if not ans:
            self.sock = None
            raise BridgeError("연결 끊김")
        try:
            data = json.loads(ans)
        except ValueError:
            raise BridgeError("답을 못 읽음: " + ans[:80])
        if not data.get("ok", False):
            raise BridgeError(data.get("err", "실패"))
        return data

    def _keep(self):
        """웅크리기를 누르고 있는 동안 계속 알림 (매크로가 갑자기 꺼져도 모드가 알아서 뗌)."""
        while not self._stop.wait(HOLD_REFRESH):
            if self._sneak and self.sock:
                try:
                    self.call("sneak 1")
                except BridgeError:
                    return

    # ---------- 입력 ----------
    def sneak(self, down):
        self._sneak = bool(down)
        self.call("sneak 1" if down else "sneak 0")

    def use(self):
        """우클릭 (낚싯대 던지기/감기)."""
        return self.call("use")

    def attack(self):
        """좌클릭 (미니게임 중 연타)."""
        return self.call("attack")

    def press(self, key):
        """e = 인벤 열기, esc = 열린 창 닫기(게임 화면이면 아무것도 안 함), 1~9 = 핫바 칸 고르기."""
        return self.call("press " + key)

    def inventory(self, slot=0):
        """인벤 정보: {"empty": 빈칸 수, "map": 36칸 빈칸 여부(위 3줄 + 핫바), "sel": 들고 있는 칸 1~9,
        "dur": [남은, 최대] 또는 None (slot=0 이면 들고 있는 칸)}"""
        return self.call(f"inv {int(slot)}")

    def state(self):
        """{"focused": 창이 앞에 있나, "screen": 열린 화면 이름 또는 None, "paused": 일시정지 메뉴}"""
        return self.call("state")


def try_connect(port=None):
    """모드가 켜져 있으면 연결된 Bridge, 아니면 None."""
    b = Bridge(port or PORT)
    try:
        b.connect()
        return b
    except BridgeError:
        return None
