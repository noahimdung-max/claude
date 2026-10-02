@echo off
cd /d "%~dp0"
python -c "import mss, cv2, numpy, pydirectinput, keyboard, PIL" 2>/dev/null || (
  echo Installing libraries for the first run...
  python -m pip install -q -r requirements.txt
)
start "" pythonw "%~dp0MacroStart.pyw"
