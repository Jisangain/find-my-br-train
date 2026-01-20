# main.py - Simplified FastAPI application
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import uvicorn

# Import utility functions
from functions.data_loader import load_data
from functions.train_stack import AsyncTimedStack, periodic_clean_and_preprocess
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
train_positions_confirmed = {}
train_positions_unconfirmed = {}
stack = AsyncTimedStack(max_age_seconds=600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    global TWO_TRAIN_ROUTES, TRAIN_ROUTES, STATION_DISTANCES
    
    print("Starting Find My BR Train FastAPI Server...")
    print("API Base URL: train.sportsprime.live")
    print("Health Check: train.sportsprime.live/health")
    print("\nPress Ctrl+C to stop the server\n")
    
    # Precalculate routes and distances
    TRAIN_ROUTES = precalculate_train_routes(DATA)
    STATION_DISTANCES = precalculate_station_distances(DATA)
    
    print("\n" + "="*60)
    print("INITIALIZING TWO-TRAIN ROUTE PRECALCULATION")
    print("="*60)
    TWO_TRAIN_ROUTES = precalculate_two_train_routes(DATA, CURRENT_REVISION)
    print("="*60 + "\n")
    
    # Start background tasks
    task1 = asyncio.create_task(periodic_clean_and_preprocess(stack, interval_seconds=30))
    
    yield
    
    # Cleanup
    task1.cancel()
    try:
        await task1
    except asyncio.CancelledError:
        print("Consumer task cancelled cleanly")
    
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
    return await positions.get_current_positions(train_ids, stack)


@app.post("/sendupdate")
async def receive_update_handler(update: positions.LocationUpdate):
    return await positions.receive_update(update, stack)


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
    return await live.health_check(CURRENT_REVISION, train_positions_confirmed, train_positions_unconfirmed)


@app.get("/live")
async def view_live_trains_handler():
    return await live.view_live_trains(stack, DATA)


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
