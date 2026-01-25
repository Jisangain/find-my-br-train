# main.py - Simplified FastAPI application
from fastapi import FastAPI, Request
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
    print("API Base URL: train.sportsprime.live")
    print("Health Check: train.sportsprime.live/health")
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


# ============= ROUTES =============

# GitHub webhook
@app.post("/payload")
async def github_webhook_handler(request: Request):
    return await github.github_webhook(request)


# Data endpoints
@app.get("/initrevision")
async def get_revision():
    return data.get_revision(CURRENT_REVISION)


@app.get("/alltrains")
async def get_all_trains():
    return data.get_all_trains(DATA)


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
            "/current/{train_ids}": "GET - Get current train positions",
            "/sendupdate": "POST - Submit location update",
            "/fix": "POST - Report incorrect information",
            "/report": "GET - View all issue reports",
            "/nearbyroute": "POST - Find alternative routes",
            "/health": "GET - Server health check",
            "/live": "GET - View live trains",
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
        reload=False,
        log_level="info"
    )
