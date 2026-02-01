# redis_tracker.py - Redis-based train position tracking

import json
import time
import statistics
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import redis

# Bangladesh timezone - train schedules are in this timezone
BD_TZ = ZoneInfo("Asia/Dhaka")


class RedisTrainTracker:
    """
    Redis-based train position tracker.
    - Stores last ping from each user per train
    - Auto-expires user data after 10 minutes (TTL)
    - Pre-calculates and caches median position when new data arrives
    - Stores last known position for 10 hours (fallback when no active users)
    - Bot users (user_id starts with "bot") provide accurate bounds
    - Validates user positions against bot bounds
    - Calculates scheduled position automatically from train data
    - Persists across server restarts (stored in Redis)
    - Data validity: positions older than 10 hours are considered invalid
    """
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, 
                 ttl_seconds: int = 600, last_known_ttl: int = 36000):
        self.redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.ttl = ttl_seconds            # 10 minutes for active user data
        self.last_known_ttl = last_known_ttl  # 10 hours for last known position/bot data
        self.max_valid_age = 36000        # 10 hours in seconds - data older than this is invalid
        self.bound_tolerance = 0.50       # Tolerance for bounds validation
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
        
        # Use provided timestamp or current time, always in Bangladesh timezone
        if timestamp:
            now = datetime.fromtimestamp(timestamp, tz=BD_TZ)
        else:
            now = datetime.now(tz=BD_TZ)
        
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
        
        # Get the adjusted last station time for comparison
        adjusted_last_time = adjusted_times[-1][1] if adjusted_times else last_station_time
        
        # Adjust current time for midnight crossing
        # Only add 1440 if current time is in the "after midnight" portion of the route
        # i.e., current time is small (early morning) AND less than last station time (after midnight part)
        if crosses_midnight and current_minutes < first_station_time:
            # Check if we're in early morning (after midnight portion) vs afternoon (before train starts)
            # If current_minutes + 1440 would be within the schedule range, we're in post-midnight
            # If current_minutes is between last_station_time and first_station_time, train is not running
            if current_minutes <= last_station_time:
                # Early morning, after midnight - train is still running from yesterday
                current_minutes += 1440
            # else: afternoon/evening before train starts - don't adjust, will return 0
        
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
        
        # Pre-calculate and cache the current position for this train
        self._update_cached_position(train_id)
        
        return True, "Position updated"
    
    def _update_cached_position(self, train_id: str):
        """
        Pre-calculate and cache the current position for a train.
        Called after each push to keep it fresh - position is served directly from cache.
        Stores both live position (from active users) and last known position.
        """
        active_users_key = f"train:{train_id}:active_users"
        user_ids = list(self.redis.smembers(active_users_key))
        
        if not user_ids:
            return
        
        # Batch fetch all user pings
        keys = [f"train:{train_id}:user:{uid}:last" for uid in user_ids]
        raw = self.redis.mget(keys)
        
        pings = []
        expired_users = []
        current_time = int(time.time())
        
        for uid, item in zip(user_ids, raw):
            if item is None:
                expired_users.append(uid)
                continue
            ping = json.loads(item)
            # Validate data age - skip if older than max_valid_age (10 hours)
            if current_time - ping["ts"] > self.max_valid_age:
                expired_users.append(uid)
                continue
            pings.append(ping)
        
        # Cleanup expired/invalid users from set
        if expired_users:
            self.redis.srem(active_users_key, *expired_users)
        
        if not pings:
            return
        
        # Calculate median position
        positions = [p["pos"] for p in pings]
        median_position = statistics.median(positions)
        max_timestamp = max(p["ts"] for p in pings)
        
        # Store as cached live position (short TTL, refreshed on each update)
        live_cache_key = f"train:{train_id}:cached_live"
        live_data = {
            "position": median_position,
            "timestamp": max_timestamp,
            "active_user": len(pings),
            "cached_at": current_time
        }
        
        # Store as last known position with 10-hour TTL (fallback)
        last_known_key = f"train:{train_id}:last_known"
        last_known_data = {
            "position": median_position,
            "timestamp": max_timestamp
        }
        
        # Pipeline for atomic operations
        pipe = self.redis.pipeline()
        pipe.set(live_cache_key, json.dumps(live_data), ex=self.ttl)
        pipe.set(last_known_key, json.dumps(last_known_data), ex=self.last_known_ttl)
        pipe.execute()
    
    def _update_bot_bounds(self, train_id: str, bot_position: float, 
                           scheduled_position: float = None, timestamp: int = None):
        """
        Update bounds for a train based on bot data.
        - Lower bound: max(0, bot_position - 0.50) - train can't be behind this
        - Upper bound: scheduled_position + 0.50 - train can't be ahead of schedule
        
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
    
    def get_train_position(self, train_id: str) -> Optional[Dict]:
        """
        Get position for a train - serves directly from pre-calculated cache.
        1. First tries cached live position (calculated when data arrives)
        2. Falls back to last known position (up to 10 hours old)
        3. Validates data age - returns None if data is too old (>10 hours)
        
        Returns format compatible with both old and new app:
        {
            "position": ..., "timestamp": ..., "user_count": ..., "is_live": ...,
            "unconfirmed": {"position": ..., "timestamp": ...}  # For old app compatibility
        }
        """
        current_time = int(time.time())
        
        # Try to get cached live position (pre-calculated on push)
        live_cache_key = f"train:{train_id}:cached_live"
        live_data = self.redis.get(live_cache_key)
        
        if live_data:
            cached = json.loads(live_data)
            # Validate data age
            if current_time - cached["timestamp"] <= self.max_valid_age:
                result = {
                    "position": cached["position"],
                    "timestamp": cached["timestamp"],
                    "active_user": cached["active_user"],
                    "is_live": True
                }
                result["unconfirmed"] = {
                    "position": cached["position"],
                    "timestamp": cached["timestamp"]
                }
                return result
        
        # Fall back to last known position
        last_known = self._get_last_known_position(train_id)
        if last_known:
            # Validate data age
            if current_time - last_known["timestamp"] > self.max_valid_age:
                return None  # Data too old, invalid
            result = {**last_known, "is_live": False, "active_user": 0}
            result["unconfirmed"] = {
                "position": last_known["position"],
                "timestamp": last_known["timestamp"]
            }
            return result
        
        return None
    
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
        Get positions for multiple trains efficiently using batch fetch.
        Serves directly from pre-calculated cache - no recalculation.
        Returns dict with train_id as key.
        """
        if not train_ids:
            return {}
        
        current_time = int(time.time())
        positions = {}
        
        # Batch fetch cached live positions (single Redis call)
        live_keys = [f"train:{tid}:cached_live" for tid in train_ids]
        live_data = self.redis.mget(live_keys)
        
        # Track which trains need fallback to last_known
        need_fallback = []
        
        for tid, data in zip(train_ids, live_data):
            if data:
                cached = json.loads(data)
                # Validate data age
                if current_time - cached["timestamp"] <= self.max_valid_age:
                    positions[tid] = {
                        "position": cached["position"],
                        "timestamp": cached["timestamp"],
                        "active_user": cached["active_user"],
                        "is_live": True,
                        "unconfirmed": {
                            "position": cached["position"],
                            "timestamp": cached["timestamp"]
                        }
                    }
                    continue
            need_fallback.append(tid)
        
        # Batch fetch last_known for trains without live data
        if need_fallback:
            last_known_keys = [f"train:{tid}:last_known" for tid in need_fallback]
            last_known_data = self.redis.mget(last_known_keys)
            
            for tid, data in zip(need_fallback, last_known_data):
                if data:
                    last_known = json.loads(data)
                    # Validate data age
                    if current_time - last_known["timestamp"] <= self.max_valid_age:
                        positions[tid] = {
                            "position": last_known["position"],
                            "timestamp": last_known["timestamp"],
                            "is_live": False,
                            "active_user": 0,
                            "unconfirmed": {
                                "position": last_known["position"],
                                "timestamp": last_known["timestamp"]
                            }
                        }
        
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
