import urllib.request
import json
import sys

def main():
    session_id = "9880115796551401488"
    with open("settings.json", "r") as f:
        settings = json.load(f)
    api_key = settings.get("jules")
    if not api_key:
        print("No jules api key found")
        sys.exit(1)
        
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print("Session API Response:")
            print(json.dumps(data, indent=2))
    except Exception as e:
        print("API Error:", e)
        if hasattr(e, "read"):
            print(e.read().decode('utf-8'))

if __name__ == "__main__":
    main()
