import os

filePath = "index.html"
if os.path.exists(filePath):
    with open(filePath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        if "/api/jules/sessions/delete" in line or "deleteSession" in line:
            print(f"{idx+1}: {line.strip()}")
else:
    print("File not found")
