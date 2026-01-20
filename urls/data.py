# data.py - Data retrieval endpoints

from typing import Dict, Any


def get_revision(current_revision: int) -> Dict[str, int]:
    """Return current data revision"""
    return {"revision": current_revision}


def get_all_trains(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return complete train database"""
    return data
