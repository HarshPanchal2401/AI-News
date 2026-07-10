import json

with open("C:\\Users\\harsh.p\\.gemini\\antigravity-ide\\brain\\61830537-7e44-4972-95cc-293faa43db7a\\.system_generated\\logs\\transcript_full.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if "console" in line.lower() or "log" in line.lower():
            content = data.get("content", "")
            if "console" in content.lower() or "error" in content.lower():
                print(f"Step {data.get('step_index')}: {content[:500]}")
