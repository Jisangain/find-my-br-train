# main.py
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import time
import json
import uvicorn
from contextlib import asynccontextmanager
import subprocess
import hmac
import hashlib
import os
import asyncio
import requests
from datetime import datetime, timedelta

# In-memory cache for seat data
seat_cache = {}  # Format: {cache_key: {"data": seat_data, "timestamp": datetime, "expires_at": datetime}}

# In-memory cache for API token
api_token_cache = {
    "token": None,
    "updated_at": None
}

# Token generation permission control
token_permission = {
    "is_blocked": False,
    "block_until": None,
    "last_permission_granted": None,
    "last_token_received": None
}

app = FastAPI()


GITHUB_SECRET = os.getenv("GITHUB_SECRET", "").encode()

def verify_github_signature(request_body: bytes, signature_header: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    signature = signature_header.split("=")[1]
    mac = hmac.new(GITHUB_SECRET, msg=request_body, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    return hmac.compare_digest(expected_signature, signature)

@app.post("/payload")
async def github_webhook(request: Request):
    signature = request.headers.get("X-Hub-Signature-256")
    body = await request.body()
    if not verify_github_signature(body, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")
    user_agent = request.headers.get("User-Agent", "")
    if not user_agent.startswith("GitHub-Hookshot/"):
        raise HTTPException(status_code=403, detail="Invalid User-Agent")
    payload = await request.json()
    print("Received valid GitHub webhook:", payload)
    subprocess.run("nohup bash restart_app.sh > restart.log 2>&1 &", shell=True)
    return PlainTextResponse("Pulled and restarted", status_code=200)


# Load data from JSON file
def load_data():
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
            return data, data['Revision']
    except FileNotFoundError:
        print("Warning: data.json not found, using fallback data")
        # Fallback data in case JSON file is missing
        return {
                "sid_to_sname": {"001": "Dhaka", "002": "Chittagong"},
                "sid_to_sloc": {"001": [24.7119, 92.8954], "002": [22.3569, 91.7832]},
                "train_names": {"101": "Test Express"},
                "tid_to_stations": {"101": [["001", 1, "22:30"], ["002", 1, "01:45"]]}
            }, 127


class TimedItem:
    def __init__(self, value: dict):
        # Convert timestamp from milliseconds to seconds if needed
        timestamp = value["timestamp"]
        # If timestamp is in milliseconds, convert to seconds
        if timestamp > 2500000000:
            self.timestamp = timestamp / 1000.0
        else:
            self.timestamp = timestamp
        self.user_id = value["user_id"]
        self.train_id = value["train_id"]
        self.position = value["position"]



class AsyncTimedStack:
    def __init__(self, max_age_seconds: int = 600):  # 10 minutes
        self._stack = []
        self._lock = asyncio.Lock()
        self._lock2 = asyncio.Lock()
        self._lock3 = asyncio.Lock()
        self.max_age = max_age_seconds
        self._trains = {}
        self.confirmed_position = {}
        self.unconfirmed_position = {}
    async def push(self, item: Any):
        async with self._lock:
            self._stack.append(TimedItem(item))

    async def clean_and_preprocess(self):
        now = time.time()
        latest_items = {}
        async with self._lock:
            async with self._lock2:
                self._trains = {}
                for item in reversed(self._stack):
                    if now - item.timestamp <= self.max_age:
                        if item.user_id not in latest_items:
                            latest_items[item.user_id] = item
                            if item.position:
                                self._trains.setdefault(item.train_id, []).append((item.position, item.timestamp))
                
                self._trains = {k: sorted(v, key=lambda x: x[0]) for k, v in self._trains.items()}
            self._stack = list(latest_items.values())
    async def process(self):
        """Process the stack to update train positions"""
        async with self._lock2:
            async with self._lock3:
                for train_id, positions in self._trains.items():
                    if len(positions) == 1:
                        self.unconfirmed_position[train_id] = [positions[0][0], positions[0][1]]
                    elif len(positions) == 2:
                        # Average the positions, use max timestamp
                        avg_position = (positions[0][0] + positions[1][0]) / 2.0
                        max_timestamp = max(positions[0][1], positions[1][1])
                        self.unconfirmed_position[train_id] = [avg_position, max_timestamp]
                    elif len(positions) == 3:
                        # Average two positions, use max timestamp
                        avg_position = (positions[-2][0] + positions[-3][0]) / 2.0
                        max_timestamp = max(positions[-2][1], positions[-3][1])
                        self.unconfirmed_position[train_id] = [avg_position, max_timestamp]
                    


                    if len(positions) > 3:
                        n = len(positions)
                        k = int(0.67 * n)
                        best_i = 0
                        best_span = positions[k-1][0] - positions[0][0]

                        for i in range(1, n - k + 1):
                            span = positions[i + k - 1][0] - positions[i][0]
                            if span < best_span:
                                best_span = span
                                best_i = i
                        slice = positions[best_i : best_i + k]
                        mid_index = k // 2
                        timestamp = max(item[1] for item in slice)
                        middle_value = (
                            slice[mid_index][0]
                            if k % 2 == 1
                            else 0.5 * (slice[mid_index - 1][0] + slice[mid_index][0])
                        )
                        self.confirmed_position[train_id] = [middle_value, timestamp]
                        

    async def get_all_positions(self, train_ids: List[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
        """Get both confirmed and unconfirmed positions for specified train IDs"""
        positions = {}

        async with self._lock3:
            for train_id in train_ids:
                train_data = {}

                # Add confirmed position if exists
                if train_id in self.confirmed_position and self.confirmed_position[train_id]:
                    position, timestamp = self.confirmed_position[train_id]
                    train_data["confirmed"] = {
                        "position": position,
                        "timestamp": int(timestamp)  # Ensure timestamp is integer seconds
                    }

                # Add unconfirmed position if exists
                if train_id in self.unconfirmed_position and self.unconfirmed_position[train_id]:
                    position, timestamp = self.unconfirmed_position[train_id]
                    train_data["unconfirmed"] = {
                        "position": position,
                        "timestamp": int(timestamp)  # Ensure timestamp is integer seconds
                    }

                # Only add if we have any data
                if train_data:
                    positions[train_id] = train_data

        return positions






async def periodic_clean_and_preprocess(stack: AsyncTimedStack, interval_seconds: int = 30):
    while True:
        await stack.clean_and_preprocess()
        await stack.process()
        
        await asyncio.sleep(interval_seconds)

        


# Load data at startup
DATA, CURRENT_REVISION = load_data()

# Utility function to calculate distance between two points using Haversine formula
def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate the distance between two points on Earth using Haversine formula"""
    import math
    
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    return c * r

# Precalculated train routes (only stations with stop_type = 1)
TRAIN_ROUTES = {}

# Precalculated distances between stations (sorted by distance)
STATION_DISTANCES = {}

def precalculate_train_routes():
    """Precalculate train routes with only regular stops (middle value = 1) for faster calculations"""
    global TRAIN_ROUTES
    tid_to_stations = DATA.get("tid_to_stations", {})
    
    for train_id, stations in tid_to_stations.items():
        # Filter stations with stop_type = 1 (middle value)
        regular_stops = [station[0] for station in stations if len(station) >= 2 and station[1] == 1]
        TRAIN_ROUTES[train_id] = regular_stops
    
    print(f"Precalculated routes for {len(TRAIN_ROUTES)} trains with regular stops only")

def precalculate_station_distances():
    """Precalculate distances from each station to all other stations, sorted by distance"""
    global STATION_DISTANCES
    sid_to_sloc = DATA.get("sid_to_sloc", {})
    
    # Filter out stations with invalid coordinates (0.0, 0.0)
    valid_stations = {
        station_id: coords for station_id, coords in sid_to_sloc.items()
        if not (coords[0] == 0.0 and coords[1] == 0.0)
    }
    
    print(f"Calculating distances between {len(valid_stations)} stations...")
    
    for from_station, from_coords in valid_stations.items():
        distances = []
        
        for to_station, to_coords in valid_stations.items():
            if from_station != to_station:  # Skip self-distance
                distance = calculate_distance(
                    from_coords[0], from_coords[1], 
                    to_coords[0], to_coords[1]
                )
                distances.append((to_station, distance))
        
        # Sort by distance (closest first)
        distances.sort(key=lambda x: x[1])
        STATION_DISTANCES[from_station] = distances
    
    print(f"Precalculated and sorted distances for {len(STATION_DISTANCES)} stations")

def get_nearby_stations(station_id, max_distance_km):
    """Get nearby stations within the specified distance (optimized lookup)"""
    if station_id not in STATION_DISTANCES:
        return []
    
    nearby = []
    for other_station, distance in STATION_DISTANCES[station_id]:
        if distance <= max_distance_km:
            nearby.append(other_station)
        else:
            break  # Since distances are sorted, we can stop here
    
    return nearby

def get_nearest_station(reference_station, candidate_stations):
    """Get the nearest station from a list of candidates to a reference station"""
    if not candidate_stations or reference_station not in STATION_DISTANCES:
        return candidate_stations
    
    # If reference station is in the candidates, return it (distance = 0)
    if reference_station in candidate_stations:
        return [reference_station]
    
    # Find the nearest station from candidates
    nearest_station = None
    nearest_distance = float('inf')
    
    for station, distance in STATION_DISTANCES[reference_station]:
        if station in candidate_stations and distance < nearest_distance:
            nearest_station = station
            nearest_distance = distance
    
    return [nearest_station] if nearest_station else candidate_stations

# Precalculate routes and distances at startup
precalculate_train_routes()
precalculate_station_distances()
# Store current train positions (simulation) - separate confirmed and unconfirmed
train_positions_confirmed = {}
train_positions_unconfirmed = {}

stack = AsyncTimedStack(max_age_seconds=600)  # 10 mins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    print("Starting Find My BR Train FastAPI Server...")
    print("API Base URL: train.sportsprime.live")
    #print("Interactive Docs: train.sportsprime.live/docs")
    print("Health Check: train.sportsprime.live/health")
    print("\nPress Ctrl+C to stop the server")
    
    # Initialize train positions
    
    # Start train movement simulation
    
    task1 = asyncio.create_task(periodic_clean_and_preprocess(stack, interval_seconds=30))
    
    yield
    task1.cancel()
    try:
        await task1
    except asyncio.CancelledError:
        print("Consumer task cancelled cleanly")
    # Shutdown (if needed)
    print("Shutting down FastAPI Server...")

app = FastAPI(
    title="Find My BR Train Server",
    description="API server for Find My BR Train app",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request/response validation
class LocationUpdate(BaseModel):
    train_id: Optional[str] = None
    id: Optional[str] = None  # For backward compatibility
    user_id: Optional[str] = "unknown"
    time: int
    position: float

class IssueReport(BaseModel):
    issue_type: Optional[str] = None
    train_id: Optional[str] = None
    train_name: Optional[str] = None
    user_id: Optional[str] = "anonymous"
    timestamp: Optional[str] = None
    description: Optional[str] = None
    blue_train_position: Optional[float] = None
    gray_train_position: Optional[float] = None
    is_using_gps: Optional[bool] = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None

@app.get("/initrevision")
async def get_revision():
    """Return current data revision"""
    return {"revision": CURRENT_REVISION}

@app.get("/alltrains")
async def get_all_trains():
    """Return complete train database"""
    return DATA

@app.get("/current/{train_ids}")
async def get_current_positions(train_ids: str):
    """Return current positions for specified trains"""
    ids = train_ids.split(',')
    positions = {}
    
    positions = await stack.get_all_positions(ids)
    print(f"Current positions for trains {ids}: {positions}")
    return positions



@app.post("/sendupdate")
async def receive_update(update: LocationUpdate):
    """Receive location update from user"""
    # Support both old and new formats for compatibility
    train_id = update.train_id or update.id
    user_id = update.user_id or 'unknown'
    timestamp = update.time
    position = update.position
    
    if not (0 <= update.position <= 150):
        raise HTTPException(400, "Invalid position value")
    
    if not all([train_id, timestamp, position]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # Store the user-provided position as confirmed
    # train_positions_confirmed[train_id] = [float(position), int(timestamp)]
    
    print(f"Updated train {train_id} confirmed position to {position} from user {user_id} at {timestamp}")
    
    update = {
        "train_id": train_id,
        "position": position,
        "user_id": user_id,
        "timestamp": timestamp
    }
    await stack.push(update)
    print(f"Added update to queue: {update}")
    return {"status": "success", "message": "Position updated"}

@app.post("/fix")
async def report_issue_post(report: IssueReport):
    """Handle JSON issue report submissions from the app"""
    # Log the issue report
    print(f"\n📋 ISSUE REPORT RECEIVED:")
    print(f"   Type: {report.issue_type or 'Not specified'}")
    print(f"   Train: {report.train_name or 'Unknown'} ({report.train_id or 'Unknown ID'})")
    print(f"   User: {report.user_id}")
    print(f"   Time: {report.timestamp or 'Not specified'}")
    print(f"   Description: {report.description or 'No description'}")
    
    if report.blue_train_position:
        gps_indicator = "(GPS)" if report.is_using_gps else "(System)"
        print(f"   Blue Train Position: {report.blue_train_position} {gps_indicator}")
    if report.gray_train_position:
        print(f"   Gray Train Position: {report.gray_train_position} (User reports)")
    
    # Log location data if available
    if report.latitude is not None and report.longitude is not None:
        print(f"   📍 Location: {report.latitude:.6f}, {report.longitude:.6f}")
        print(f"   🗺️  Maps Link: https://maps.google.com/maps?q={report.latitude},{report.longitude}")
    elif report.latitude is not None or report.longitude is not None:
        print(f"   ⚠️  Partial location data: lat={report.latitude}, lng={report.longitude}")
    else:
        print(f"   📍 Location: Not available")
    
    print("   ✅ Issue report logged successfully\n")
    
    # Append the report to a file for persistence
    try:
        with open("issue_reports.log", "a") as f:
            f.write(json.dumps(report.model_dump()) + "\n")
    except Exception as e:
        print(f"Failed to write issue report to file: {e}")

    return {"status": "success", "message": "Issue report received"}

@app.get("/report", response_class=HTMLResponse)
async def view_reports():
    """View all issue reports in simple HTML format"""
    try:
        reports = []
        
        # Read reports from the log file
        try:
            with open("issue_reports.log", "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            report = json.loads(line.strip())
                            reports.append(report)
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass  # No reports file exists yet
        
        # Sort reports by timestamp (newest first)
        reports.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Generate statistics
        total_reports = len(reports)
        categorized_issues = len([r for r in reports if r.get('issue_type')])
        affected_trains = len(set(r.get('train_id', 'Unknown') for r in reports))
        unique_users = len(set(r.get('user_id', 'Anonymous') for r in reports))
        
        # Generate simple HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Find My BR Train - Issue Reports</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>🚂 Find My BR Train - Issue Reports</h1>
            
            <h2>📊 Statistics</h2>
            <ul>
                <li><strong>Total Reports:</strong> {total_reports}</li>
                <li><strong>Categorized Issues:</strong> {categorized_issues}</li>
                <li><strong>Affected Trains:</strong> {affected_trains}</li>
                <li><strong>Unique Users:</strong> {unique_users}</li>
            </ul>
            
            <h2>📋 Reports ({total_reports} total)</h2>
        """
        
        if not reports:
            html_content += "<p><em>No reports submitted yet.</em></p>"
        else:
            for i, report in enumerate(reports):
                issue_type = report.get('issue_type', 'General Issue')
                train_name = report.get('train_name', 'Unknown Train')
                train_id = report.get('train_id', 'Unknown ID')
                user_id = report.get('user_id', 'Anonymous')
                timestamp = report.get('timestamp', 'Unknown Time')
                description = report.get('description', 'No description provided')
                blue_pos = report.get('blue_train_position')
                gray_pos = report.get('gray_train_position')
                is_gps = report.get('is_using_gps', False)
                latitude = report.get('latitude')
                longitude = report.get('longitude')
                
                html_content += f"""
                <div style="border: 1px solid #ccc; margin: 10px 0; padding: 15px;">
                    <h3>#{i+1}: {issue_type}</h3>
                    <p><strong>Train:</strong> {train_name} ({train_id})</p>
                    <p><strong>Reported By:</strong> {user_id}</p>
                    <p><strong>Time:</strong> {timestamp}</p>
                    <p><strong>Description:</strong> {description}</p>
                """
                
                if blue_pos or gray_pos:
                    html_content += "<p><strong>Position Information:</strong></p><ul>"
                    if blue_pos:
                        gps_indicator = "(GPS)" if is_gps else "(System)"
                        html_content += f"<li>Blue Train Position: {blue_pos} {gps_indicator}</li>"
                    if gray_pos:
                        html_content += f"<li>Gray Train Position: {gray_pos} (User Report)</li>"
                    html_content += "</ul>"
                
                # Add location information if available
                if latitude is not None and longitude is not None:
                    html_content += f"""
                    <p><strong>📍 Location Information:</strong></p>
                    <ul>
                        <li>Latitude: {latitude:.6f}</li>
                        <li>Longitude: {longitude:.6f}</li>
                        <li><a href="https://maps.google.com/maps?q={latitude},{longitude}" target="_blank">🗺️ View on Google Maps</a></li>
                        <li><a href="https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}&zoom=16" target="_blank">🗺️ View on OpenStreetMap</a></li>
                    </ul>
                    """
                elif latitude is not None or longitude is not None:
                    html_content += f"""
                    <p><strong>⚠️ Partial Location:</strong> lat={latitude}, lng={longitude}</p>
                    """
                else:
                    html_content += "<p><strong>📍 Location:</strong> Not available</p>"
                
                html_content += "</div>"
        
        html_content += f"""
            <hr>
            <p><small>Last updated: {int(time.time())} | <a href="/report">Refresh</a></small></p>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        return HTMLResponse(content=f"""
        <html>
        <body>
            <h1>Error Loading Reports</h1>
            <p>Error: {str(e)}</p>
        </body>
        </html>
        """)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "revision": CURRENT_REVISION,
        "active_trains_confirmed": len(train_positions_confirmed),
        "active_trains_unconfirmed": len(train_positions_unconfirmed)
    }

@app.get("/token")
async def get_token():
    """Return API token from cache or environment variable TRAIN_API_TOKEN"""
    # First check if we have a cached token
    if api_token_cache["token"] is not None:
        return {"token": api_token_cache["token"], "source": "cache", "updated_at": api_token_cache["updated_at"]}
    
    # Fall back to environment variable
    token = os.getenv("TRAIN_API_TOKEN", "")
    return {"token": token, "source": "environment"}

@app.get("/request-token-permission")
async def request_token_permission():
    """Request permission to generate a new token"""
    try:
        current_time = time.time()
        
        # Check if currently blocked
        if token_permission["is_blocked"] and token_permission["block_until"] and current_time < token_permission["block_until"]:
            remaining_time = int(token_permission["block_until"] - current_time)
            return {
                "permission_granted": False,
                "reason": "blocked",
                "remaining_seconds": remaining_time,
                "message": f"Token generation is blocked for {remaining_time} more seconds"
            }
        
        # Clear expired blocks
        if token_permission["is_blocked"] and token_permission["block_until"] and current_time >= token_permission["block_until"]:
            token_permission["is_blocked"] = False
            token_permission["block_until"] = None
            print("🔓 Token generation block expired")
        
        # Grant permission and block for 1 minute
        token_permission["is_blocked"] = True
        token_permission["block_until"] = current_time + 60  # 1 minute block
        token_permission["last_permission_granted"] = current_time
        
        print(f"✅ Token generation permission granted for 1 minute (blocked until {token_permission['block_until']})")
        
        return {
            "permission_granted": True,
            "blocked_until": token_permission["block_until"],
            "message": "Permission granted. You have 1 minute to generate token. Other users are blocked."
        }
        
    except Exception as e:
        print(f"❌ Error handling token permission request: {e}")
        return {
            "permission_granted": False,
            "reason": "error",
            "message": str(e)
        }

class TokenUpdateRequest(BaseModel):
    token: str

@app.post("/update-token")
async def update_token(request: TokenUpdateRequest):
    """Update the API token in cache"""
    try:
        if not request.token or not request.token.strip():
            raise HTTPException(status_code=400, detail="Token cannot be empty")
        
        current_time = time.time()
        
        # Update the token cache
        api_token_cache["token"] = request.token.strip()
        api_token_cache["updated_at"] = int(current_time)
        
        # Update token permission state - block for 10 minutes after receiving token
        token_permission["is_blocked"] = True
        token_permission["block_until"] = current_time + 600  # 10 minutes block
        token_permission["last_token_received"] = current_time
        
        print(f"🔄 API TOKEN UPDATED: {request.token[:20]}... (timestamp: {api_token_cache['updated_at']})")
        print(f"🔒 Token generation blocked for 10 minutes (until {token_permission['block_until']})")
        
        return {
            "status": "success",
            "message": "Token updated successfully. Token generation blocked for 10 minutes.",
            "token_preview": f"{request.token[:20]}...",
            "updated_at": api_token_cache["updated_at"],
            "blocked_until": token_permission["block_until"]
        }
        
    except Exception as e:
        print(f"❌ Error updating token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SeatAvailabilityRequest(BaseModel):
    from_city: str
    to_city: str
    date_of_journey: str
    seat_class: str = "ALL"

class BatchSeatRequest(BaseModel):
    routes: List[Dict[str, str]]  # List of {from_city, to_city} combinations
    date_of_journey: str
    seat_class: str = "ALL"

@app.post("/seat-availability")
async def get_seat_availability(request: SeatAvailabilityRequest):
    """Get seat availability data with in-memory caching logic"""
    
    # Create cache key
    cache_key = f"{request.from_city}_{request.to_city}_{request.date_of_journey}_{request.seat_class}"
    
    # Check if we have cached data in memory
    current_time = datetime.now()
    
    if cache_key in seat_cache:
        cached_entry = seat_cache[cache_key]
        time_passed = int((current_time - cached_entry["timestamp"]).total_seconds() / 60)
        return {
            "isexist": True,
            "rawdata": cached_entry["data"],
            "timepassed": time_passed
        }
    return {
        "isexist": False,
        "rawdata": None,
        "timepassed": None
    }

@app.post("/batch-seat-availability")
async def get_batch_seat_availability(request: BatchSeatRequest):
    """Get seat availability for multiple routes in a single request"""
    
    results = {}
    current_time = datetime.now()
    
    for route in request.routes:
        from_city = route["fromCity"]  # Match Flutter key names
        to_city = route["toCity"]      # Match Flutter key names
        
        # Create cache key for this route
        cache_key = f"{from_city}_{to_city}_{request.date_of_journey}_{request.seat_class}"
        route_key = f"{from_city}_to_{to_city}"
        
        # Check if we have cached data in memory
        if cache_key in seat_cache:
            cached_entry = seat_cache[cache_key]
            time_passed = int((current_time - cached_entry["timestamp"]).total_seconds() / 60)
            results[route_key] = {
                "isexist": True,
                "rawdata": cached_entry["data"],
                "timepassed": time_passed,
                "from_city": from_city,
                "to_city": to_city
            }
        else:
            results[route_key] = {
                "isexist": False,
                "rawdata": None,
                "timepassed": None,
                "from_city": from_city,
                "to_city": to_city
            }
    
    return {
        "total_routes": len(request.routes),
        "results": results
    }

@app.post("/refresh-seat-data")
async def refresh_seat_data(request: SeatAvailabilityRequest):
    """Receive and cache seat data sent from the Flutter app"""
    
    try:
        # The app should send the raw data in the request
        # We'll expect the raw data to be included in the request
        return {
            "status": "success",
            "message": "Please send raw data in the request body"
        }
            
    except Exception as e:
        print(f"Error saving seat data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SeatDataCacheRequest(BaseModel):
    from_city: str
    to_city: str
    date_of_journey: str
    seat_class: str = "ALL"
    rawdata: dict  # The actual seat data from external API

@app.post("/cache-seat-data")
async def cache_seat_data(request: SeatDataCacheRequest):
    """Cache seat data in memory sent from the Flutter app after it fetches from external API"""
    
    try:
        # Create cache key
        cache_key = f"{request.from_city}_{request.to_city}_{request.date_of_journey}_{request.seat_class}"
        
        # Store in memory with 5-minute expiration
        current_time = datetime.now()
        expires_at = current_time + timedelta(minutes=5)
        
        seat_cache[cache_key] = {
            "timestamp": current_time,
            "expires_at": expires_at,
            "data": request.rawdata
        }
        
        print(f"Cached seat data in memory for route: {request.from_city} -> {request.to_city} on {request.date_of_journey}")
        
        return {
            "isexist": True,
            "rawdata": request.rawdata,
            "timepassed": 0,
            "status": "cached_successfully_in_memory"
        }
        
    except Exception as e:
        print(f"Error caching seat data in memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/live", response_class=HTMLResponse)
async def view_live_trains():
    """View all live trains that recently received user data (simple HTML format)"""
    try:
        # Get live trains from the time stack
        confirmed_trains = list(stack.confirmed_position.keys()) if stack.confirmed_position else []
        unconfirmed_trains = list(stack.unconfirmed_position.keys()) if stack.unconfirmed_position else []
        
        # Combine and deduplicate
        all_live_trains = list(set(confirmed_trains + unconfirmed_trains))
        
        # Sort trains by most recent update time (newest first)
        def get_latest_timestamp(train_id):
            confirmed_timestamp = 0
            unconfirmed_timestamp = 0
            
            if train_id in stack.confirmed_position:
                confirmed_timestamp = stack.confirmed_position[train_id][1]
            if train_id in stack.unconfirmed_position:
                unconfirmed_timestamp = stack.unconfirmed_position[train_id][1]
            
            return max(confirmed_timestamp, unconfirmed_timestamp)
        
        all_live_trains.sort(key=get_latest_timestamp, reverse=True)  # Sort by most recent update time
        
        # Get train names from DATA
        train_names = {}
        tid_to_name = DATA.get("tid_to_name", {})
        
        # Generate statistics
        total_live_trains = len(all_live_trains)
        confirmed_count = len(confirmed_trains)
        unconfirmed_count = len(unconfirmed_trains)
        
        # Generate simple HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Find My BR Train - Live Trains</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>🚂 Find My BR Train - Live Trains</h1>
            
            <h2>📊 Live Statistics</h2>
            <ul>
                <li><strong>Total Live Trains:</strong> {total_live_trains}</li>
                <li><strong>Confirmed Positions:</strong> {confirmed_count}</li>
                <li><strong>Unconfirmed Positions:</strong> {unconfirmed_count}</li>
                <li><strong>Data Age:</strong> Last 10 minutes</li>
            </ul>
            
            <h2>🔴 Live Trains ({total_live_trains} trains)</h2>
        """
        
        if not all_live_trains:
            html_content += "<p><em>No trains are currently live (no recent user data).</em></p>"
        else:
            html_content += "<div>"
            
            for i, train_id in enumerate(all_live_trains):
                train_name = tid_to_name.get(train_id, "Unknown Train")
                
                # Determine status
                status = ""
                position_info = ""
                timestamp_info = ""
                
                if train_id in confirmed_trains:
                    status = "✅ Confirmed"
                    if train_id in stack.confirmed_position:
                        position, timestamp = stack.confirmed_position[train_id]
                        position_info = f"Position: {position:.2f}"
                        timestamp_info = f"Updated: {int(time.time() - timestamp)}s ago"
                elif train_id in unconfirmed_trains:
                    status = "⚠️ Unconfirmed"
                    if train_id in stack.unconfirmed_position:
                        position, timestamp = stack.unconfirmed_position[train_id]
                        position_info = f"Position: {position:.2f}"
                        timestamp_info = f"Updated: {int(time.time() - timestamp)}s ago"
                
                html_content += f"""
                <div style="border: 1px solid #ddd; margin: 5px 0; padding: 10px;">
                    <h3>#{i+1}: {train_name} ({train_id})</h3>
                    <p><strong>Status:</strong> {status}</p>
                    <p><strong>{position_info}</strong></p>
                    <p><small>{timestamp_info}</small></p>
                </div>
                """
            
            html_content += "</div>"
        
        html_content += f"""
            <hr>
            <p><small>Last updated: {int(time.time())} | <a href="/live">Refresh</a> | <a href="/health">Health Check</a></small></p>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        return HTMLResponse(content=f"""
        <html>
        <body>
            <h1>Error Loading Live Trains</h1>
            <p>Error: {str(e)}</p>
        </body>
        </html>
        """)

class NearbyRouteRequest(BaseModel):
    from_station: str = Field(alias="from")  
    to: str

@app.post("/nearbyroute")
async def find_nearby_routes(request: NearbyRouteRequest):
    """Find alternative train routes through nearby stations (optimized with precalculated routes and distances)"""
    
    from_station_input = request.from_station.strip()
    to_station_input = request.to.strip()
    
    sid_to_sloc = DATA.get("sid_to_sloc", {})
    
    # Case-insensitive station lookup - create mapping from lowercase to actual station ID
    station_lookup = {station.lower(): station for station in sid_to_sloc.keys()}
    
    # Find the correct station IDs (case-insensitive)
    from_station = station_lookup.get(from_station_input.lower())
    to_station = station_lookup.get(to_station_input.lower())
    
    if from_station is None or to_station is None:
        # Show some similar stations for debugging
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
    
    # Get direct distance from precalculated distances
    direct_distance = None
    if from_station in STATION_DISTANCES:
        for station, distance in STATION_DISTANCES[from_station]:
            if station == to_station:
                direct_distance = distance
                break
    
    if direct_distance is None:
        raise HTTPException(status_code=400, detail="Could not calculate distance between stations")
    
    
    direct_trains = set()
    for train_id, station_ids in TRAIN_ROUTES.items():
        if from_station in station_ids and to_station in station_ids:
            from_index = station_ids.index(from_station)
            to_index = station_ids.index(to_station)
            
            if from_index < to_index:
                direct_trains.add(train_id)
    
    
    search_radius = direct_distance * 0.15  # 15% of direct distance as search radius
    
    
    nearby_from_list = get_nearby_stations(from_station, search_radius)
    nearby_from = {from_station}  
    nearby_from.update(nearby_from_list)
    
    nearby_to_list = get_nearby_stations(to_station, search_radius)
    nearby_to = {to_station}  
    nearby_to.update(nearby_to_list)
    
    
    alternative_trains = {}
    for train_id, station_ids in TRAIN_ROUTES.items():
        if train_id in direct_trains:
            continue  
        
        train_nearby_from = [station for station in station_ids if station in nearby_from]
        train_nearby_to = [station for station in station_ids if station in nearby_to]
        
        if train_nearby_from and train_nearby_to:
            from_indices = [i for i, station in enumerate(station_ids) if station in nearby_from]
            to_indices = [i for i, station in enumerate(station_ids) if station in nearby_to]
            
            # Check if any from station comes before any to station
            if any(from_idx < to_idx for from_idx in from_indices for to_idx in to_indices):
                # Get only the nearest stations
                nearest_from = get_nearest_station(from_station, train_nearby_from)
                nearest_to = get_nearest_station(to_station, train_nearby_to)
                
                # Store the nearest stations this train connects
                alternative_trains[train_id] = {
                    "from_nearby": nearest_from,
                    "to_nearby": nearest_to
                }
    
    
    return {
        "alternative_trains": alternative_trains,
        "total_alternative_routes": len(alternative_trains)
    }

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Find My BR Train FastAPI Server",
        "version": "1.0.0",
        "framework": "FastAPI",
        "endpoints": {
            "/initrevision": "GET - Check data revision",
            "/alltrains": "GET - Download complete database",
            "/current/{train_ids}": "GET - Get current train positions",
            "/sendupdate": "POST - Submit location update",
            "/fix": "POST - Report incorrect information",
            "/report": "GET - View all issue reports in webpage",
            "/nearbyroute": "POST - Find alternative routes through nearby stations",
            "/health": "GET - Server health check",
            "/token": "GET - Return API token from cache or environment",
            "/request-token-permission": "GET - Request permission to generate new token",
            "/update-token": "POST - Update API token in cache",
            "/seat-availability": "POST - Get seat availability with caching",
            "/cache-seat-data": "POST - Cache seat data sent from Flutter app",
            "/docs": "GET - Interactive API documentation",
        },
        "github": "https://github.com/jisangain/find-my-br-train",
        "contribute": "Visit our GitHub repository to contribute!"
    }


if __name__ == '__main__':
    uvicorn.run(
        "main:app",
        host='0.0.0.0',
        port=8000,
        reload=False,  # Disable reload to prevent issues with background threads
        log_level="info"
    )
