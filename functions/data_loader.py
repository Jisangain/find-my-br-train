# data_loader.py - Data loading utilities

import json

# Empty-but-well-formed fallback: callers treat the return value as a dict
# (membership checks like `"tid_to_stations" in DATA`, `.get(...)`, etc.), so
# the fallback must be a dict too, not a sentinel int - otherwise startup
# crashes deep inside urls/data.py instead of degrading gracefully.
_FALLBACK_DATA = {"Revision": 0}


def load_data():
    """Load data from JSON file. Falls back to an empty dataset (server
    starts up but serves no trains) if data.json is missing, malformed, or
    missing the Revision key, instead of crashing at startup."""
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data, data['Revision']
    except FileNotFoundError:
        print("Warning: data.json not found, using fallback data")
    except json.JSONDecodeError as e:
        print(f"Warning: data.json is not valid JSON ({e}), using fallback data")
    except KeyError:
        print("Warning: data.json is missing the 'Revision' key, using fallback data")

    return dict(_FALLBACK_DATA), 0

