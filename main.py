# main.py - Simplified FastAPI application
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

# Import utility functions
from functions.data_loader import load_data
from functions.redis_tracker import RedisTrainTracker
from functions.route_calculator import (
    precalculate_train_routes,
    precalculate_station_distances,
    precalculate_two_train_routes
)

# Import URL handlers
from urls import github, data, positions, routes, reports, live


# Global variables
DATA, CURRENT_REVISION = load_data()

import hashlib
import json
import os
from urls.data import get_all_trains

DATA_HASHES = {}

def precalculate_data_hashes():
    print("Precalculating data hashes...")
    
    # Base hash (for versions < 28)
    base_data = get_all_trains(DATA, version=0)
    DATA_HASHES[0] = hashlib.sha256(json.dumps(base_data, sort_keys=True).encode("utf-8")).hexdigest()
    
    # Precalculate version 28 specifically as it's the fallback
    v28_data = get_all_trains(DATA, version=28)
    DATA_HASHES[28] = hashlib.sha256(json.dumps(v28_data, sort_keys=True).encode("utf-8")).hexdigest()
    
    # Version hashes based on directories
    if os.path.exists("train_routes"):
        for folder in os.listdir("train_routes"):
            if folder.startswith("version"):
                try:
                    version_num = int(folder.replace("version", ""))
                    if version_num not in DATA_HASHES:
                        v_data = get_all_trains(DATA, version=version_num)
                        DATA_HASHES[version_num] = hashlib.sha256(json.dumps(v_data, sort_keys=True).encode("utf-8")).hexdigest()
                except ValueError:
                    pass
    print(f"Hashes precalculated for versions: {list(DATA_HASHES.keys())}")

precalculate_data_hashes()

TWO_TRAIN_ROUTES = {}
TRAIN_ROUTES = {}
STATION_DISTANCES = {}

# Redis-based train tracker (replaces AsyncTimedStack)
tracker = RedisTrainTracker(host="localhost", port=6379, db=0, ttl_seconds=600)
tracker.set_train_data(DATA)  # Provide train schedule data for scheduled position calculation

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    global TWO_TRAIN_ROUTES, TRAIN_ROUTES, STATION_DISTANCES
    
    print("Starting Find My BR Train FastAPI Server...")
    print("API Base URL: findmytrain.freeddns.org")
    print("Health Check: findmytrain.freeddns.org/health")
    print("\nPress Ctrl+C to stop the server\n")
    
    # Check Redis connection
    if tracker.health_check():
        print("✓ Redis connection established")
    else:
        print("⚠ Warning: Redis connection failed - position tracking won't work!")
    
    # Precalculate routes and distances
    TRAIN_ROUTES = precalculate_train_routes(DATA)
    STATION_DISTANCES = precalculate_station_distances(DATA)
    
    print("\n" + "="*60)
    print("INITIALIZING TWO-TRAIN ROUTE PRECALCULATION")
    print("="*60)
    TWO_TRAIN_ROUTES = precalculate_two_train_routes(DATA, CURRENT_REVISION)
    print("="*60 + "\n")
    
    yield
    
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

# Add Apitally middleware (reads from environment variables)
from apitally.fastapi import ApitallyMiddleware
apitally_client_id = os.getenv("APITALLY_CLIENT_ID")
apitally_env = os.getenv("APITALLY_ENV", "prod")

app.add_middleware(
    ApitallyMiddleware,
    client_id=apitally_client_id,
    env=apitally_env,
    enable_request_logging=True,
    log_request_headers=True,
    log_request_body=True,
    log_response_body=True,
    capture_logs=True,
)



# Mount static files
import os
if os.path.exists("train_routes"):
    app.mount("/train_routes", StaticFiles(directory="train_routes"), name="train_routes")
if os.path.exists(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")


# ============= ROUTES =============

# GitHub webhook
@app.post("/payload")
async def github_webhook_handler(request: Request):
    return await github.github_webhook(request)


# Data endpoints
from typing import Optional

@app.get("/initrevision")
async def get_revision(version: Optional[int] = None):
    return data.get_revision(CURRENT_REVISION, DATA_HASHES, version)


@app.get("/alltrains")
async def get_all_trains(request: Request, version: int = 0):
    from fastapi.responses import Response
    import gzip
    import json

    result = data.get_all_trains(DATA, version)

    if version >= 29:
        # Inject hash using same max-Y <= version logic
        valid_versions = [v for v in DATA_HASHES.keys() if v <= version and v != 0]
        if valid_versions:
            result["hash"] = DATA_HASHES[max(valid_versions)]
        elif 0 in DATA_HASHES:
            result["hash"] = DATA_HASHES[0]

        if "gzip" in request.headers.get("accept-encoding", ""):
            compressed_data = gzip.compress(json.dumps(result, separators=(",", ":")).encode("utf-8"))
            return Response(
                content=compressed_data,
                media_type="application/json",
                headers={"Content-Encoding": "gzip"}
            )

    return result


# Position endpoints
@app.get("/current/{train_ids}")
async def get_current_positions_handler(train_ids: str):
    return positions.get_current_positions(train_ids, tracker)


@app.get("/bounds/{train_id}")
async def get_train_bounds_handler(train_id: str):
    """Get current bounds for a train (set by bot users)"""
    return positions.get_train_bounds(train_id, tracker)


@app.post("/sendupdate")
async def receive_update_handler(update: positions.LocationUpdate):
    return positions.receive_update(update, tracker)


# Route endpoints
@app.get("/two-train-routes/{from_station}/{to_station}")
async def get_two_train_routes_handler(from_station: str, to_station: str):
    return routes.get_two_train_routes(from_station, to_station, TWO_TRAIN_ROUTES, DATA)


@app.get("/two-train-routes-all")
async def get_all_two_train_routes_handler():
    return routes.get_all_two_train_routes(TWO_TRAIN_ROUTES, DATA)


@app.post("/nearbyroute")
async def find_nearby_routes_handler(request: routes.NearbyRouteRequest):
    return await routes.find_nearby_routes(request, DATA, TRAIN_ROUTES, STATION_DISTANCES)


# Report endpoints
@app.post("/fix")
async def report_issue_handler(report: reports.IssueReport):
    return await reports.report_issue_post(report)


@app.get("/report")
async def view_reports_handler():
    return await reports.view_reports()


# Live endpoints
@app.get("/health")
async def health_check_handler():
    return live.health_check(CURRENT_REVISION, tracker)


@app.get("/live")
async def view_live_trains_handler():
    return live.view_live_trains(tracker, DATA)


@app.get("/activetrains")
async def get_active_trains_handler():
    return live.get_active_trains_details(tracker)


# Root endpoint
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
            "/activetrains": "GET - Get active trains details",
            "/current/{train_ids}": "GET - Get current train positions",
            "/sendupdate": "POST - Submit location update",
            "/fix": "POST - Report incorrect information",
            "/report": "GET - View all issue reports",
            "/nearbyroute": "POST - Find alternative routes",
            "/health": "GET - Server health check",
            "/live": "GET - View live trains",
            "/location-improver": "GET/POST - Location Improver dashboard and receiver",
            "/docs": "GET - Interactive API documentation",
        },
        "github": "https://github.com/jisangain/find-my-br-train",
        "contribute": "Visit our GitHub repository to contribute!"
    }


from collections import deque
from fastapi.responses import HTMLResponse
import datetime

IMPROVER_LOCATIONS = deque(maxlen=500)

@app.post("/location-improver")
async def post_location_improver(request: Request, train_id: Optional[str] = None):
    try:
        body = await request.json()
        x = body.get("x")
        y = body.get("y")
        user_id = body.get("user_id", "unknown")
        req_train_id = body.get("train_id")
        if req_train_id is None:
            req_train_id = train_id or "unknown"
            
        if x is not None and y is not None:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            IMPROVER_LOCATIONS.appendleft({
                "x": x,
                "y": y,
                "user_id": user_id,
                "train_id": req_train_id,
                "timestamp": timestamp
            })
            return {"status": "success", "message": "Location recorded"}
        else:
            return {"status": "error", "message": "Missing x or y coordinate"}
    except Exception as e:
        return {"status": "error", "message": f"Server error: {str(e)}"}

@app.get("/location-improver", response_class=HTMLResponse)
async def get_location_improver_dashboard():
    rows_html = ""
    for idx, item in enumerate(IMPROVER_LOCATIONS, 1):
        x = item['x']
        y = item['y']
        user_id = item['user_id']
        t_id = item['train_id']
        ts = item['timestamp']
        osm_url = f"https://www.openstreetmap.org/?mlat={x}&mlon={y}#map=16/{x}/{y}"
        gmaps_url = f"https://maps.google.com/?q={x},{y}"
        
        rows_html += f"""
        <tr class="border-b border-white/10 hover:bg-white/5 transition duration-150">
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-400 font-medium">{idx}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-100"><span class="bg-indigo-500/20 text-indigo-300 px-2 py-1 rounded text-xs font-mono font-bold">{user_id}</span></td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-100"><span class="bg-purple-500/20 text-purple-300 px-2 py-1 rounded text-xs font-mono font-bold">{t_id}</span></td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300 font-mono">{x}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300 font-mono">{y}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-400 font-mono">{ts}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm space-x-2">
                <a href="{osm_url}" target="_blank" class="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-indigo-200 bg-indigo-900/50 hover:bg-indigo-900 transition duration-150">🌐 OSM</a>
                <a href="{gmaps_url}" target="_blank" class="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-emerald-200 bg-emerald-900/50 hover:bg-emerald-900 transition duration-150">📍 Maps</a>
            </td>
        </tr>
        """
        
    if not IMPROVER_LOCATIONS:
        rows_html = """
        <tr>
            <td colspan="7" class="px-6 py-12 text-center text-gray-500 text-sm font-medium">
                📭 No location reports captured in memory yet.
            </td>
        </tr>
        """

    progress_percent = (len(IMPROVER_LOCATIONS) / 500) * 100
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Bangladesh Railway - Location Improver Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Outfit', sans-serif;
                background-color: #0b0f19;
                background-image: 
                    radial-gradient(at 0% 0%, rgba(30, 27, 75, 0.4) 0, transparent 50%),
                    radial-gradient(at 50% 0%, rgba(17, 24, 39, 0.4) 0, transparent 50%),
                    radial-gradient(at 100% 0%, rgba(4, 120, 87, 0.1) 0, transparent 50%);
                background-attachment: fixed;
            }}
            .glass {{
                background: rgba(255, 255, 255, 0.03);
                backdrop-filter: blur(12px);
                border: 1px border-white/10;
            }}
        </style>
    </head>
    <body class="text-white min-h-screen">
        <div class="max-w-6xl mx-auto px-4 py-8">
            <!-- Header -->
            <div class="flex flex-col md:flex-row md:items-center md:justify-between mb-8 pb-6 border-b border-white/10">
                <div>
                    <h1 class="text-3xl font-bold bg-gradient-to-r from-indigo-400 via-purple-400 to-emerald-400 bg-clip-text text-transparent">🇧🇩 Bangladesh Railway</h1>
                    <p class="text-gray-400 mt-1 text-sm font-medium">Location Improver Dashboard (RAM Cache)</p>
                </div>
                <div class="mt-4 md:mt-0 flex items-center space-x-4">
                    <button onclick="window.location.reload()" class="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium hover:bg-white/10 transition duration-150">🔄 Refresh</button>
                    <span class="px-3 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-full text-xs font-semibold animate-pulse flex items-center space-x-1">
                        <span class="h-2 w-2 bg-emerald-400 rounded-full inline-block"></span>
                        <span>Live</span>
                    </span>
                </div>
            </div>

            <!-- Stats Overview -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="glass p-6 rounded-2xl border border-white/10 shadow-xl flex flex-col justify-between">
                    <h3 class="text-gray-400 text-sm font-semibold uppercase tracking-wider">Reports Stored</h3>
                    <div class="mt-2 flex items-baseline">
                        <span class="text-4xl font-bold font-mono">{len(IMPROVER_LOCATIONS)}</span>
                        <span class="text-gray-500 text-lg font-medium ml-1">/ 500 max</span>
                    </div>
                    <div class="w-full bg-white/10 h-1.5 rounded-full mt-4 overflow-hidden">
                        <div class="bg-gradient-to-r from-indigo-500 to-purple-500 h-1.5 rounded-full" style="width: {progress_percent}%"></div>
                    </div>
                </div>
                
                <div class="glass p-6 rounded-2xl border border-white/10 shadow-xl flex flex-col justify-between">
                    <h3 class="text-gray-400 text-sm font-semibold uppercase tracking-wider">Feature Status</h3>
                    <div class="mt-2">
                        <span class="text-lg font-semibold inline-flex items-center text-indigo-300">
                            ✨ Capturing All Reports
                        </span>
                    </div>
                    <p class="text-xs text-gray-500 mt-4">Storing incoming coordinate reports in temporary memory.</p>
                </div>
                
                <div class="glass p-6 rounded-2xl border border-white/10 shadow-xl flex flex-col justify-between">
                    <h3 class="text-gray-400 text-sm font-semibold uppercase tracking-wider">System Target</h3>
                    <div class="mt-2">
                        <span class="text-lg font-semibold inline-flex items-center text-emerald-400">
                            🛠️ Missing Stations Audit
                        </span>
                    </div>
                    <p class="text-xs text-gray-500 mt-4">Cross-references raw coords with geocoding tools to build/correct schedules.</p>
                </div>
            </div>

            <!-- Data Table -->
            <div class="glass rounded-2xl border border-white/10 shadow-2xl overflow-hidden">
                <div class="px-6 py-5 border-b border-white/10">
                    <h3 class="text-lg font-semibold">📍 Captured Coordinates Stream</h3>
                    <p class="text-gray-400 text-xs">Displays the 500 most recent coordinate anomalies sent by apps in real-time.</p>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-white/10">
                        <thead class="bg-white/5">
                            <tr>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">#</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">User ID</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Train ID</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Latitude (X)</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Longitude (Y)</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Timestamp</th>
                                <th scope="col" class="px-6 py-3 text-left text-xs font-semibold text-gray-300 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-white/10 bg-transparent">
                            {rows_html}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)



if __name__ == '__main__':
    uvicorn.run(
        "main:app",
        host='0.0.0.0',
        port=8000,
        reload=False,
        log_level="info"
    )
