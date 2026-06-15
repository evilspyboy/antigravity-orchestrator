with open("src/extension.ts", "r", encoding="utf-8") as f:
    content = f.read()

# Let's search for the activation function
import re
activate_matches = re.findall(r"function activate\(.*?\).*?\{", content)
print("Activate function declarations:", activate_matches)

# Search for registerMcpSchemas and syncSkills calls
for call in ["registerMcpSchemas", "syncSkills", "register"]:
    matches = [line.strip() for line in content.splitlines() if call in line]
    print(f"\nLines matching '{call}':")
    for m in matches[:10]:
        print(" ", m)
