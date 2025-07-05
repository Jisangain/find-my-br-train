# main.py
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
            return data['DATA'], data['CURRENT_REVISION']
    except FileNotFoundError:
        print("Warning: data.json not found, using fallback data")
        # Fallback data in case JSON file is missing
        return {
            "Revision": 0,
            "online_user_update_delay": 10,
            "update_delay": 20,
            "sid_to_sname": {"001": "dhaka", "002": "chittagong"},
            "sid_to_sloc": {"001": [24.7119, 92.8954], "002": [22.3569, 91.7832]},
            "train_names": {"101": "Test Express"},
            "tid_to_stations": {"101": [["001", 1, "22:30"], ["002", 1, "01:45"]]}
        }, 127


class TimedItem:
    def __init__(self, value: dict):
        self.timestamp = value["timestamp"]
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
                for train_id, position in self._trains.items():
                    if len(position) == 1:
                        self.unconfirmed_position[train_id] = [position[0][0], position[0][1]]
                    elif len(position) == 2:
                        self.unconfirmed_position[train_id] = [(position[0][0] + position[0][1]) / 2.0, max(position[0][1], position[1][1])]
                    elif len(position) == 3:
                        self.unconfirmed_position[train_id] = [(position[-2] + position[-3]) / 2.0, max(position[-2][1], position[-3][1])]
                    


                    if len(position) > 3:
                        n = len(position)
                        k = int(0.67 * n)
                        best_i = 0
                        best_span = position[k-1] - position[0]

                        for i in range(1, n - k + 1):
                            span = position[i + k - 1] - position[i]
                            if span < best_span:
                                best_span = span
                                best_i = i
                        slice = position[best_i : best_i + k]
                        mid_index = k // 2
                        timestamp = max(item[1] for item in slice)
                        middle_value = (
                            slice[mid_index]
                            if k % 2 == 1
                            else 0.5 * (slice[mid_index - 1] + slice[mid_index])
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
                        "timestamp": timestamp
                    }

                # Add unconfirmed position if exists
                if train_id in self.unconfirmed_position and self.unconfirmed_position[train_id]:
                    position, timestamp = self.unconfirmed_position[train_id]
                    train_data["unconfirmed"] = {
                        "position": position,
                        "timestamp": timestamp
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
    
    print("   ✅ Issue report logged successfully\n")
    
    # Append the report to a file for persistence
    try:
        with open("issue_reports.log", "a") as f:
            f.write(json.dumps(report.model_dump()) + "\n")
    except Exception as e:
        print(f"Failed to write issue report to file: {e}")

    return {"status": "success", "message": "Issue report received"}

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
            "/health": "GET - Server health check",
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