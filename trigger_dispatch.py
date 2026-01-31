import requests
import json
import os

# Your Railway URL
BASE_URL = "https://sabine-super-agent-production.up.railway.app"

# 1. HARDCODE IT FOR NOW (easiest for testing)
# Replace 'your-secret-key-here' with the actual value from Railway
API_KEY = "hM0Z_h_OrXweFDEZ55TDfPM89dCPN0kf5PokYWyL-Yo" 

def trigger_dispatch():
    print(f"🔫 Firing dispatch signal to {BASE_URL}...")
    
    # 2. Add the headers dictionary
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }

    try:
        # 3. Pass headers=headers into the post request
        response = requests.post(f"{BASE_URL}/tasks/dispatch", headers=headers)
        
        if response.status_code == 200:
            print("\n✅ SUCCESS: Dispatch Triggered!")
            print("Response Payload:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"\n❌ Failed: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"\n⚠️ Connection Error: {e}")

if __name__ == "__main__":
    trigger_dispatch()