import os
import time
import json
import redis
from fastapi.testclient import TestClient
from main import app, tracker

def test_train_chat():
    print("🧪 Running WebSocket Chat Integration Tests...")
    
    # 1. Clean up Redis state for testing
    redis_client = r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    test_train_id = "test_train_999"
    chat_key = f"train:{test_train_id}:chat"
    redis_client.delete(chat_key)
    
    # Set moderator env var explicitly
    os.environ["train_mod"] = "user_2052"
    
    # Initialize TestClient
    client = TestClient(app)
    
    # 2. Test initial connection and empty history
    print("👉 Connecting User A (inside train)...")
    with client.websocket_connect(f"/chat/{test_train_id}?user_id=user_100101&inside_train=true") as ws_a:
        # User A should receive empty history
        data = ws_a.receive_json()
        print("User A received:", data)
        assert data["type"] == "history"
        assert len(data["messages"]) == 0
        
        # 3. Test sending a message and receiving the broadcast
        print("👉 User A sending a message...")
        ws_a.send_text("Hello from User A!")
        
        # User A should receive their own broadcast message
        broadcast_a = ws_a.receive_json()
        print("User A received broadcast:", broadcast_a)
        assert broadcast_a["type"] == "message"
        assert broadcast_a["sender"] == "User_1001(Inside Train)"
        assert broadcast_a["text"] == "Hello from User A!"
        assert "timestamp" in broadcast_a
        
        # Check Redis database directly to see if message was stored
        msgs_in_db = redis_client.zrange(chat_key, 0, -1)
        assert len(msgs_in_db) == 1
        stored_msg = json.loads(msgs_in_db[0])
        assert stored_msg["text"] == "Hello from User A!"
        
        # 4. Test connecting User B (not inside train) and loading history
        print("👉 Connecting User B (outside train)...")
        with client.websocket_connect(f"/chat/{test_train_id}?user_id=user_100202&inside_train=false") as ws_b:
            # User B should receive history containing User A's message
            data_b = ws_b.receive_json()
            print("User B received history:", data_b)
            assert data_b["type"] == "history"
            assert len(data_b["messages"]) == 1
            assert data_b["messages"][0]["text"] == "Hello from User A!"
            assert data_b["messages"][0]["sender"] == "User_1001(Inside Train)"
            
            # 5. Test real-time message broadcasting from B to A
            print("👉 User B sending a message...")
            ws_b.send_text("Hello from User B!")
            
            # User B gets their own broadcast
            broadcast_b_self = ws_b.receive_json()
            print("User B received broadcast:", broadcast_b_self)
            assert broadcast_b_self["sender"] == "User_1002"
            
            # User A should also receive User B's message in real-time
            broadcast_b_to_a = ws_a.receive_json()
            print("User A received broadcast of B's message:", broadcast_b_to_a)
            assert broadcast_b_to_a["text"] == "Hello from User B!"
            assert broadcast_b_to_a["sender"] == "User_1002"
 
     # 6. Test Moderator nickname logic
    print("👉 Connecting Moderator...")
    with client.websocket_connect(f"/chat/{test_train_id}?user_id=user_205202&inside_train=false") as ws_mod:
        history_mod = ws_mod.receive_json()
        assert len(history_mod["messages"]) == 2
        
        ws_mod.send_text("This is Moderator speaking!")
        broadcast_mod = ws_mod.receive_json()
        print("Moderator received broadcast:", broadcast_mod)
        assert broadcast_mod["sender"] == "Moderator"
        assert broadcast_mod["text"] == "This is Moderator speaking!"

    # 7. Test 10-hour history pruning logic
    print("👉 Testing 10-hour history pruning...")
    # Add an old message directly to Redis
    old_time = int(time.time()) - (11 * 3600)  # 11 hours ago
    old_message = {
        "type": "message",
        "sender": "OldUser",
        "user_id": "user_old",
        "text": "Extremely old message",
        "timestamp": old_time
    }
    redis_client.zadd(chat_key, {json.dumps(old_message): old_time})
    
    # Verify it is in Redis
    assert redis_client.zcard(chat_key) == 4
    
    # Connect User C to trigger pruning
    print("👉 Connecting User C to trigger prune...")
    with client.websocket_connect(f"/chat/{test_train_id}?user_id=user_1003") as ws_c:
        history_c = ws_c.receive_json()
        print("User C history count:", len(history_c["messages"]))
        # Should NOT contain the old message (so only 3 messages: User A, User B, Moderator)
        assert len(history_c["messages"]) == 3
        for msg in history_c["messages"]:
            assert msg["text"] != "Extremely old message"
            
    # Also verify it is pruned in Redis itself
    assert redis_client.zcard(chat_key) == 3

    print("🎉 All WebSocket Chat integration tests passed successfully!")

if __name__ == "__main__":
    test_train_chat()
