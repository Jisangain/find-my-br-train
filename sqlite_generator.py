# functions/sqlite_generator.py
import os
import sys
import json
import sqlite3
from typing import Dict, Any

# Ensure project root is in path if run as a script
if __name__ == '__main__':
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.data_loader import load_data
from urls.data import get_all_trains as fetch_version_data


def generate_sqlite_db(data: dict, current_revision: int, data_hashes: dict, version: int, db_path: str):
    """
    Generate an SQLite database containing all transit data for the specified version.
    """
    print(f"Generating SQLite database for version {version} at {db_path}...")
    
    # Ensure a fresh database file is created
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception as e:
            print(f"⚠ Warning: Could not remove old database: {e}")
            
    # 1. Fetch version-specific merged data dictionary
    v_data = fetch_version_data(data, version)
    
    # 2. Open connection and enable Foreign Keys
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # 3. Create tables
    # stations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stations (
        id TEXT PRIMARY KEY,
        name_en TEXT NOT NULL,
        name_bn TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL
    );
    """)
    
    # trains table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trains (
        id TEXT PRIMARY KEY,
        name_en TEXT NOT NULL,
        name_bn TEXT NOT NULL
    );
    """)
    
    # train_off_days table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS train_off_days (
        train_id TEXT NOT NULL,
        day_of_week TEXT NOT NULL,
        FOREIGN KEY(train_id) REFERENCES trains(id) ON DELETE CASCADE
    );
    """)
    
    # routes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS routes (
        train_id TEXT NOT NULL,
        station_id TEXT NOT NULL,
        stop_sequence INTEGER NOT NULL,
        flag INTEGER NOT NULL,
        arrival_time TEXT,
        PRIMARY KEY (train_id, stop_sequence),
        FOREIGN KEY(train_id) REFERENCES trains(id) ON DELETE CASCADE,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE RESTRICT
    );
    """)
    
    # metadata table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    
    # 4. Insert stations data
    sid_to_sloc = v_data.get("sid_to_sloc", {})
    xsid_to_sloc = v_data.get("xsid_to_sloc", {})
    sid_to_sname = v_data.get("sid_to_sname", {})
    
    stations_to_insert = {}
    
    # Standard stations
    for sid, coords in sid_to_sloc.items():
        name_list = sid_to_sname.get(sid, [sid, sid])
        if isinstance(name_list, list) and len(name_list) >= 2:
            name_en, name_bn = name_list[0], name_list[1]
        elif isinstance(name_list, list) and len(name_list) == 1:
            name_en = name_bn = name_list[0]
        else:
            name_en = name_bn = str(name_list)
        stations_to_insert[sid] = (sid, name_en, name_bn, float(coords[0]), float(coords[1]))
        
    # Extra stations (junctions/landmarks)
    for sid, coords in xsid_to_sloc.items():
        if sid not in stations_to_insert:
            stations_to_insert[sid] = (sid, sid, sid, float(coords[0]), float(coords[1]))
            
    cursor.executemany(
        "INSERT OR REPLACE INTO stations (id, name_en, name_bn, lat, lng) VALUES (?, ?, ?, ?, ?)",
        list(stations_to_insert.values())
    )
    
    # 5. Insert trains data
    train_names = v_data.get("train_names", {})
    trains_to_insert = []
    for tid, names in train_names.items():
        if isinstance(names, list) and len(names) >= 2:
            name_en, name_bn = names[0], names[1]
        elif isinstance(names, list) and len(names) == 1:
            name_en = name_bn = names[0]
        else:
            name_en = name_bn = str(names)
        trains_to_insert.append((tid, name_en, name_bn))
        
    cursor.executemany(
        "INSERT OR REPLACE INTO trains (id, name_en, name_bn) VALUES (?, ?, ?)",
        trains_to_insert
    )
    
    # 6. Insert train_off_days data
    offday = v_data.get("offday", {})
    off_days_to_insert = []
    for tid, days in offday.items():
        # Ensure referenced train exists to prevent foreign key violation
        if tid in train_names:
            if isinstance(days, list):
                for day in days:
                    off_days_to_insert.append((tid, day))
            elif isinstance(days, str):
                off_days_to_insert.append((tid, days))
                
    cursor.executemany(
        "INSERT INTO train_off_days (train_id, day_of_week) VALUES (?, ?)",
        off_days_to_insert
    )
    
    # 7. Insert routes data
    tid_to_stations = v_data.get("tid_to_stations", {})
    routes_to_insert = []
    
    for tid, stops in tid_to_stations.items():
        if tid not in train_names:
            continue
        for idx, stop in enumerate(stops):
            # stop is [station_id, stop_type, reaching_time]
            if not isinstance(stop, list) or len(stop) < 2:
                continue
            
            station_id = stop[0]
            flag = stop[1]
            reaching_time = stop[2] if len(stop) >= 3 else -1
            
            # Ensure station_id exists in stations to satisfy FK constraint
            if station_id not in stations_to_insert:
                cursor.execute(
                    "INSERT OR IGNORE INTO stations (id, name_en, name_bn, lat, lng) VALUES (?, ?, ?, 0.0, 0.0)",
                    (station_id, station_id, station_id)
                )
                stations_to_insert[station_id] = (station_id, station_id, station_id, 0.0, 0.0)
                
            arrival_time = None
            if reaching_time != -1 and reaching_time != "-1":
                arrival_time = str(reaching_time)
                
            # stop_sequence is 1-based index
            routes_to_insert.append((tid, station_id, idx + 1, int(flag), arrival_time))
            
    cursor.executemany(
        "INSERT OR REPLACE INTO routes (train_id, station_id, stop_sequence, flag, arrival_time) VALUES (?, ?, ?, ?, ?)",
        routes_to_insert
    )
    
    # 8. Insert metadata
    metadata_keys = [
        "Revision",
        "online_user_update_delay",
        "update_delay",
        "persistence_notice",
        "first_open_notice",
        "app_update_notice",
        "data_update_notice",
        "location_improver"
    ]
    
    metadata_to_insert = []
    for key in metadata_keys:
        val = v_data.get(key)
        if val is not None:
            if isinstance(val, (dict, list)):
                val_str = json.dumps(val)
            elif isinstance(val, bool):
                val_str = "1" if val else "0"
            else:
                val_str = str(val)
            metadata_to_insert.append((key, val_str))
            
    # Add hash if available in data_hashes
    valid_versions = [v for v in data_hashes.keys() if v <= version and v != 0]
    best_hash_v = max(valid_versions) if valid_versions else 0
    if best_hash_v in data_hashes:
        metadata_to_insert.append(("hash", data_hashes[best_hash_v]))
    
    # Add version
    metadata_to_insert.append(("version", str(version)))
    
    cursor.executemany(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        metadata_to_insert
    )
    
    conn.commit()
    
    # Run VACUUM to optimize database size (must be outside transaction block)
    try:
        old_isolation = conn.isolation_level
        conn.isolation_level = None
        cursor.execute("VACUUM;")
        conn.isolation_level = old_isolation
    except Exception as e:
        print(f"⚠ Warning: VACUUM failed: {e}")
        
    conn.close()
    print(f"✓ SQLite database successfully generated: {db_path}")


def get_or_create_sqlite_db(data: dict, current_revision: int, data_hashes: dict, version: int, db_path: str) -> str:
    """
    Checks if an existing database file is valid and matches the current revision.
    If not, it generates a fresh database file.
    """
    needs_generation = True
    
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = 'Revision'")
            row = cursor.fetchone()
            if row and int(row[0]) == current_revision:
                # DB file exists and matches the current revision
                needs_generation = False
            conn.close()
        except Exception as e:
            print(f"⚠ Validation failed for existing database, will recreate: {e}")
            
    if needs_generation:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception as e:
                print(f"⚠ Failed to remove stale SQLite database: {e}")
                
        # Generate the DB
        generate_sqlite_db(data, current_revision, data_hashes, version, db_path)
        
    return db_path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Generate SQLite DB from Bangladesh Railway JSON Data")
    parser.add_argument("--version", type=int, default=33, help="Version number to generate database for (default: 33)")
    parser.add_argument("--output", type=str, default=None, help="Output SQLite database file path")
    args = parser.parse_args()
    
    # Load base data
    data, current_revision = load_data()
    if data == -1:
        print("❌ Error: Could not load data.json")
        sys.exit(1)
        
    # Precalculate hash
    # In CLI mode, we can just hash the JSON output of get_all_trains for the version
    v_data = fetch_version_data(data, args.version)
    import hashlib
    v_hash = hashlib.sha256(json.dumps(v_data, sort_keys=True).encode("utf-8")).hexdigest()
    data_hashes = {args.version: v_hash}
    
    # Determine output path
    output_path = args.output
    if output_path is None:
        db_dir = "sqlite_db"
        os.makedirs(db_dir, exist_ok=True)
        output_path = os.path.join(db_dir, f"version{args.version}.db")
        
    generate_sqlite_db(data, current_revision, data_hashes, args.version, output_path)
