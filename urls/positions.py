# positions.py - Train position endpoints

from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional, Dict


class LocationUpdate(BaseModel):
    train_id: Optional[str] = None
    id: Optional[str] = None  # For backward compatibility
    user_id: Optional[str] = "unknown"
    time: int
    position: float
    # Note: scheduled_position is calculated automatically from train data


def get_current_positions(train_ids: str, tracker) -> Dict:
    """Return current positions for specified trains"""
    ids = train_ids.split(',')
    positions = tracker.get_positions(ids)
    print(f"Current positions for trains {ids}: {positions}")
    return positions


def get_train_bounds(train_id: str, tracker) -> Dict:
    """Get current bounds for a train (set by bot users)"""
    bounds = tracker.get_train_bounds(train_id)
    if bounds:
        return {"train_id": train_id, "bounds": bounds}
    return {"train_id": train_id, "bounds": None, "message": "No bounds set"}


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
    
    is_bot = user_id.lower().startswith("bot")
    print(f"{'[BOT]' if is_bot else '[USER]'} train={train_id} pos={position} user={user_id} ts={timestamp}")
    
    # Store in Redis (scheduled_position is calculated automatically from train data)
    success, message = tracker.push(train_id, user_id, position, timestamp)
    
    if not success:
        print(f"Position rejected: {message}")
        raise HTTPException(400, f"Position rejected: {message}")
    
    print(f"Added update to Redis: train={train_id}, user={user_id}, pos={position}")
    
    return {"status": "success", "message": message}
