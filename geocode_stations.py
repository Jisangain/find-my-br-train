import json
import requests
import time
from typing import Dict, List, Tuple, Optional

def load_data(filename: str) -> Dict:
    """Load data from JSON file"""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            return data.get('DATA', data)  # Handle both wrapped and unwrapped formats
    except FileNotFoundError:
        print(f"Error: {filename} not found")
        return {}
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {filename}")
        return {}

def find_zero_coordinate_stations(data: Dict) -> List[str]:
    """Find stations with [0.0, 0.0] coordinates"""
    sid_to_sloc = data.get('sid_to_sloc', {})
    sid_to_sname = data.get('sid_to_sname', {})
    
    zero_stations = []
    for sid, coords in sid_to_sloc.items():
        if coords == [0.0, 0.0] or coords == [0, 0]:
            zero_stations.append(sid)
    
    print(f"Found {len(zero_stations)} stations with [0.0, 0.0] coordinates:")
    for sid in zero_stations:
        station_name = sid_to_sname.get(sid, "Unknown")
        print(f"  {sid}: {station_name}")
    
    return zero_stations

def geocode_station(station_name: str, session: requests.Session) -> Optional[Tuple[float, float]]:
    """
    Try to geocode a station using Nominatim API with different search terms
    Returns (latitude, longitude) or None if not found
    """
    # Different search patterns to try
    search_terms = [
        f"{station_name} railway station bangladesh",
        f"{station_name} junction bangladesh", 
        f"{station_name} rail station bangladesh",
        f"{station_name} train station bangladesh",
        f"{station_name} station bangladesh",
        f"{station_name} bangladesh"
    ]
    
    base_url = "https://nominatim.openstreetmap.org/search"
    
    for search_term in search_terms:
        try:
            params = {
                'q': search_term,
                'format': 'json',
                'limit': 1,
                'countrycodes': 'bd',  # Restrict to Bangladesh
                'addressdetails': 1
            }
            
            headers = {
                'User-Agent': 'Bangladesh Railway Station Geocoder/1.0'
            }
            
            print(f"    Trying: {search_term}")
            
            response = session.get(base_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            results = response.json()
            
            if results and len(results) > 0:
                result = results[0]
                lat = float(result['lat'])
                lon = float(result['lon'])
                display_name = result.get('display_name', '')
                
                print(f"    ✅ Found: {display_name}")
                print(f"    📍 Coordinates: [{lat}, {lon}]")
                
                return (lat, lon)
            
            # Add delay to respect rate limits
            time.sleep(0.5)
            
        except requests.RequestException as e:
            print(f"    ❌ Request error for '{search_term}': {e}")
            continue
        except (ValueError, KeyError) as e:
            print(f"    ❌ Data error for '{search_term}': {e}")
            continue
        except Exception as e:
            print(f"    ❌ Unexpected error for '{search_term}': {e}")
            continue
    
    return None

def load_existing_results(output_filename: str) -> Tuple[Dict, Dict]:
    """Load existing geocoding results if file exists"""
    try:
        with open(output_filename, 'r') as f:
            existing_data = json.load(f)
            return (
                existing_data.get('geocoded_stations', {}),
                existing_data.get('failed_stations', {})
            )
    except FileNotFoundError:
        return {}, {}
    except json.JSONDecodeError:
        print(f"Warning: Could not parse existing {output_filename}")
        return {}, {}

def save_progress(geocoded_stations: Dict, failed_stations: Dict, total_processed: int, output_filename: str):
    """Save progress incrementally"""
    all_results = {**geocoded_stations, **failed_stations}
    total_stations = total_processed
    
    output_data = {
        "geocoded_stations": geocoded_stations,
        "failed_stations": failed_stations,
        "all_stations_sid_to_sloc": all_results,
        "summary": {
            "total_processed": len(geocoded_stations) + len(failed_stations),
            "successfully_geocoded": len(geocoded_stations),
            "failed_to_geocode": len(failed_stations),
            "success_rate": f"{len(geocoded_stations)/(len(geocoded_stations) + len(failed_stations))*100:.1f}%" if (geocoded_stations or failed_stations) else "0%"
        }
    }
    
    with open(output_filename, 'w') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

def main():
    """Main function to geocode stations with zero coordinates"""
    output_filename = "geocoded_stations.json"
    
    # Load the data
    print("Loading data from data.json...")
    data = load_data('data.json')
    
    if not data:
        print("No data loaded. Exiting.")
        return
    
    # Find stations with zero coordinates
    zero_stations = find_zero_coordinate_stations(data)
    
    if not zero_stations:
        print("No stations with [0.0, 0.0] coordinates found.")
        return
    
    # Load existing results to resume if interrupted
    existing_geocoded, existing_failed = load_existing_results(output_filename)
    
    # Filter out already processed stations
    remaining_stations = [sid for sid in zero_stations 
                         if sid not in existing_geocoded and sid not in existing_failed]
    
    # Initialize results with existing data
    geocoded_stations = existing_geocoded.copy()
    failed_stations = existing_failed.copy()
    
    sid_to_sname = data.get('sid_to_sname', {})
    
    if existing_geocoded or existing_failed:
        print(f"📁 Found existing results: {len(existing_geocoded)} geocoded, {len(existing_failed)} failed")
    
    if not remaining_stations:
        print("✅ All stations already processed!")
        return
    
    # Create a session for reuse
    session = requests.Session()
    
    print(f"\n🔍 Starting geocoding for {len(remaining_stations)} remaining stations...")
    print(f"📊 Total stations: {len(zero_stations)}, Already processed: {len(zero_stations) - len(remaining_stations)}")
    print("=" * 60)
    
    for i, sid in enumerate(remaining_stations, 1):
        station_name = sid_to_sname.get(sid, sid)
        current_total = len(zero_stations) - len(remaining_stations) + i
        print(f"\n[{current_total}/{len(zero_stations)}] Geocoding: {sid} ({station_name})")
        
        try:
            # Try to geocode
            coordinates = geocode_station(station_name, session)
            
            if coordinates:
                lat, lon = coordinates
                geocoded_stations[sid] = [lat, lon]
                print(f"  ✅ Success: {sid} -> [{lat}, {lon}]")
            else:
                failed_stations[sid] = [0.0, 0.0]
                print(f"  ❌ Failed: {sid} (keeping [0.0, 0.0])")
            
            # Save progress every 5 stations
            if i % 5 == 0 or i == len(remaining_stations):
                save_progress(geocoded_stations, failed_stations, len(zero_stations), output_filename)
                print(f"  💾 Progress saved ({i}/{len(remaining_stations)} completed)")
            
        except KeyboardInterrupt:
            print(f"\n⏹️  Interrupted by user. Saving progress...")
            save_progress(geocoded_stations, failed_stations, len(zero_stations), output_filename)
            print(f"💾 Progress saved to {output_filename}")
            return
        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")
            failed_stations[sid] = [0.0, 0.0]
        
        # Reduced delay between requests
        time.sleep(0.8)
    
    # Final save
    save_progress(geocoded_stations, failed_stations, len(zero_stations), output_filename)
    
    # Print summary
    print("\n" + "=" * 60)
    print("🎯 GEOCODING SUMMARY")
    print("=" * 60)
    print(f"📊 Total stations processed: {len(zero_stations)}")
    print(f"✅ Successfully geocoded: {len(geocoded_stations)}")
    print(f"❌ Failed to geocode: {len(failed_stations)}")
    print(f"📈 Success rate: {len(geocoded_stations)/len(zero_stations)*100:.1f}%" if zero_stations else "0%")
    print(f"💾 Results saved to: {output_filename}")
    
    if geocoded_stations:
        print(f"\n✅ Successfully geocoded stations:")
        for sid, coords in geocoded_stations.items():
            station_name = sid_to_sname.get(sid, "Unknown")
            print(f"  {sid}: {station_name} -> {coords}")
    
    if failed_stations:
        print(f"\n❌ Failed to geocode stations:")
        for sid in failed_stations:
            station_name = sid_to_sname.get(sid, "Unknown")
            print(f"  {sid}: {station_name}")

if __name__ == "__main__":
    main()
