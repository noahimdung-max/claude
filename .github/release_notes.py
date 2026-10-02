"""CHANGELOG.md 에서 한 버전 내용만 뽑아 릴리즈 설명(notes.md)으로 저장."""
import re
import sys

ver = sys.argv[1].lstrip("v")
text = open("CHANGELOG.md", encoding="utf-8").read()
intro = text.split("# 패치 내역")[0].strip()
m = re.search(rf"^## v{re.escape(ver)}\s*$(.*?)(?=^## v|\Z)", text, re.S | re.M)
if not m:
    sys.exit(f"CHANGELOG.md 에 v{ver} 항목이 없음")
body = f"## v{ver} 변경 사항\n{m.group(1).strip()}\n\n---\n{intro}\n\n전체 패치 내역: CHANGELOG.md\n"
open("notes.md", "w", encoding="utf-8").write(body)
sys.stdout.buffer.write(body.encode("utf-8"))
