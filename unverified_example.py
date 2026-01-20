import json
import time
import redis

r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

TTL_SECONDS = 600  # last 10 minutes

def on_user_ping(train_id: int, user_id: str, pos: float, acc: float = None, speed: float = None, ts = int(time.time())):

    ping = {
        "pos": pos,
        "ts": ts,
        "acc": acc,
        "speed": speed
    }

    user_key = f"train:{train_id}:user:{user_id}:last"
    active_users_key = f"train:{train_id}:active_users"

    # Pipeline = faster (1 network roundtrip)
    pipe = r.pipeline()
    pipe.set(user_key, json.dumps(ping), ex=TTL_SECONDS)  # store latest ping with TTL
    pipe.sadd(active_users_key, user_id)                 # mark user active on this train
    pipe.expire(active_users_key, TTL_SECONDS)           # auto-clean user list too
    pipe.execute()







import statistics
import json
import time

def compute_train_position(train_id: int):
    active_users_key = f"train:{train_id}:active_users"
    user_ids = list(r.smembers(active_users_key))
    if not user_ids:
        return None

    # build keys for MGET
    keys = [f"train:{train_id}:user:{uid}:last" for uid in user_ids]
    raw = r.mget(keys)   # fast batch fetch

    pings = []
    expired_users = []

    for uid, item in zip(user_ids, raw):
        if item is None:   # key expired (older than 10 min)
            expired_users.append(uid)
            continue
        pings.append(json.loads(item))

    # cleanup expired users from set
    if expired_users:
        r.srem(active_users_key, *expired_users)

    if not pings:
        return None

    # ✅ simple aggregation
    poss = [p["pos"] for p in pings]

    # MEDIAN reduces noise from wrong GPS
    train_pos = statistics.median(poss)

    result = {
        "train_id": train_id,
        "lat": train_pos,
        "count": len(pings),
        "updated_at": int(time.time())
    }
    return result
