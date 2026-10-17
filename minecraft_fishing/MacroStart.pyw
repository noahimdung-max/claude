"""더블클릭하면 검은 cmd 창 없이 실행됨 (pythonw).
새 화면(webapp, Edge WebView2)으로 열고, WebView2 가 없거나 못 열면 예전 화면(app, tk)으로 엶."""
import os
import sys
import traceback

BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def old_ui():
    import app
    app.App().run()


try:
    if "--old-ui" in sys.argv:
        old_ui()
    else:
        try:
            import webapp
        except ImportError:
            webapp = None
        if webapp is None:
            old_ui()
        else:
            w = webapp.WebApp()
            try:
                w.run()
            except Exception:
                if w.loaded.is_set():                 # 화면이 이미 떴다면 진짜 오류
                    raise
                from fishing_macro import save_error
                save_error("새 화면을 못 열어서 예전 화면으로 엶\n" + traceback.format_exc())
                w.cleanup()                           # 이미 켜진 매크로·단축키는 끄고
                old_ui()
except Exception:
    import ctypes
    msg = traceback.format_exc()
    if "No module named" in msg:
        msg = "필요한 라이브러리가 없어. run.bat 을 한 번 실행해줘.\n\n" + msg
    ctypes.windll.user32.MessageBoxW(0, msg[-1500:], "낚시 매크로 오류", 0x10)
