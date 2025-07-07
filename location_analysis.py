import json
import folium

with open('data.json', 'r', encoding='utf-8') as f:
    payload = json.load(f)

data = payload['DATA']
sid_to_sloc    = data['sid_to_sloc']
sid_to_sname   = data['sid_to_sname']
train_names    = data['train_names']
tid_to_stations = data['tid_to_stations']

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

m.save("tid_to_stations_map.html")
print("✅ Map saved as 'tid_to_stations_map.html'")
