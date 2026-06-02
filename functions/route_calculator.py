# route_calculator.py - Route calculation and precalculation utilities

import json
import math
from typing import Dict, Any, List, Tuple


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    r = 6371  # Earth radius in kilometers
    return c * r


def precalculate_train_routes(data: Dict[str, Any]) -> Dict:
    """Precalculate train routes with only regular stops"""
    train_routes = {}
    tid_to_stations = data.get("tid_to_stations", {})
    
    for train_id, stations in tid_to_stations.items():
        regular_stops = [station[0] for station in stations if len(station) >= 2 and station[1] == 1]
        train_routes[train_id] = regular_stops
    
    print(f"✓ Precalculated routes for {len(train_routes)} trains with regular stops only")
    return train_routes


def precalculate_station_distances(data: Dict[str, Any]) -> Dict:
    """Precalculate distances from each station to all other stations"""
    station_distances = {}
    sid_to_sloc = data.get("sid_to_sloc", {})
    
    valid_stations = {
        station_id: coords for station_id, coords in sid_to_sloc.items()
        if not (coords[0] == 0.0 and coords[1] == 0.0)
    }
    
    print(f"Calculating distances between {len(valid_stations)} stations...")
    
    total_stations = len(valid_stations)
    processed = 0
    
    for from_station, from_coords in valid_stations.items():
        distances = []
        
        for to_station, to_coords in valid_stations.items():
            if from_station != to_station:
                distance = calculate_distance(
                    from_coords[0], from_coords[1], 
                    to_coords[0], to_coords[1]
                )
                distances.append((to_station, distance))
        
        distances.sort(key=lambda x: x[1])
        station_distances[from_station] = distances
        
        processed += 1
        if processed % 50 == 0 or processed == total_stations:
            progress = (processed / total_stations) * 100
            print(f"Progress: {progress:.1f}% ({processed}/{total_stations} stations)")
    
    print(f"✓ Precalculated and sorted distances for {len(station_distances)} stations")
    return station_distances


def parse_time(time_str):
    """Parse time string HH:MM to minutes since midnight"""
    if not time_str or time_str == "--:--":
        return None
    try:
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes
    except:
        return None


def time_difference(arrival_time, departure_time):
    """Calculate time difference in minutes, handling day boundary"""
    if arrival_time is None or departure_time is None:
        return None
    diff = departure_time - arrival_time
    if diff < 0:
        diff += 24 * 60
    return diff


def find_common_stations(train1_stations, train2_stations):
    """Find common stations between two trains"""
    common = []
    for i, station1 in enumerate(train1_stations):
        sid1, stype1, time1 = station1[0], station1[1], station1[2] if len(station1) > 2 else None
        if stype1 != 1:
            continue
        
        for j, station2 in enumerate(train2_stations):
            sid2, stype2, time2 = station2[0], station2[1], station2[2] if len(station2) > 2 else None
            if stype2 != 1:
                continue
            
            if sid1 == sid2:
                common.append({
                    'station_id': sid1,
                    'train1_index': i,
                    'train1_time': time1,
                    'train2_index': j,
                    'train2_time': time2
                })
    return common


def find_best_interchange_station(common_stations, from_index_train1, to_index_train2):
    """Find the best interchange station: earliest valid connection (min positive wait)"""
    best_station = None
    min_time_diff = float('inf')
    
    for station in common_stations:
        if station['train1_index'] <= from_index_train1 or station['train2_index'] >= to_index_train2:
            continue
        
        arrival_time = parse_time(station['train1_time'])
        departure_time = parse_time(station['train2_time'])
        
        if arrival_time is None or departure_time is None:
            continue
        
        time_diff = time_difference(arrival_time, departure_time)
        
        if time_diff is not None and time_diff >= 0 and time_diff < min_time_diff:
            min_time_diff = time_diff
            best_station = station
    
    return best_station, min_time_diff if best_station is not None else -1


def _get_total_journey_time(route_info, key, tid_to_stations) -> float:
    """Calculate total journey time in minutes for a route (handles overnight crossings)."""
    train1_id, train2_id, interchange_id = route_info
    from_sid, to_sid = key

    train1_stations = tid_to_stations.get(train1_id, [])
    train2_stations = tid_to_stations.get(train2_id, [])

    train1_departure = None  # Departure from origin on train1
    train1_arrival = None    # Arrival at interchange on train1
    train2_departure = None  # Departure from interchange on train2
    train2_arrival = None    # Arrival at destination on train2

    for station in train1_stations:
        if station[0] == from_sid and len(station) > 2:
            train1_departure = parse_time(station[2])
        elif station[0] == interchange_id and len(station) > 2:
            train1_arrival = parse_time(station[2])

    for station in train2_stations:
        if station[0] == interchange_id and len(station) > 2:
            train2_departure = parse_time(station[2])
        elif station[0] == to_sid and len(station) > 2:
            train2_arrival = parse_time(station[2])

    if train1_departure is None or train2_arrival is None:
        return float('inf')

    # Track day offsets through the journey segments
    days = 0

    # Check if train1 arrives next day at interchange
    if train1_arrival is not None and train1_arrival < train1_departure:
        days += 1

    # Check if train2 departs next day from interchange (relative to train1 arrival)
    if train1_arrival is not None and train2_departure is not None:
        effective_arrival = train1_arrival + days * 24 * 60
        effective_departure = train2_departure
        if effective_departure < train1_arrival:
            days += 1  # Train2 departs next day from interchange

    # Check if train2 arrives next day relative to its own departure
    if train2_departure is not None and train2_arrival < train2_departure:
        days += 1
    elif train2_departure is None and train2_arrival < train1_departure:
        days += 1

    total_time = (train2_arrival - train1_departure) + (days * 24 * 60)
    if total_time < 0:
        total_time += 24 * 60  # Safety fallback

    return total_time


def _get_train1_departure(route_info, key, tid_to_stations) -> float:
    """Return train1 departure time (minutes since midnight) from the origin station."""
    train1_id = route_info[0]
    from_sid = key[0]
    for station in tid_to_stations.get(train1_id, []):
        if station[0] == from_sid and len(station) > 2:
            t = parse_time(station[2])
            return t if t is not None else float('inf')
    return float('inf')


def precalculate_two_train_routes(data: Dict[str, Any], current_revision: int) -> Dict:
    """Precalculate all possible two-train routes"""
    
    # Try to load from cache
    try:
        with open('two_train_routes.json', 'r') as f:
            cached_data = json.load(f)
            if cached_data.get("revision") == current_revision:
                print("✓ Two-train routes loaded from cache (revision matches)")
                routes = {}
                for key, value in cached_data.get("routes", {}).items():
                    from_sid, to_sid = key.split("|||")
                    # File is already sorted by departure time (pre-sorted at save time)
                    routes[(from_sid, to_sid)] = [
                        (r["train1"], r["train2"], r["interchange"])
                        for r in value
                    ]
                return routes
            else:
                print(f"⚠ Warning: Cache revision mismatch (cache: {cached_data.get('revision')}, current: {current_revision}). Loading cache as fallback to avoid blocking startup.")
                routes = {}
                for key, value in cached_data.get("routes", {}).items():
                    from_sid, to_sid = key.split("|||")
                    routes[(from_sid, to_sid)] = [
                        (r["train1"], r["train2"], r["interchange"])
                        for r in value
                    ]
                return routes
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    
    print("Starting precalculation of two-train routes...")
    
    # Filter to only use type 1 stations
    tid_to_stations = {
        tid: [s for s in stations if len(s) >= 2 and s[1] == 1]
        for tid, stations in data.get("tid_to_stations", {}).items()
    }
    routes = {}
    train_ids = list(tid_to_stations.keys())
    total_train_pairs = len(train_ids) * (len(train_ids) - 1)
    processed_pairs = 0
    
    for i, train1_id in enumerate(train_ids):
        train1_stations = tid_to_stations[train1_id]
        
        for j, train2_id in enumerate(train_ids):
            if i == j:
                continue
            
            processed_pairs += 1
            if processed_pairs % 500 == 0:
                progress = (processed_pairs / total_train_pairs) * 100
                print(f"Progress: {progress:.1f}% ({processed_pairs}/{total_train_pairs} train pairs processed)")
            
            train2_stations = tid_to_stations[train2_id]
            common_stations = find_common_stations(train1_stations, train2_stations)
            
            if len(common_stations) < 1:
                continue
            
            for from_idx, from_station in enumerate(train1_stations):
                from_sid, from_stype = from_station[0], from_station[1]
                if from_stype != 1:
                    continue
                
                for to_idx, to_station in enumerate(train2_stations):
                    to_sid, to_stype = to_station[0], to_station[1]
                    if to_stype != 1:
                        continue
                    
                    if from_sid == to_sid:
                        continue
                    
                    has_direct_train1 = any(
                        st[0] == to_sid and st[1] == 1 and idx > from_idx
                        for idx, st in enumerate(train1_stations)
                    )
                    
                    has_direct_train2 = any(
                        st[0] == from_sid and st[1] == 1 and idx < to_idx
                        for idx, st in enumerate(train2_stations)
                    )
                    
                    if has_direct_train1 or has_direct_train2:
                        continue
                    
                    best_interchange, max_wait = find_best_interchange_station(
                        common_stations, from_idx, to_idx
                    )
                    
                    if best_interchange and max_wait >= 0:
                        route_key = (from_sid, to_sid)
                        route_info = (train1_id, train2_id, best_interchange['station_id'])
                        
                        if route_key not in routes:
                            routes[route_key] = []
                        
                        if route_info not in routes[route_key]:
                            routes[route_key].append(route_info)
    
    # Keep top 8 by total travel time (shortest journeys first)
    for key in routes:
        routes[key] = sorted(routes[key], key=lambda r: _get_total_journey_time(r, key, tid_to_stations))[:8]
    
    print(f"✓ Precalculation complete. Found {len(routes)} station pairs with two-train routes.")
    
    # Save to file — routes are pre-sorted by departure time; no dep field needed (saves space)
    try:
        with open('two_train_routes.json', 'w') as f:
            json_routes = {
                "revision": current_revision,
                "routes": {
                    f"{k[0]}|||{k[1]}": [
                        {"train1": t[0], "train2": t[1], "interchange": t[2]}
                        for t in v
                    ]
                    for k, v in routes.items()
                }
            }
            json.dump(json_routes, f, indent=2)
        print("✓ Two-train routes saved to two_train_routes.json")
    except Exception as e:
        print(f"✗ Error saving two-train routes: {e}")
    
    return routes
