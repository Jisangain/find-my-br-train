# data.py - Data retrieval endpoints

from typing import Dict, Any
import os
import json


from typing import Optional

def get_revision(current_revision: int, data_hashes: Dict[int, str] = None, version: Optional[int] = None) -> Dict[str, Any]:
    """Return current data revision and hash"""
    response = {"revision": current_revision}
    
    if data_hashes:
        if version is None:
            if 0 in data_hashes:
                response["hash"] = data_hashes[0]
        else:
            valid_versions = [v for v in data_hashes.keys() if v <= version and v != 0]
            if valid_versions:
                best_y = max(valid_versions)
                response["hash"] = data_hashes[best_y]
            elif 28 in data_hashes and version >= 28:
                response["hash"] = data_hashes[28]
            elif 0 in data_hashes:
                response["hash"] = data_hashes[0]
            
    return response


def get_all_trains(data: Dict[str, Any], version: int = 0) -> Dict[str, Any]:
    """Return complete train database"""
    if version >= 28:
        response_data = data.copy()
        
        folder_path = None
        if os.path.exists("train_routes"):
            available_versions = []
            for folder in os.listdir("train_routes"):
                if folder.startswith("version"):
                    try:
                        v = int(folder.replace("version", ""))
                        available_versions.append(v)
                    except ValueError:
                        pass
            
            valid_versions = [v for v in available_versions if v <= version]
            if valid_versions:
                best_y = max(valid_versions)
                folder_path = os.path.join("train_routes", f"version{best_y}")
        
        # Fallback to version 28 if no valid version directory is found or train_routes doesn't exist
        if folder_path is None or not os.path.exists(folder_path):
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
