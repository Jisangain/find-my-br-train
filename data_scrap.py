import json
import requests
from datetime import datetime
import re


def load_data():
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            return data['DATA'], data['CURRENT_REVISION']
    except FileNotFoundError:
        print("Warning: data.json not found, using fallback data")
        # Fallback data in case JSON file is missing
        return {
            "CURRENT_REVISION": 0,
            "ONLINE_USER_UPDATE_DELAY": 10,
            "UPDATE_DELAY": 20,
            "DATA": {
                "sid_to_sname": {"001": "dhaka", "002": "chittagong"},
                "sid_to_sloc": {"001": [24.7119, 92.8954], "002": [22.3569, 91.7832]},
                "train_names": {"101": "Test Express"},
                "tid_to_stations": {"101": [["001", 1, "22:30"], ["002", 1, "01:45"]]}
            }
        }, 127
    
old_data = load_data()[0]
print(len(list(old_data['tid_to_stations'].keys())))

# Collected from https://eticket.railway.gov.bd/train-information
trains = ['712', '771', '772', '793', '794', '705', '706', '727', '728', '769', '770', '747', '748', '783', '784', '759', '760', '753', '754', '775', '776', '751', '752', '797', '755', '798', '756', '731', '757', '758', '765', '763', '766', '764', '715', '716', '725', '726', '795', '796', '733', '734', '761', '762', '803', '804', '779', '780', '713', '714', '768', '767', '791', '792', '787', '788', '701', '702', '703', '704', '707', '708', '711', '709', '710', '717', '718', '719', '720', '721', '722', '723', '724', '735', '736', '737', '738', '739', '740', '741', '742', '743', '744', '745', '746', '749', '750', '773', '774', '781', '782', '785', '786', '789', '790', '799', '800', '801', '802', '729', '730', '777', '778', '57', '58', '77', '78', '805', '806', '1001', '1002', '1003', '1004', '1005', '1006', '1007', '1008', '1009', '1010', '1011', '1012', '1013', '1014', '1015', '1016', '61', '62', '65', '66', '813', '814', '809', '810', '815', '816', '732', '41', '42', '825', '826', '827', '828', '821', '824', '822', '823', '109', '110']
station_mapping = {}
conflict_station = {}
new_station = []
i = 0
for model in trains:
    i+=1
    print("at:",i)
    url = "https://railspaapi.shohoz.com/v1.0/web/train-routes"
    payload = {
        "model": model,
        "departure_date_time": "2025-08-27"
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        traindata = response.json()['data']
        trainname = traindata['train_name']
        offday = ['Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        for onday in traindata['days']:
            offday.remove(onday)
        trainroutes = []
        for route in traindata['routes']:
            traintime = route.get('departure_time') or route['arrival_time']
            time_12h = traintime[:8].strip()
            time_24h = datetime.strptime(time_12h, '%I:%M %p').strftime('%H:%M')
            trainroutes.append([route['city'], 1, time_24h])
        

        for station in trainroutes:
            flag = True
            if model in old_data['tid_to_stations']:
                for old_station in old_data['tid_to_stations'][model]:
                    if station[1:] == old_station[1:]:
                        flag = False
                        if old_station[0] in station_mapping:
                            if station_mapping[old_station[0]] != station[0]:
                                conflict_station[old_station[0]] = (station_mapping[old_station[0]], station[0])
                        else:
                            station_mapping[old_station[0]] = station[0]
            if flag:
                new_station.append(station[0])


        old_data['tid_to_stations'][model] = trainroutes
        if(len(offday) > 0):
            if 'offday' not in old_data:
                old_data['offday'] = {}
            old_data['offday'][model] = offday
        else:
            try:
                if 'offday' in old_data:
                    old_data['offday'].pop(model, None)
            except:
                pass
        old_data['train_names'][model] = trainname
    else:
        print(f"Train {model}: Request failed with status {response.status_code}")
new_station = set([
    station for station in new_station if station not in station_mapping.values() and station not in conflict_station.values()
])
for station in station_mapping:
    old_name = old_data['sid_to_sname'].pop(station)
    old_data['sid_to_sname'][station_mapping[station]] = old_name

    old_loc = old_data['sid_to_sloc'].pop(station)
    old_data['sid_to_sloc'][station_mapping[station]] = old_loc

for station in new_station:
    old_data['sid_to_sname'][station] = station

    old_data['sid_to_sloc'][station] = [0.0, 0.0]

print('\n\n')
print(conflict_station)
raw = json.dumps(old_data, indent=4, ensure_ascii=False)

fixed = re.sub(r"\[\s+([^\]]+?)\s+\]", lambda m: "[" + " ".join(m.group(1).split()) + "]", raw)
with open('updated_data.json', 'w') as f:
    f.write(fixed)