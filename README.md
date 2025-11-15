# Find My BR Train

A real-time train tracking system for Bangladesh Railway (BR) trains. This FastAPI-based server provides live train position updates and allows users to contribute location data.

## 🚂 About

This project helps passengers track Bangladesh Railway trains in real-time by crowdsourcing location updates from users. The system processes multiple user reports to provide accurate train positions.

## 🛠️ Setup

### Prerequisites
- Python 3.8+
- pip

### Installation
1. Clone the repository:
```bash
git clone https://github.com/jisangain/find-my-br-train.git
cd find-my-br-train
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the server:
```bash
python3 main.py
```

The server will start on `http://localhost:8000`

## 📊 API Endpoints

- `GET /` - API information and available endpoints
- `GET /health` - Server health check
- `GET /initrevision` - Get current data revision
- `GET /alltrains` - Download complete train database
- `GET /current/{train_ids}` - Get current positions for specified trains
- `POST /sendupdate` - Submit location update
- `POST /fix` - Report incorrect information
- `GET /docs` - Interactive API documentation

## 🤝 Contributing

We welcome contributions to improve train data accuracy! Most contributions will involve updating the `data.json` file.

### 📝 Contributing to data.json

The `data.json` file contains all train and station information. **After each modification, please increment `CURRENT_REVISION` by 1.**

#### Structure Overview

```json
{
  "CURRENT_REVISION": 128,
  "DATA": {
    "sid_to_sname": { "station_id": "station_name" },
    "sid_to_sloc": { "station_id": [latitude, longitude] },
    "train_names": { "train_id": "train_name" },
    "tid_to_stations": { "train_id": [["station_id", stop_type, "time"]] }
  }
}
```

#### 🚉 Adding Stations (sid_to_sname & sid_to_sloc)

**sid_to_sname**: Station ID to Station Name
- **Always append new stations** - don't modify existing IDs
- **Check if station already exists** before adding
- Use lowercase names (e.g., "dhaka", "chittagong")

**sid_to_sloc**: Station ID to Location [latitude, longitude]
- Find accurate coordinates using Google Maps, OpenStreetMap, or other mapping services
- Use decimal degrees format
- Ensure high precision for accuracy

Example:
```json
"sid_to_sname": {
  "Jashore": "Jashore/Jessore"
},
"sid_to_sloc": {
  "Jashore": [23.1634, 89.2182]
}
```

#### 🚆 Adding Trains (train_names)

- Use official train IDs from [Bangladesh Railway eTicket](https://eticket.railway.gov.bd/en)
- Use proper train names as listed on official sources
- Follow existing ID format (3-digit numbers as strings)

Example:
```json
"train_names": {
  "109": "Parabat Express"
}
```

#### 🛤️ Adding Train Routes (tid_to_stations)

Each station entry has three elements: `["station_id", stop_type, "reaching_time"]`

**Stop Types:**
- `1`: Train stops at this station (regular stop)
- `0`: Train passes through but doesn't stop
- `-1`: Important landmark/irregular stop (bridges, junctions, etc.)

**Time Format:** Use 24-hour format "HH:MM"

**Important:** Keep stations in **sequence order** of the train's journey

Example:
```json
"tid_to_stations": {
  "109": [
    ["Dhaka", 1, "18:00"],    // Dhaka - stops
    ["Comilla", 0, "19:30"],    // Comilla - passes through
    ["Chittagong", 1, "21:15"]     // Chittagong - stops
  ]
}
```

### 📋 Contribution Guidelines

1. **Fork** the repository
2. **Create a new branch** for your changes
3. **Update data.json** following the structure above
4. **Increment CURRENT_REVISION** by 1
5. **Test your changes** by running data_validator.py
6. **Location_analysis.py** creates html file to debug geo location.
7. **Submit a pull request** with a clear description

### ✅ Before Contributing

- Verify train information from official Bangladesh Railway sources
- Double-check station coordinates using multiple mapping services
- Ensure station names are consistent with existing naming conventions
- Test that your JSON is valid (use a JSON validator)

### 🔍 Data Sources

- [Bangladesh Railway eTicket](https://eticket.railway.gov.bd/en) - Official train schedules
- [Google Maps](https://maps.google.com) - Station coordinates
- [OpenStreetMap](https://www.openstreetmap.org) - Alternative mapping source

## 📄 License

This project is open source. Please ensure all contributed data is accurate and from reliable sources.

## 🚀 Live Server

The production server runs at: `train.sportsprime.live`

## 📞 Support

For questions or issues, please open a GitHub issue or contribute to the project!