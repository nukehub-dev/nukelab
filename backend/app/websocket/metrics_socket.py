import json
import asyncio
from typing import Set, Dict
from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as redis
from app.config import settings

# Track active connections
connections: Dict[str, Set[WebSocket]] = {}


class MetricsWebSocketManager:
    """Manages WebSocket connections and metric broadcasting"""

    def __init__(self):
        self.redis_client = None
        self._pubsub_task = None
        self._running = False

    async def get_redis(self):
        if not self.redis_client:
            self.redis_client = redis.from_url(settings.redis_url)
        return self.redis_client

    async def start_redis_listener(self):
        """Start listening to Redis pub/sub for metrics"""
        if self._running:
            return
        self._running = True

        try:
            redis_client = await self.get_redis()
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("metrics:all", "metrics:system")

            async for message in pubsub.listen():
                if not self._running:
                    break
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        channel = message.get('channel', '').decode() if isinstance(message.get('channel'), bytes) else message.get('channel', '')
                        if channel == 'metrics:system':
                            await self._broadcast_system_metric(data)
                        else:
                            await self._broadcast_metric(data)
                    except Exception as e:
                        print(f"Error broadcasting metric: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Redis listener error: {e}")

    async def stop_redis_listener(self):
        self._running = False

    async def _broadcast_metric(self, metric: dict):
        """Broadcast metric to subscribed clients"""
        server_id = metric.get('server_id')
        disconnected = []

        # Broadcast to server-specific subscribers
        if server_id:
            room = f"server:{server_id}"
            if room in connections:
                for ws in connections[room]:
                    try:
                        await ws.send_json({
                            "event": "metrics:server",
                            "data": metric
                        })
                    except Exception:
                        disconnected.append((room, ws))

        # Broadcast to global subscribers
        if "global" in connections:
            for ws in connections["global"]:
                try:
                    await ws.send_json({
                        "event": "metrics:all",
                        "data": metric
                    })
                except Exception:
                    disconnected.append(("global", ws))

        # Clean up disconnected clients
        for room, ws in disconnected:
            if room in connections:
                connections[room].discard(ws)
                if not connections[room]:
                    connections.pop(room, None)

    async def _broadcast_system_metric(self, metric: dict):
        """Broadcast system metric to all connected clients"""
        disconnected = []
        
        # Broadcast to all rooms
        for room, clients in list(connections.items()):
            for ws in clients:
                try:
                    await ws.send_json({
                        "event": "metrics:system",
                        "data": metric
                    })
                except Exception:
                    disconnected.append((room, ws))
        
        # Clean up disconnected clients
        for room, ws in disconnected:
            if room in connections:
                connections[room].discard(ws)
                if not connections[room]:
                    connections.pop(room, None)

    async def handle_connection(self, websocket: WebSocket):
        """Handle a new WebSocket connection"""
        await websocket.accept()

        try:
            while True:
                message = await websocket.receive_text()
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')

                    if msg_type == 'subscribe':
                        scope = data.get('scope', 'global')
                        target_id = data.get('target_id')

                        if scope == 'server' and target_id:
                            room = f"server:{target_id}"
                        elif scope == 'user' and target_id:
                            room = f"user:{target_id}"
                        else:
                            room = "global"

                        if room not in connections:
                            connections[room] = set()
                        connections[room].add(websocket)

                        await websocket.send_json({
                            "event": "subscribed",
                            "scope": scope,
                            "target_id": target_id
                        })

                    elif msg_type == 'unsubscribe':
                        scope = data.get('scope', 'global')
                        target_id = data.get('target_id')

                        if scope == 'server' and target_id:
                            room = f"server:{target_id}"
                        elif scope == 'user' and target_id:
                            room = f"user:{target_id}"
                        else:
                            room = "global"

                        if room in connections:
                            connections[room].discard(websocket)
                            if not connections[room]:
                                connections.pop(room, None)

                        await websocket.send_json({
                            "event": "unsubscribed",
                            "scope": scope,
                            "target_id": target_id
                        })

                except json.JSONDecodeError:
                    await websocket.send_json({
                        "event": "error",
                        "message": "Invalid JSON"
                    })

        except WebSocketDisconnect:
            # Clean up on disconnect
            for room in list(connections.keys()):
                connections[room].discard(websocket)
                if not connections[room]:
                    connections.pop(room, None)
        except Exception as e:
            print(f"WebSocket error: {e}")
            # Clean up on error
            for room in list(connections.keys()):
                connections[room].discard(websocket)
                if not connections[room]:
                    connections.pop(room, None)


manager = MetricsWebSocketManager()
