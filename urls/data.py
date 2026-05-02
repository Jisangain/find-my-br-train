# data.py - Data retrieval endpoints

from typing import Dict, Any
import os
import json


def get_revision(current_revision: int) -> Dict[str, int]:
    """Return current data revision"""
    return {"revision": current_revision}


def get_all_trains(data: Dict[str, Any], version: int = 0) -> Dict[str, Any]:
    """Return complete train database"""
    if version >= 28:
        response_data = data.copy()
        
        # Load tid_to_stations from folder 28
        folder_path = os.path.join("train_routes", "version28")
        if os.path.exists(folder_path):
            tid_to_stations = {}
            for filename in os.listdir(folder_path):
                if filename.endswith(".json"):
                    tid = filename[:-5]
                    with open(os.path.join(folder_path, filename), "r", encoding="utf-8") as f:
                        tid_to_stations[tid] = json.load(f)
            response_data["tid_to_stations"] = tid_to_stations
            
        return response_data
        
    return data
