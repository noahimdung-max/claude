"""더블클릭하면 검은 cmd 창 없이 실행됨 (pythonw)."""
import os
import sys
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
try:
    import app
    app.App().run()
except Exception:
    import ctypes
    msg = traceback.format_exc()
    if "No module named" in msg:
        msg = "필요한 라이브러리가 없어. run.bat 을 한 번 실행해줘.\n\n" + msg
    ctypes.windll.user32.MessageBoxW(0, msg[-1500:], "낚시 매크로 오류", 0x10)
