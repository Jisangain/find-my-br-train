import json
import sys

# load data
with open('data.json', 'r', encoding='utf-8') as f:
    payload = json.load(f)

data = payload.get("DATA", {})

sid_to_sloc = data.get("sid_to_sloc", {})
sid_to_sname = data.get("sid_to_sname", {})
train_names = data.get("train_names", {})
tid_to_stations = data.get("tid_to_stations", {})

errors = []

# 0. Check that all locations are floats
for sid, coords in sid_to_sloc.items():
    if not (isinstance(coords, list) and len(coords) == 2):
        errors.append(f"🛑 Station {sid}: location should be a list of two floats, got {coords!r}")
        continue
    lat, lon = coords
    if not isinstance(lat, float) or not isinstance(lon, float):
        errors.append(f"🛑 Station {sid}: coordinates must be floats (e.g. 0.0), got types {type(lat).__name__}, {type(lon).__name__}")

# 1. Every train in tid_to_stations must have a name
for tid in tid_to_stations:
    if tid not in train_names:
        errors.append(f"🛑 Train ID {tid} has no entry in train_names.")

# 2. Validate each station entry for each train
for tid, stops in tid_to_stations.items():
    if not isinstance(stops, list) or len(stops) < 2:
        errors.append(f"🛑 Train {tid}: stops should be a list of at least two entries.")
        continue

    # Check first and last entry state == 1
    first_state = stops[0][1] if len(stops[0]) > 1 else None
    last_state  = stops[-1][1] if len(stops[-1]) > 1 else None
    if first_state != 1:
        errors.append(f"🛑 Train {tid}: first stop state is {first_state}, must be 1.")
    if last_state != 1:
        errors.append(f"🛑 Train {tid}: last stop state is {last_state}, must be 1.")

    # Validate each stop
    for idx, stop in enumerate(stops):
        if not (isinstance(stop, list) and len(stop) == 3):
            errors.append(f"🛑 Train {tid}, stop #{idx}: expected [station_id, state, time], got {stop!r}")
            continue

        sid, state, tm = stop

        # station ID must be a string
        if not isinstance(sid, str):
            errors.append(f"🛑 Train {tid}, stop #{idx}: station id {sid!r} is not a string.")

        # state must be -1, 0, or 1
        if state not in (-1, 0, 1):
            errors.append(f"🛑 Train {tid}, stop #{idx}: state {state!r} not in {{-1,0,1}}.")

        # time must be a HH:MM string
        if not (isinstance(tm, str) and len(tm) == 5 and tm[2] == ':' and
                tm[:2].isdigit() and tm[3:].isdigit()):
            errors.append(f"🛑 Train {tid}, stop #{idx}: invalid time format {tm!r}, expected 'HH:MM'.")

        # station must exist in both sid_to_sname and sid_to_sloc
        if sid not in sid_to_sname:
            errors.append(f"🛑 Station {sid} used by train {tid} has no name in sid_to_sname.")
        if sid not in sid_to_sloc:
            errors.append(f"🛑 Station {sid} used by train {tid} has no location in sid_to_sloc.")

# 3. Check for any orphan stations in sid_to_sname or sid_to_sloc
for sid in sid_to_sname:
    if sid not in sid_to_sloc:
        errors.append(f"⚠️ Station {sid} defined in sid_to_sname but missing in sid_to_sloc.")
for sid in sid_to_sloc:
    if sid not in sid_to_sname:
        errors.append(f"⚠️ Station {sid} defined in sid_to_sloc but missing in sid_to_sname.")

# report
if errors:
    print("Validation errors found:\n")
    for err in errors:
        print(err)
    sys.exit(1)
else:
    print("✅ All checks passed successfully.")
