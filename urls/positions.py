# positions.py - Train position endpoints

import hmac
import os
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

# Shared secret that authenticates a "bot" (trusted GPS source) update. The
# client-supplied user_id string must never grant bot trust on its own - it's
# fully attacker-controlled. If this isn't configured, no request can be
# treated as a bot (fail closed).
BOT_API_KEY = os.getenv("BOT_API_KEY", "")


class LocationUpdate(BaseModel):
    train_id: Optional[str] = None
    id: Optional[str] = None  # For backward compatibility
    user_id: Optional[str] = "unknown"
    time: int
    position: float
    bot_token: Optional[str] = None  # Shared secret for trusted bot updates
    # Note: scheduled_position is calculated automatically from train data


def _is_authenticated_bot(bot_token: Optional[str]) -> bool:
    if not BOT_API_KEY or not bot_token:
        return False
    return hmac.compare_digest(bot_token, BOT_API_KEY)


def get_current_positions(train_ids: str, tracker) -> Dict:
    """Return current positions for specified trains"""
    ids = train_ids.split(',')
    positions = tracker.get_positions(ids)
    print(f"Current positions for trains {ids}: {positions}")
    return positions


def get_train_bounds(train_id: str, tracker) -> Dict:
    """Debug endpoint: the reference position new pings for this train are
    currently being teleport-checked against (see RedisTrainTracker.push)."""
    bounds = tracker.get_train_bounds(train_id)
    if bounds:
        return {"train_id": train_id, "bounds": bounds}
    return {"train_id": train_id, "bounds": None, "message": "No reference position yet"}


def receive_update(update: LocationUpdate, tracker):
    """Receive location update from user"""
    # Support both old and new formats for compatibility
    train_id = update.train_id or update.id
    user_id = update.user_id or 'unknown'
    timestamp = update.time
    position = update.position
    
    if not (0 <= update.position <= 150):
        raise HTTPException(400, "Invalid position value")
    
    if train_id is None or timestamp is None or position is None:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    is_bot = _is_authenticated_bot(update.bot_token)
    print(f"{'[BOT]' if is_bot else '[USER]'} train={train_id} pos={position} user={user_id} ts={timestamp}")

    # Store in Redis (scheduled_position is calculated automatically from train data)
    success, message = tracker.push(train_id, user_id, position, timestamp, is_bot=is_bot)
    
    if not success:
        print(f"Position rejected: {message}")
        raise HTTPException(400, f"Position rejected: {message}")
    
    print(f"Added update to Redis: train={train_id}, user={user_id}, pos={position}")
    
    return {"status": "success", "message": message}
