# routes.py - Route finding endpoints

from fastapi import HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List


def get_two_train_routes(from_station: str, to_station: str, two_train_routes: Dict, data: Dict[str, Any]) -> Dict:
    """Get two-train route options between stations"""
    route_key = (from_station, to_station)
    
    if route_key in two_train_routes:
        # Expand the compact data with names for the response
        sid_to_sname = data.get("sid_to_sname", {})
        train_names = data.get("train_names", {})
        
        routes = []
        for train1_id, train2_id, interchange_id in two_train_routes[route_key]:
            routes.append({
                "train1_id": train1_id,
                "train1_name": train_names.get(train1_id, train1_id),
                "train2_id": train2_id,
                "train2_name": train_names.get(train2_id, train2_id),
                "interchange_station_id": interchange_id,
                "interchange_station_name": sid_to_sname.get(interchange_id, interchange_id)
            })
        
        return {
            "from_station": from_station,
            "to_station": to_station,
            "routes": routes
        }
    else:
        return {
            "from_station": from_station,
            "to_station": to_station,
            "routes": []
        }


def get_all_two_train_routes(two_train_routes: Dict, data: Dict[str, Any]) -> Dict:
    """Return all precalculated two-train routes"""
    sid_to_sname = data.get("sid_to_sname", {})
    train_names = data.get("train_names", {})
    
    json_routes = {}
    for (from_sid, to_sid), route_list in two_train_routes.items():
        route_key = f"{from_sid}_{to_sid}"
        json_routes[route_key] = [
            {
                "train1_id": train1_id,
                "train1_name": train_names.get(train1_id, train1_id),
                "train2_id": train2_id,
                "train2_name": train_names.get(train2_id, train2_id),
                "interchange_station_id": interchange_id,
                "interchange_station_name": sid_to_sname.get(interchange_id, interchange_id)
            }
            for train1_id, train2_id, interchange_id in route_list
        ]
    
    return {
        "total_routes": len(two_train_routes),
        "routes": json_routes
    }


class NearbyRouteRequest(BaseModel):
    from_station: str = Field(alias="from")  
    to: str


async def find_nearby_routes(
    request: NearbyRouteRequest, 
    data: Dict[str, Any],
    train_routes: Dict,
    station_distances: Dict
):
    """Find alternative train routes through nearby stations"""
    
    from_station_input = request.from_station.strip()
    to_station_input = request.to.strip()
    
    sid_to_sloc = data.get("sid_to_sloc", {})
    
    # Case-insensitive station lookup
    station_lookup = {station.lower(): station for station in sid_to_sloc.keys()}
    
    from_station = station_lookup.get(from_station_input.lower())
    to_station = station_lookup.get(to_station_input.lower())
    
    if from_station is None or to_station is None:
        available_stations = list(sid_to_sloc.keys())
        similar_from = [s for s in available_stations if from_station_input.lower() in s.lower() or s.lower() in from_station_input.lower()][:5]
        similar_to = [s for s in available_stations if to_station_input.lower() in s.lower() or s.lower() in to_station_input.lower()][:5]
        
        error_msg = f"Station not found. From: '{from_station_input}' (similar: {similar_from}), To: '{to_station_input}' (similar: {similar_to})"
        raise HTTPException(status_code=400, detail=error_msg)
    
    # Check for invalid coordinates
    from_coords = sid_to_sloc[from_station]
    to_coords = sid_to_sloc[to_station]
    
    if (from_coords[0] == 0.0 and from_coords[1] == 0.0) or (to_coords[0] == 0.0 and to_coords[1] == 0.0):
        raise HTTPException(status_code=400, detail="Station coordinates not available")
    
    # Get direct distance
    direct_distance = None
    if from_station in station_distances:
        for station, distance in station_distances[from_station]:
            if station == to_station:
                direct_distance = distance
                break
    
    if direct_distance is None:
        raise HTTPException(status_code=400, detail="Could not calculate distance between stations")
    
    # Find direct trains
    direct_trains = set()
    for train_id, station_ids in train_routes.items():
        if from_station in station_ids and to_station in station_ids:
            from_index = station_ids.index(from_station)
            to_index = station_ids.index(to_station)
            
            if from_index < to_index:
                direct_trains.add(train_id)
    
    # Search radius
    search_radius = direct_distance * 0.15
    
    # Get nearby stations
    nearby_from_list = get_nearby_stations(from_station, search_radius, station_distances)
    nearby_from = {from_station}
    nearby_from.update(nearby_from_list)
    
    nearby_to_list = get_nearby_stations(to_station, search_radius, station_distances)
    nearby_to = {to_station}
    nearby_to.update(nearby_to_list)
    
    # Find alternative trains
    alternative_trains = {}
    for train_id, station_ids in train_routes.items():
        if train_id in direct_trains:
            continue
        
        train_nearby_from = [station for station in station_ids if station in nearby_from]
        train_nearby_to = [station for station in station_ids if station in nearby_to]
        
        if train_nearby_from and train_nearby_to:
            from_indices = [i for i, station in enumerate(station_ids) if station in nearby_from]
            to_indices = [i for i, station in enumerate(station_ids) if station in nearby_to]
            
            if any(from_idx < to_idx for from_idx in from_indices for to_idx in to_indices):
                nearest_from = get_nearest_station(from_station, train_nearby_from, station_distances)
                nearest_to = get_nearest_station(to_station, train_nearby_to, station_distances)
                
                alternative_trains[train_id] = {
                    "from_nearby": nearest_from,
                    "to_nearby": nearest_to
                }
    
    return {
        "alternative_trains": alternative_trains,
        "total_alternative_routes": len(alternative_trains)
    }


def get_nearby_stations(station_id: str, max_distance_km: float, station_distances: Dict) -> List[str]:
    """Get nearby stations within the specified distance"""
    if station_id not in station_distances:
        return []
    
    nearby = []
    for other_station, distance in station_distances[station_id]:
        if distance <= max_distance_km:
            nearby.append(other_station)
        else:
            break
    
    return nearby


def get_nearest_station(reference_station: str, candidate_stations: List[str], station_distances: Dict) -> List[str]:
    """Get the nearest station from a list of candidates"""
    if not candidate_stations or reference_station not in station_distances:
        return candidate_stations
    
    if reference_station in candidate_stations:
        return [reference_station]
    
    nearest_station = None
    nearest_distance = float('inf')
    
    for station, distance in station_distances[reference_station]:
        if station in candidate_stations and distance < nearest_distance:
            nearest_station = station
            nearest_distance = distance
    
    return [nearest_station] if nearest_station else candidate_stations
