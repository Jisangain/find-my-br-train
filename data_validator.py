#!/usr/bin/env python3
"""
Data Validator for Bangladesh Railway Data
Validates consistency and relationships between different data structures
"""

import json
import sys
from typing import Dict, Set, Any, List

def load_data_file(filepath: str) -> Dict[str, Any]:
    """Load and return data from JSON file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('DATA', data)
    except FileNotFoundError:
        print(f"❌ Error: File '{filepath}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in '{filepath}': {e}")
        sys.exit(1)

def analyze_data_consistency(data: Dict[str, Any]) -> bool:
    """Analyze data consistency according to specified rules"""
    
    print("🔍 Bangladesh Railway Data Consistency Analyzer")
    print("=" * 60)
    
    # Extract data structures
    sid_to_sloc = data.get('sid_to_sloc', {})
    sid_to_sname = data.get('sid_to_sname', {})
    train_names = data.get('train_names', {})
    offday = data.get('offday', {})
    tid_to_stations = data.get('tid_to_stations', {})
    
    # Convert to sets for analysis
    sid_sloc_keys = set(sid_to_sloc.keys())
    sid_sname_keys = set(sid_to_sname.keys())
    train_names_keys = set(train_names.keys())
    offday_keys = set(offday.keys())
    tid_stations_keys = set(tid_to_stations.keys())
    
    print(f"📊 Data Structure Sizes:")
    print(f"   • sid_to_sloc:    {len(sid_sloc_keys):4d} entries")
    print(f"   • sid_to_sname:   {len(sid_sname_keys):4d} entries")
    print(f"   • train_names:    {len(train_names_keys):4d} entries")
    print(f"   • offday:         {len(offday_keys):4d} entries")
    print(f"   • tid_to_stations:{len(tid_stations_keys):4d} entries")
    print()
    
    all_checks_passed = True
    
    # Check 1: sid_to_sloc keys == sid_to_sname keys
    print("🔍 Check 1: Station ID consistency (sid_to_sloc ↔ sid_to_sname)")
    if sid_sloc_keys == sid_sname_keys:
        print("   ✅ PASSED: All station IDs have both location and name data")
    else:
        print("   ❌ FAILED: Mismatch between sid_to_sloc and sid_to_sname keys")
        
        missing_in_sname = sid_sloc_keys - sid_sname_keys
        missing_in_sloc = sid_sname_keys - sid_sloc_keys
        
        if missing_in_sname:
            print(f"   📍 {len(missing_in_sname)} stations have location but no name:")
            for station in sorted(missing_in_sname):
                coords = sid_to_sloc[station]
                print(f"      • {station}: {coords}")
        
        if missing_in_sloc:
            print(f"   📝 {len(missing_in_sloc)} stations have name but no location:")
            for station in sorted(missing_in_sloc):
                name = sid_to_sname[station]
                print(f"      • {station}: '{name}'")
        
        all_checks_passed = False
    print()
    
    # Check 2: offday keys ⊆ train_names keys
    print("🔍 Check 2: Off-day data consistency (offday ⊆ train_names)")
    if offday_keys.issubset(train_names_keys):
        print("   ✅ PASSED: All trains with off-days exist in train_names")
    else:
        print("   ❌ FAILED: Some trains have off-day data but no name data")
        
        invalid_offday = offday_keys - train_names_keys
        print(f"   🚫 {len(invalid_offday)} trains have off-day data but no train name:")
        for train_id in sorted(invalid_offday):
            days = offday[train_id]
            print(f"      • {train_id}: off on {days}")
        
        all_checks_passed = False
    print()
    
    # Check 3: tid_to_stations keys ⊆ train_names keys
    print("🔍 Check 3: Train station data consistency (tid_to_stations ⊆ train_names)")
    if tid_stations_keys.issubset(train_names_keys):
        print("   ✅ PASSED: All trains with station data exist in train_names")
    else:
        print("   ❌ FAILED: Some trains have station data but no name data")
        
        invalid_stations = tid_stations_keys - train_names_keys
        print(f"   🚫 {len(invalid_stations)} trains have station data but no train name:")
        for train_id in sorted(invalid_stations):
            stations = tid_to_stations[train_id]
            print(f"      • {train_id}: {len(stations)} stations")
        
        all_checks_passed = False
    print()
    
    # Check 4: All station names in tid_to_stations ⊆ sid_to_sname keys
    print("🔍 Check 4: Station references consistency (station codes in routes ⊆ station data)")
    
    # Collect all station codes used in train routes
    all_route_stations = set()
    train_station_usage = {}
    
    for train_id, stations in tid_to_stations.items():
        train_stations = set()
        for station_info in stations:
            if isinstance(station_info, list) and len(station_info) > 0:
                station_code = station_info[0]
                all_route_stations.add(station_code)
                train_stations.add(station_code)
        train_station_usage[train_id] = train_stations
    
    if all_route_stations.issubset(sid_sname_keys):
        print("   ✅ PASSED: All station codes in routes exist in station data")
        print(f"   📈 {len(all_route_stations)} unique stations referenced in {len(tid_to_stations)} train routes")
    else:
        print("   ❌ FAILED: Some station codes in routes don't exist in station data")
        
        missing_stations = all_route_stations - sid_sname_keys
        print(f"   🚫 {len(missing_stations)} station codes are referenced but don't exist:")
        
        # Show which trains reference missing stations
        for station_code in sorted(missing_stations):
            referencing_trains = []
            for train_id, train_stations in train_station_usage.items():
                if station_code in train_stations:
                    train_name = train_names.get(train_id, "Unknown")
                    referencing_trains.append(f"{train_id}({train_name})")
            
            print(f"      • {station_code}: used by {len(referencing_trains)} trains")
            if len(referencing_trains) <= 5:
                print(f"        └─ {', '.join(referencing_trains)}")
            else:
                print(f"        └─ {', '.join(referencing_trains[:3])}, ... (+{len(referencing_trains)-3} more)")
        
        all_checks_passed = False
    print()
    
    # Summary
    print("=" * 60)
    if all_checks_passed:
        print("🎉 SUMMARY: All consistency checks PASSED!")
        print("   The data structure is valid and consistent.")
    else:
        print("⚠️  SUMMARY: Some consistency checks FAILED!")
        print("   The data structure has integrity issues that need to be resolved.")
    
    print("=" * 60)
    return all_checks_passed

def main():
    """Main function"""
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = "data.json"
    
    print(f"📂 Analyzing file: {filepath}")
    data = load_data_file(filepath)
    
    success = analyze_data_consistency(data)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
