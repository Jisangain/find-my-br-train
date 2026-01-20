# positions.py - Train position endpoints

from fastapi import HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, List


class LocationUpdate(BaseModel):
    train_id: Optional[str] = None
    id: Optional[str] = None  # For backward compatibility
    user_id: Optional[str] = "unknown"
    time: int
    position: float


async def get_current_positions(train_ids: str, stack) -> Dict:
    """Return current positions for specified trains"""
    ids = train_ids.split(',')
    positions = await stack.get_all_positions(ids)
    print(f"Current positions for trains {ids}: {positions}")
    return positions


async def receive_update(update: LocationUpdate, stack):
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
    
    print(f"Updated train {train_id} confirmed position to {position} from user {user_id} at {timestamp}")
    
    update_data = {
        "train_id": train_id,
        "position": position,
        "user_id": user_id,
        "timestamp": timestamp
    }
    await stack.push(update_data)
    print(f"Added update to queue: {update_data}")
    
    return {"status": "success", "message": "Position updated"}
