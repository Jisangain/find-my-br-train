import json
import folium
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("--version", type=int, default=0)
args = parser.parse_args()

data = None
if args.version >= 29:
    folder_path = os.path.join("train_routes", f"version{args.version}")
    if os.path.exists(folder_path):
        v_data_path = os.path.join(folder_path, "data.json")
        if os.path.exists(v_data_path):
            print(f"📂 Loading base data.json from {v_data_path} for version {args.version}")
            with open(v_data_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        else:
            with open('data.json', 'r', encoding='utf-8') as f:
                payload = json.load(f)
        data = payload.get('DATA', payload)
        
        print(f"📂 Loading tid_to_stations from {folder_path} for version {args.version}")
        tid_to_stations = {}
        for filename in os.listdir(folder_path):
            if filename.endswith(".json") and filename != "data.json":
                tid = filename[:-5]
                with open(os.path.join(folder_path, filename), "r", encoding="utf-8") as file:
                    tid_to_stations[tid] = json.load(file)
        data["tid_to_stations"] = tid_to_stations

if data is None:
    with open('data.json', 'r', encoding='utf-8') as f:
        payload = json.load(f)
    data = payload.get('DATA', payload)


sid_to_sloc    = data.get('sid_to_sloc', {})
sid_to_sname   = data.get('sid_to_sname', {})
train_names    = data.get('train_names', {})
tid_to_stations = data.get('tid_to_stations', {})

m = folium.Map(location=[23.5, 89.5], zoom_start=7)

for tid, stops in tid_to_stations.items():
    train_label = f"{tid} – {train_names.get(tid, 'Unnamed')}"
    fg = folium.FeatureGroup(name=train_label, show=False)

    for idx, (sid, state, tm) in enumerate(stops, start=1):
        coord = sid_to_sloc[sid]
        name  = sid_to_sname[sid]
        
        # Main marker: numbered circle showing stop index
        folium.Marker(
            location=coord,
            icon=folium.DivIcon(html=f"""
                <div style="
                    background-color: {'blue' if state==1 else 'gray'};
                    color: white;
                    border-radius: 50%;
                    width: 24px;
                    height: 24px;
                    text-align: center;
                    line-height: 24px;
                    font-size: 14px;
                    font-weight: bold;
                ">{idx}</div>
            """),
            popup=f"<b>{name}</b><br/>Time: {tm}<br/>State: {state}"
        ).add_to(fg)

        folium.map.Marker(
            [coord[0] + 0.02, coord[1] + 0.02],
            icon=folium.DivIcon(html=f"""
                <div style="font-size: 12px; color: black;"><b>{name}</b></div>
            """)
        ).add_to(fg)

    fg.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

# HTML and JavaScript for the search box
search_html = """
<div style="position: fixed; 
            top: 10px; left: 70px; z-index: 1000; 
            background-color: white; border: 2px solid grey; 
            padding: 10px; border-radius: 5px;">
    <input type="text" id="latlon" placeholder="e.g., 23.99, 90.36" style="width: 150px;"/>
    <button onclick="searchLocation()">Search</button>
</div>

<script>
function searchLocation() {
    var latlonStr = document.getElementById('latlon').value;
    if (!latlonStr) {
        alert("Please enter coordinates.");
        return;
    }
    var parts = latlonStr.split(',');
    if (parts.length !== 2) {
        alert("Invalid format. Please use 'latitude,longitude'.");
        return;
    }
    var lat = parseFloat(parts[0].trim());
    var lon = parseFloat(parts[1].trim());

    if (isNaN(lat) || isNaN(lon)) {
        alert("Invalid coordinates.");
        return;
    }

    var customMarker = L.marker([lat, lon], {
        icon: L.icon({
            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
            iconSize: [25, 41],
            iconAnchor: [12, 41],
            popupAnchor: [1, -34],
            shadowSize: [41, 41]
        })
    }).addTo(this.map);
    
    customMarker.bindPopup(`<b>Custom Location</b><br>Lat: ${lat}<br>Lon: ${lon}`).openPopup();
    this.map.setView([lat, lon], 13);
}
</script>
"""

# Add the search box to the map
m.get_root().html.add_child(folium.Element(search_html.replace("this.map", m.get_name())))

folium.LayerControl(collapsed=False).add_to(m)

m.save("tid_to_stations_map.html")
print("✅ Map saved as 'tid_to_stations_map.html'")
