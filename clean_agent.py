import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(BASE_DIR, "execution_agent.py")

with open(file_path, "r") as f:
    content = f.read()

# Replace escaped quotes with unescaped ones
content = content.replace('\\\\"', '"').replace("\\\\'", "'")

with open(file_path, "w") as f:
    f.write(content)

print("File cleaned successfully.")
