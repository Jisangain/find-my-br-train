# scratch/test_weighted_position.py
import sys
import os
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.redis_tracker import RedisTrainTracker

def run_test():
    print("🧪 Running weighted position calculation validation tests...")
    
    # 1. Initialize tracker
    tracker = RedisTrainTracker(host="localhost", port=6379, db=0)
    
    if not tracker.health_check():
        print("❌ Error: Redis is not running or not accessible. Make sure redis-server is started.")
        sys.exit(1)
        
    train_id = "test_train_999"
    current_time = int(time.time())
    
    # Clean up any existing Redis keys for this test train first
    tracker.redis.delete(
        f"train:{train_id}:active_users",
        f"train:{train_id}:user:user1:last",
        f"train:{train_id}:user:user2:last",
        f"train:{train_id}:cached_live",
        f"train:{train_id}:last_known"
    )
    
    # 2. Push User 1 update: 3.2 min ago, position 1.50
    # 3.2 min is between 3 and 5 min, so weight = 0.15
    ts_user1 = current_time - int(3.2 * 60)
    pos_user1 = 1.50
    success1, msg1 = tracker.push(train_id, "user1", pos_user1, ts_user1)
    assert success1, f"Failed to push user1 update: {msg1}"
    
    # 3. Push User 2 update: 1.12 min ago, position 1.75
    # 1.12 min is between 1 and 2 min, so weight = 0.40
    ts_user2 = current_time - int(1.12 * 60)
    pos_user2 = 1.75
    success2, msg2 = tracker.push(train_id, "user2", pos_user2, ts_user2)
    assert success2, f"Failed to push user2 update: {msg2}"
    
    # 4. Fetch the position and assert
    res = tracker.get_train_position(train_id)
    assert res is not None, "Expected position to be cached and returned"
    
    actual_pos = res["position"]
    expected_pos = (1.75 * 0.40 + 1.50 * 0.15) / (0.40 + 0.15)
    
    print(f"   User 1 (3.2 min ago): Pos = {pos_user1}, Weight = 0.15")
    print(f"   User 2 (1.12 min ago): Pos = {pos_user2}, Weight = 0.40")
    print(f"   Expected Pos: {expected_pos:.6f}")
    print(f"   Actual Cached Pos: {actual_pos:.6f}")
    
    # Using float delta check for precision
    diff = abs(actual_pos - expected_pos)
    assert diff < 0.0001, f"Calculated position mismatch. Expected {expected_pos}, got {actual_pos}"
    
    # Clean up keys after test
    tracker.redis.delete(
        f"train:{train_id}:active_users",
        f"train:{train_id}:user:user1:last",
        f"train:{train_id}:user:user2:last",
        f"train:{train_id}:cached_live",
        f"train:{train_id}:last_known"
    )
    
    print("✅ Weighted position calculation test passed successfully!")
    
    # 5. Station Proximity Priority Test
    print("🧪 Running station proximity priority tests...")
    tracker.redis.delete(
        f"train:{train_id}:active_users",
        f"train:{train_id}:user:user1:last",
        f"train:{train_id}:user:user2:last",
        f"train:{train_id}:user:user3:last",
        f"train:{train_id}:cached_live",
        f"train:{train_id}:last_known"
    )
    
    # User 1: 0.5 min ago, pos = 2.005 (proximity <= 0.01, so weight = 0.05)
    ts_u1 = current_time - int(0.5 * 60)
    pos_u1 = 2.005
    tracker.push(train_id, "user1", pos_u1, ts_u1)
    
    # User 2: 0.5 min ago, pos = 2.015 (proximity <= 0.02, so weight = 0.10)
    ts_u2 = current_time - int(0.5 * 60)
    pos_u2 = 2.015
    tracker.push(train_id, "user2", pos_u2, ts_u2)
    
    # User 3: 0.5 min ago, pos = 2.030 (proximity > 0.02, so normal weight = 0.75)
    ts_u3 = current_time - int(0.5 * 60)
    pos_u3 = 2.030
    tracker.push(train_id, "user3", pos_u3, ts_u3)
    
    res_prox = tracker.get_train_position(train_id)
    assert res_prox is not None
    
    actual_pos_prox = res_prox["position"]
    expected_pos_prox = (2.005 * 0.05 + 2.015 * 0.10 + 2.030 * 0.75) / (0.05 + 0.10 + 0.75)
    
    print(f"   User 1 (pos=2.005, <=0.01): Weight = 0.05")
    print(f"   User 2 (pos=2.015, <=0.02): Weight = 0.10")
    print(f"   User 3 (pos=2.030, >0.02): Weight = 0.75")
    print(f"   Expected Pos: {expected_pos_prox:.6f}")
    print(f"   Actual Cached Pos: {actual_pos_prox:.6f}")
    
    diff_prox = abs(actual_pos_prox - expected_pos_prox)
    assert diff_prox < 0.0001, f"Calculated proximity position mismatch. Expected {expected_pos_prox}, got {actual_pos_prox}"
    
    # Clean up keys after test
    tracker.redis.delete(
        f"train:{train_id}:active_users",
        f"train:{train_id}:user:user1:last",
        f"train:{train_id}:user:user2:last",
        f"train:{train_id}:user:user3:last",
        f"train:{train_id}:cached_live",
        f"train:{train_id}:last_known"
    )
    print("✅ Station proximity priority tests passed successfully!")

if __name__ == '__main__':
    run_test()
