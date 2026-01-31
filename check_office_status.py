import requests
import json

BASE_URL = "https://sabine-super-agent-production.up.railway.app"
API_KEY = "hM0Z_h_OrXweFDEZ55TDfPM89dCPN0kf5PokYWyL-Yo" # Use the same key as before

def check_status():
    headers = {"X-API-Key": API_KEY}
    response = requests.get(f"{BASE_URL}/orchestration/status", headers=headers)
    print("📊 Virtual Engineering Office Status:")
    print(json.dumps(response.json(), indent=2))

if __name__ == "__main__":
    check_status()