# redis_tracker.py - Redis-based train position tracking

import json
import time
import statistics
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import redis


class RedisTrainTracker:
    """
    Redis-based train position tracker.
    - Stores last ping from each user per train
    - Auto-expires user data after 10 minutes (TTL)
    - Calculates median position from all active users
    - Stores last known position for 10 hours (fallback when no active users)
    - Bot users (user_id starts with "bot") provide accurate bounds
    - Validates user positions against bot bounds
    - Calculates scheduled position automatically from train data
    - Persists across server restarts (stored in Redis)
    """
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, 
                 ttl_seconds: int = 600, last_known_ttl: int = 36000):
        self.redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.ttl = ttl_seconds            # 10 minutes for active user data
        self.last_known_ttl = last_known_ttl  # 10 hours for last known position/bot data
        self.bound_tolerance = 0.20       # Tolerance for bounds validation
        self.train_data = None            # Reference to train schedule data
    
    def set_train_data(self, data: Dict):
        """Set reference to train schedule data for scheduled position calculations"""
        self.train_data = data
    
    def _calculate_scheduled_position(self, train_id: str, timestamp: int = None) -> Optional[float]:
        """
        Calculate scheduled position based on current time and train schedule.
        Uses interpolation between stations based on scheduled times.
        
        Note: No train runs more than 24 hours, so we only need to handle
        a single midnight crossing at most.
        
        Returns position as float (0 = first station, N-1 = last station)
        Returns None if train not found or no schedule data.
        """
        if self.train_data is None:
            return None
        
        tid_to_stations = self.train_data.get("tid_to_stations", {})
        stations = tid_to_stations.get(str(train_id))
        
        if not stations:
            return None
        
        # Use provided timestamp or current time
        if timestamp:
            now = datetime.fromtimestamp(timestamp)
        else:
            now = datetime.now()
        
        current_minutes = now.hour * 60 + now.minute
        
        # Parse all station times first
        station_times = []  # List of (index, raw_minutes)
        
        for i, station in enumerate(stations):
            if len(station) < 3 or station[2] is None:
                continue
            
            time_str = station[2]
            if time_str == "--:--":
                continue
            
            try:
                parts = time_str.split(':')
                station_minutes = int(parts[0]) * 60 + int(parts[1])
                station_times.append((i, station_minutes))
            except (ValueError, IndexError):
                continue
        
        if not station_times:
            return None
        
        first_station_time = station_times[0][1]
        last_station_time = station_times[-1][1]
        
        # Check if schedule crosses midnight (last time < first time means midnight crossing)
        crosses_midnight = last_station_time < first_station_time
        
        # Adjust station times for midnight crossing
        adjusted_times = []
        for idx, minutes in station_times:
            if crosses_midnight and minutes < first_station_time:
                # This station is after midnight, add 24 hours
                adjusted_times.append((idx, minutes + 1440))
            else:
                adjusted_times.append((idx, minutes))
        
        # Adjust current time for midnight crossing
        # If schedule crosses midnight and current time is in the "after midnight" portion
        if crosses_midnight and current_minutes < first_station_time:
            current_minutes += 1440
        
        # Find bracketing stations
        previous_station_idx = None
        previous_station_time = None
        next_station_idx = None
        next_station_time = None
        
        for idx, station_minutes in adjusted_times:
            if station_minutes <= current_minutes:
                previous_station_idx = idx
                previous_station_time = station_minutes
            elif next_station_idx is None:
                next_station_idx = idx
                next_station_time = station_minutes
                break
        
        # Calculate interpolated position
        if previous_station_idx is not None and next_station_idx is not None:
            total_time = next_station_time - previous_station_time
            elapsed_time = current_minutes - previous_station_time
            
            if total_time > 0:
                progress = elapsed_time / total_time
                return previous_station_idx + progress * (next_station_idx - previous_station_idx)
            return float(previous_station_idx)
        elif previous_station_idx is not None:
            # Past last scheduled station
            return float(previous_station_idx)
        elif next_station_idx is not None:
            # Before first scheduled station
            return 0.0
        
        return None
    
    def push(self, train_id: str, user_id: str, position: float, timestamp: int) -> Tuple[bool, str]:
        """
        Store user's latest position update for a train.
        Only keeps the last update per user (overwrites previous).
        Auto-expires after TTL.
        
        Bot users (user_id starts with "bot") are trusted and set bounds.
        Regular users are validated against bot bounds.
        Scheduled position is calculated automatically from train data.
        
        Returns: (success: bool, message: str)
        """
        # Convert timestamp from milliseconds to seconds if needed
        if timestamp > 2500000000:
            timestamp = int(timestamp / 1000)
        
        is_bot = user_id.lower().startswith("bot")
        
        # Calculate scheduled position for bounds
        scheduled_position = self._calculate_scheduled_position(train_id, timestamp)
        
        # If this is a bot user, update the bounds first
        if is_bot:
            self._update_bot_bounds(train_id, position, scheduled_position, timestamp)
        else:
            # Validate position against bounds for non-bot users
            valid, reason = self._validate_position_against_bounds(train_id, position, scheduled_position)
            if not valid:
                return False, reason
        
        ping = {
            "pos": position,
            "ts": timestamp
        }
        
        user_key = f"train:{train_id}:user:{user_id}:last"
        active_users_key = f"train:{train_id}:active_users"
        active_trains_key = "active_trains"
        all_trains_key = "all_trains_with_history"
        
        # Use longer TTL for bot users
        user_ttl = self.last_known_ttl if is_bot else self.ttl
        
        # Pipeline for atomic operations (single network roundtrip)
        pipe = self.redis.pipeline()
        pipe.set(user_key, json.dumps(ping), ex=user_ttl)  # Store ping with appropriate TTL
        pipe.sadd(active_users_key, user_id)               # Mark user active
        pipe.expire(active_users_key, self.ttl)            # Auto-clean user list (10 min)
        pipe.sadd(active_trains_key, train_id)             # Track active trains
        pipe.expire(active_trains_key, self.ttl)           # Auto-clean train list
        pipe.sadd(all_trains_key, train_id)                # Track all trains with history
        pipe.expire(all_trains_key, self.last_known_ttl)   # 10 hour expiry
        pipe.execute()
        
        # Update last known position for this train
        self._update_last_known_position(train_id)
        
        return True, "Position updated"
    
    def _update_bot_bounds(self, train_id: str, bot_position: float, 
                           scheduled_position: float = None, timestamp: int = None):
        """
        Update bounds for a train based on bot data.
        - Lower bound: max(0, bot_position - 0.20) - train can't be behind this
        - Upper bound: scheduled_position + 0.20 - train can't be ahead of schedule
        
        Bot bounds are stored with 10-hour TTL.
        """
        bounds_key = f"train:{train_id}:bounds"
        
        # Get existing bounds
        existing = self.redis.get(bounds_key)
        if existing:
            bounds = json.loads(existing)
        else:
            bounds = {"lower": None, "upper": None, "bot_position": None, "timestamp": None}
        
        # Update lower bound based on bot position
        # Lower bound = max(0, bot_position - tolerance)
        new_lower = max(0, bot_position - self.bound_tolerance)
        
        # Only update if new lower bound is higher (train moved forward)
        if bounds["lower"] is None or new_lower > bounds["lower"]:
            bounds["lower"] = new_lower
        
        # Update upper bound if scheduled position provided
        if scheduled_position is not None:
            bounds["upper"] = scheduled_position + self.bound_tolerance
        
        # Store bot position and timestamp
        bounds["bot_position"] = bot_position
        bounds["timestamp"] = timestamp or int(time.time())
        
        # Save with 10-hour TTL
        self.redis.set(bounds_key, json.dumps(bounds), ex=self.last_known_ttl)
    
    def _validate_position_against_bounds(self, train_id: str, position: float, 
                                          scheduled_position: float = None) -> Tuple[bool, str]:
        """
        Validate a user's reported position against bounds.
        
        - Upper bound: Always enforced based on scheduled_position + tolerance
          (train can't be ahead of schedule)
        - Lower bound: Only enforced if bot has set it
          (train can't be behind bot's reported position)
        
        Returns: (valid: bool, reason: str)
        """
        # Always check upper bound against scheduled position (train can't be ahead of schedule)
        if scheduled_position is not None:
            upper_bound = scheduled_position + self.bound_tolerance
            if position > upper_bound:
                return False, f"Position {position:.2f} exceeds scheduled position {scheduled_position:.2f} (upper bound {upper_bound:.2f})"
        
        # Check lower bound from bot data (if exists)
        bounds_key = f"train:{train_id}:bounds"
        bounds_data = self.redis.get(bounds_key)
        
        if bounds_data:
            bounds = json.loads(bounds_data)
            lower_bound = bounds.get("lower")
            
            # Check lower bound (train can't be behind bot position - tolerance)
            if lower_bound is not None and position < lower_bound:
                return False, f"Position {position:.2f} is below lower bound {lower_bound:.2f}"
        
        return True, "Position within bounds"
    
    def get_train_bounds(self, train_id: str) -> Optional[Dict]:
        """Get current bounds for a train."""
        bounds_key = f"train:{train_id}:bounds"
        data = self.redis.get(bounds_key)
        if data:
            return json.loads(data)
        return None
    
    def _update_last_known_position(self, train_id: str):
        """
        Calculate and store the last known position for a train.
        Called after each push to keep it fresh.
        Stored with 10-hour TTL.
        """
        active_users_key = f"train:{train_id}:active_users"
        user_ids = list(self.redis.smembers(active_users_key))
        
        if not user_ids:
            return
        
        # Batch fetch all user pings
        keys = [f"train:{train_id}:user:{uid}:last" for uid in user_ids]
        raw = self.redis.mget(keys)
        
        pings = []
        for item in raw:
            if item is not None:
                pings.append(json.loads(item))
        
        if not pings:
            return
        
        # Calculate median position
        positions = [p["pos"] for p in pings]
        median_position = statistics.median(positions)
        max_timestamp = max(p["ts"] for p in pings)
        
        # Store as last known position with 10-hour TTL
        last_known_key = f"train:{train_id}:last_known"
        last_known_data = {
            "position": median_position,
            "timestamp": max_timestamp
        }
        self.redis.set(last_known_key, json.dumps(last_known_data), ex=self.last_known_ttl)
    
    def get_train_position(self, train_id: str) -> Optional[Dict]:
        """
        Get position for a train.
        1. First tries to calculate from active users (last 10 min)
        2. Falls back to last known position (up to 10 hours old)
        
        Returns format compatible with both old and new app:
        {
            "position": ..., "timestamp": ..., "user_count": ..., "is_live": ...,
            "unconfirmed": {"position": ..., "timestamp": ...}  # For old app compatibility
        }
        """
        # Try to get live position from active users
        live_position = self._get_live_position(train_id)
        if live_position:
            result = {**live_position, "is_live": True}
            # Add unconfirmed field for backward compatibility with old app
            result["unconfirmed"] = {
                "position": live_position["position"],
                "timestamp": live_position["timestamp"]
            }
            return result
        
        # Fall back to last known position
        last_known = self._get_last_known_position(train_id)
        if last_known:
            result = {**last_known, "is_live": False, "active_user": 0}
            # Add unconfirmed field for backward compatibility with old app
            result["unconfirmed"] = {
                "position": last_known["position"],
                "timestamp": last_known["timestamp"]
            }
            return result
        
        return None
    
    def _get_live_position(self, train_id: str) -> Optional[Dict]:
        """
        Calculate position from active users (last 10 min).
        Returns None if no active users.
        """
        active_users_key = f"train:{train_id}:active_users"
        user_ids = list(self.redis.smembers(active_users_key))
        
        if not user_ids:
            return None
        
        # Batch fetch all user pings
        keys = [f"train:{train_id}:user:{uid}:last" for uid in user_ids]
        raw = self.redis.mget(keys)
        
        pings = []
        expired_users = []
        
        for uid, item in zip(user_ids, raw):
            if item is None:  # Key expired
                expired_users.append(uid)
                continue
            pings.append(json.loads(item))
        
        # Cleanup expired users from set
        if expired_users:
            self.redis.srem(active_users_key, *expired_users)
        
        if not pings:
            return None
        
        # Calculate median position (reduces noise)
        positions = [p["pos"] for p in pings]
        median_position = statistics.median(positions)
        max_timestamp = max(p["ts"] for p in pings)
        
        return {
            "position": median_position,
            "timestamp": max_timestamp,
            "active_user": len(pings)
        }
    
    def _get_last_known_position(self, train_id: str) -> Optional[Dict]:
        """
        Get last known position (stored for up to 10 hours).
        Used as fallback when no active users.
        """
        last_known_key = f"train:{train_id}:last_known"
        data = self.redis.get(last_known_key)
        
        if data:
            return json.loads(data)
        return None
    
    def get_positions(self, train_ids: List[str]) -> Dict[str, Dict]:
        """
        Get positions for multiple trains.
        Returns dict with train_id as key.
        """
        positions = {}
        
        for train_id in train_ids:
            result = self.get_train_position(train_id)
            if result:
                positions[train_id] = result
        
        return positions
    
    def get_all_active_trains(self) -> List[str]:
        """Get list of all trains with active user data (last 10 min)"""
        active_trains_key = "active_trains"
        return list(self.redis.smembers(active_trains_key))
    
    def get_all_trains_with_history(self) -> List[str]:
        """Get list of all trains with any position history (up to 10 hours)"""
        all_trains_key = "all_trains_with_history"
        return list(self.redis.smembers(all_trains_key))
    
    def get_active_train_count(self) -> int:
        """Get count of active trains"""
        return len(self.get_all_active_trains())
    
    def get_user_count_for_train(self, train_id: str) -> int:
        """Get number of active users for a train"""
        active_users_key = f"train:{train_id}:active_users"
        return self.redis.scard(active_users_key)
    
    def health_check(self) -> bool:
        """Check if Redis connection is healthy"""
        try:
            self.redis.ping()
            return True
        except:
            return False
