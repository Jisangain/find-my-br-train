import requests
import json

# Test the nearbyroute endpoint
def test_nearbyroute():
    url = "http://localhost:8000/nearbyroute"
    
    # Test data - using valid station codes
    test_requests = [
        {"from": "Khulna", "to": "Biman_Bandar"},  # Mixed case (original format)
        {"from": "KHULNA", "to": "BIMAN_BANDAR"},  # Uppercase (what app sends)
        {"from": "khulna", "to": "biman_bandar"},  # Lowercase
        {"from": "DHA", "to": "CHI"},  # Other valid stations
        {"from": "INVALID", "to": "CHI"},  # Invalid from station
    ]
    
    for i, data in enumerate(test_requests, 1):
        print(f"\n🧪 Test {i}: {data}")
        try:
            response = requests.post(url, json=data)
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Success: {len(result.get('alternative_trains', {}))} alternative routes found")
            else:
                print(f"   ❌ Error: {response.text}")
        except Exception as e:
            print(f"   ❌ Exception: {e}")

if __name__ == "__main__":
    test_nearbyroute()
