import os
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Set default train moderator if not set
os.environ["train_mod"] = os.getenv("train_mod", "user_2052")

class TrainChatManager:
    def __init__(self):
        # Maps train_id -> set of active WebSockets
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, train_id: str, websocket: WebSocket):
        await websocket.accept()
        if train_id not in self.active_connections:
            self.active_connections[train_id] = set()
        self.active_connections[train_id].add(websocket)

    def disconnect(self, train_id: str, websocket: WebSocket):
        if train_id in self.active_connections:
            self.active_connections[train_id].discard(websocket)
            if not self.active_connections[train_id]:
                del self.active_connections[train_id]

    async def broadcast(self, train_id: str, message: dict):
        if train_id in self.active_connections:
            for connection in list(self.active_connections[train_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.active_connections[train_id].discard(connection)

def register_chat_endpoint(app: FastAPI, tracker):
    """
    Registers the WebSocket chat endpoint to the FastAPI app.
    Reuses the Redis client from the provided tracker.
    """
    chat_manager = TrainChatManager()

    @app.websocket("/chat/{train_id}")
    async def websocket_chat_endpoint(
        websocket: WebSocket, 
        train_id: str, 
        user_id: str = "unknown", 
        inside_train: str = "false"
    ):
        # Parse inside_train robustly
        is_inside = False
        if isinstance(inside_train, bool):
            is_inside = inside_train
        elif isinstance(inside_train, str):
            is_inside = inside_train.lower() in ("true", "1", "yes")

        # Reduce the last 2 digits of user_id and capitalize 'U'
        short_user_id = user_id[:-2] if len(user_id) > 2 else user_id
        if short_user_id.startswith("user_"):
            display_user = "User_" + short_user_id[5:]
        elif short_user_id.startswith("user"):
            display_user = "User" + short_user_id[4:]
        else:
            display_user = short_user_id.capitalize() if short_user_id else ""

        train_mod = os.getenv("train_mod", "user_2052")
        if short_user_id == train_mod:
            nickname = "Moderator"
        elif is_inside:
            nickname = f"{display_user}(Inside Train)"
        else:
            nickname = display_user

        await chat_manager.connect(train_id, websocket)

        current_time = int(time.time())
        chat_key = f"train:{train_id}:chat"
        redis_client = tracker.redis

        try:
            # Prune old messages (older than 10 hours)
            redis_client.zremrangebyscore(chat_key, "-inf", current_time - 36000)

            # Retrieve history (past 10 hours)
            history_raw = redis_client.zrangebyscore(chat_key, current_time - 36000, "+inf")
            history = []
            for msg in history_raw:
                try:
                    history.append(json.loads(msg))
                except Exception:
                    pass

            # Send history to the newly connected user
            await websocket.send_json({
                "type": "history",
                "messages": history
            })

            while True:
                # Wait for text from the socket
                data = await websocket.receive_text()
                if not data:
                    continue

                try:
                    msg_payload = json.loads(data)
                    text = msg_payload.get("text", "")
                except (ValueError, TypeError):
                    # Fallback to plain text if not valid JSON
                    text = data

                if not text or not text.strip():
                    continue

                msg_time = int(time.time())
                new_message = {
                    "type": "message",
                    "sender": nickname,
                    "user_id": user_id,
                    "text": text.strip(),
                    "timestamp": msg_time
                }

                # Prune and Save to Redis, set expiry on the key (10 hours)
                redis_client.zremrangebyscore(chat_key, "-inf", msg_time - 36000)
                redis_client.zadd(chat_key, {json.dumps(new_message): msg_time})
                redis_client.expire(chat_key, 36000)

                # Broadcast message
                await chat_manager.broadcast(train_id, new_message)

        except WebSocketDisconnect:
            pass
        finally:
            chat_manager.disconnect(train_id, websocket)
