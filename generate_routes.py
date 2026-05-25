#!/usr/bin/env python3
"""
Generate Train Routes for Bangladesh Railway (Generic Version).
Reconstructs the full physical path of each train route recursively using
other trains' stop patterns.
"""

import json
import os
import shutil
import argparse

def is_backward(t1, t2):
    try:
        h1, m1 = map(int, t1.split(':'))
        h2, m2 = map(int, t2.split(':'))
        diff = (h2 * 60 + m2 - (h1 * 60 + m1)) % 1440
        return diff > 720 or diff == 0
    except Exception:
        return False

def get_intermediates(X, Y, all_routes, active_pairs):
    if (X, Y) in active_pairs:
        return []
    active_pairs.add((X, Y))
    
    candidates = []
    for tid, route in all_routes.items():
        if X in route and Y in route:
            ix = route.index(X)
            iy = route.index(Y)
            if ix < iy:
                intermediates = route[ix+1:iy]
                if len(intermediates) > 0:
                    candidates.append(intermediates)
                    
    if not candidates:
        active_pairs.remove((X, Y))
        return []
        
    longest_intermediates = max(candidates, key=len)
    
    full_sequence = []
    current = X
    for next_station in longest_intermediates:
        full_sequence.extend(get_intermediates(current, next_station, all_routes, active_pairs))
        full_sequence.append(next_station)
        current = next_station
    full_sequence.extend(get_intermediates(current, Y, all_routes, active_pairs))
    
    active_pairs.remove((X, Y))
    return full_sequence

def generate_route(train_stops, all_routes):
    base_station_names = {stop[0] for stop in train_stops}
    result = []
    
    for i in range(len(train_stops) - 1):
        X = train_stops[i][0]
        Y = train_stops[i+1][0]
        tX = train_stops[i][2]
        tY = train_stops[i+1][2]
        
        result.append(train_stops[i])
        
        # Rule 1: Skip if the segment itself is a backward time jump, with exception for Bidyaganj -> Narundi
        skip = is_backward(tX, tY)
        if (X, Y) == ("Bidyaganj", "Narundi"):
            skip = False
            
        if not skip:
            intermediates = get_intermediates(X, Y, all_routes, set())
            filtered_intermediates = [z for z in intermediates if z not in base_station_names]
            for station in filtered_intermediates:
                result.append([station, 0, -1])
            
    result.append(train_stops[-1])
    return result

def main():
    parser = argparse.ArgumentParser(description="Generate Train Routes for a specific version")
    parser.add_argument("--version", type=int, required=True, help="Version number to generate routes for (e.g. 30)")
    args = parser.parse_args()
    
    version = args.version
    version_dir = os.path.join("train_routes", f"version{version}")
    v_data_path = os.path.join(version_dir, "data.json")
    
    # Always load base train schedules from the root data.json
    print(f"📂 Loading base train schedules from root: data.json")
    with open('data.json', 'r', encoding='utf-8') as f:
        payload = json.load(f)
            
    data = payload.get('DATA', payload)
    base_routes = data.get('tid_to_stations', {})
    all_routes = {tid: [stop[0] for stop in stops] for tid, stops in base_routes.items()}
    
    # 2. Prepare directory
    print(f"🧹 Preparing directory: {version_dir}")
    has_v_data = os.path.exists(v_data_path)
    if has_v_data:
        # Save a backup of the version-specific data.json in memory
        with open(v_data_path, 'r', encoding='utf-8') as f:
            v_data_content = f.read()
            
    # Clear directory by removing everything EXCEPT data.json
    if os.path.exists(version_dir):
        for item in os.listdir(version_dir):
            item_path = os.path.join(version_dir, item)
            if os.path.isfile(item_path) and item != "data.json":
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
    else:
        os.makedirs(version_dir, exist_ok=True)
        
    # Restore version-specific data.json if we backed it up
    if has_v_data:
        with open(v_data_path, 'w', encoding='utf-8') as f:
            f.write(v_data_content)
            
    # 3. Generate routes
    print(f"⚙️ Generating version {version} routes for {len(base_routes)} trains...")
    generated_count = 0
    for tid, base_stops in base_routes.items():
        expanded_route = generate_route(base_stops, all_routes)
        
        file_path = os.path.join(version_dir, f"{tid}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(expanded_route, f, separators=(',', ':'))
        generated_count += 1
        
    print(f"✅ Generated {generated_count} train route files successfully in {version_dir}!")

if __name__ == '__main__':
    main()
