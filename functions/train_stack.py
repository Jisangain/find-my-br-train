# train_stack.py - Train position tracking with time-based stack

import asyncio
import time
from typing import Any, Dict, List


class TimedItem:
    def __init__(self, value: dict):
        timestamp = value["timestamp"]
        # Convert timestamp from milliseconds to seconds if needed
        if timestamp > 2500000000:
            self.timestamp = timestamp / 1000.0
        else:
            self.timestamp = timestamp
        self.user_id = value["user_id"]
        self.train_id = value["train_id"]
        self.position = value["position"]


class AsyncTimedStack:
    def __init__(self, max_age_seconds: int = 600):
        self._stack = []
        self._lock = asyncio.Lock()
        self._lock2 = asyncio.Lock()
        self._lock3 = asyncio.Lock()
        self.max_age = max_age_seconds
        self._trains = {}
        self.confirmed_position = {}
        self.unconfirmed_position = {}
    
    async def push(self, item: Any):
        async with self._lock:
            self._stack.append(TimedItem(item))

    async def clean_and_preprocess(self):
        now = time.time()
        latest_items = {}
        async with self._lock:
            async with self._lock2:
                self._trains = {}
                for item in reversed(self._stack):
                    if now - item.timestamp <= self.max_age:
                        if item.user_id not in latest_items:
                            latest_items[item.user_id] = item
                            if item.position:
                                self._trains.setdefault(item.train_id, []).append((item.position, item.timestamp))
                
                self._trains = {k: sorted(v, key=lambda x: x[0]) for k, v in self._trains.items()}
            self._stack = list(latest_items.values())
    
    async def process(self):
        """Process the stack to update train positions"""
        async with self._lock2:
            async with self._lock3:
                for train_id, positions in self._trains.items():
                    if len(positions) == 1:
                        self.unconfirmed_position[train_id] = [positions[0][0], positions[0][1]]
                    elif len(positions) == 2:
                        avg_position = (positions[0][0] + positions[1][0]) / 2.0
                        max_timestamp = max(positions[0][1], positions[1][1])
                        self.unconfirmed_position[train_id] = [avg_position, max_timestamp]
                    elif len(positions) == 3:
                        avg_position = (positions[-2][0] + positions[-3][0]) / 2.0
                        max_timestamp = max(positions[-2][1], positions[-3][1])
                        self.unconfirmed_position[train_id] = [avg_position, max_timestamp]

                    if len(positions) > 3:
                        n = len(positions)
                        k = int(0.67 * n)
                        best_i = 0
                        best_span = positions[k-1][0] - positions[0][0]

                        for i in range(1, n - k + 1):
                            span = positions[i + k - 1][0] - positions[i][0]
                            if span < best_span:
                                best_span = span
                                best_i = i
                        
                        slice = positions[best_i : best_i + k]
                        mid_index = k // 2
                        timestamp = max(item[1] for item in slice)
                        middle_value = (
                            slice[mid_index][0]
                            if k % 2 == 1
                            else 0.5 * (slice[mid_index - 1][0] + slice[mid_index][0])
                        )
                        self.confirmed_position[train_id] = [middle_value, timestamp]

    async def get_all_positions(self, train_ids: List[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
        """Get both confirmed and unconfirmed positions for specified train IDs"""
        positions = {}

        async with self._lock3:
            for train_id in train_ids:
                train_data = {}

                if train_id in self.confirmed_position and self.confirmed_position[train_id]:
                    position, timestamp = self.confirmed_position[train_id]
                    train_data["confirmed"] = {
                        "position": position,
                        "timestamp": int(timestamp)
                    }

                if train_id in self.unconfirmed_position and self.unconfirmed_position[train_id]:
                    position, timestamp = self.unconfirmed_position[train_id]
                    train_data["unconfirmed"] = {
                        "position": position,
                        "timestamp": int(timestamp)
                    }

                if train_data:
                    positions[train_id] = train_data

        return positions


async def periodic_clean_and_preprocess(stack: AsyncTimedStack, interval_seconds: int = 30):
    """Periodically clean and preprocess the stack"""
    while True:
        await stack.clean_and_preprocess()
        await stack.process()
        await asyncio.sleep(interval_seconds)
