import re
import os

filePath = "src/extension.ts"
if os.path.exists(filePath):
    with open(filePath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        if any(w in line.lower() for w in ["delete", "archive", "purge"]):
            print(f"{idx+1}: {line.strip()}")
else:
    print("File not found")
