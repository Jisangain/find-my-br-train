from fastapi.testclient import TestClient
from main import app

def test_user_reports():
    client = TestClient(app)
    
    # 1. Check initially empty GET /report-user
    print("👉 Fetching reports (should be empty)...")
    res = client.get("/report-user")
    assert res.status_code == 200
    assert "No user reports submitted yet" in res.text
    print("✓ Initial GET OK")
    
    # 2. Submit a report POST /report-user
    print("👉 Submitting a user report...")
    report_data = {
        "reported_user_id": "user_99999",
        "reported_by": "user_11111",
        "text": "This user is spamming the chat channel with links!",
        "train_id": "701",
        "train_name": "Subarna Express"
    }
    res = client.post("/report-user", json=report_data)
    assert res.status_code == 200
    assert res.json() == {"status": "success", "message": "User report recorded successfully"}
    print("✓ POST OK")
    
    # 3. Check reports GET /report-user again
    print("👉 Fetching reports again...")
    res = client.get("/report-user")
    assert res.status_code == 200
    assert "user_99999" in res.text
    assert "user_11111" in res.text
    assert "This user is spamming" in res.text
    assert "Subarna Express" in res.text
    print("✓ GET after POST OK")
    print("🎉 All chat user report tests passed successfully!")

if __name__ == "__main__":
    test_user_reports()
