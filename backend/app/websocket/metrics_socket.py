import json
import asyncio
from typing import Set, Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.server import Server
from app.core.permissions import Permission
from app.core.roles import get_role_permissions

# Track active connections
connections: Dict[str, Set[WebSocket]] = {}

# Track authenticated users per connection
connection_users: Dict[WebSocket, dict] = {}


async def validate_websocket_token(websocket: WebSocket) -> Optional[User]:
    """Validate JWT token from WebSocket query parameters"""
    token = websocket.query_params.get('token')
    
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        if not username:
            return None
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.username == username))
            return result.scalar_one_or_none()
    except (JWTError, Exception):
        return None


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission"""
    user_permissions = get_role_permissions(user.role)
    return Permission.ALL in user_permissions or permission in user_permissions


async def check_server_access(user: User, server_id: str, db: AsyncSession) -> bool:
    """Check if user can access a specific server"""
    # Admin/moderator/support with read_all can access any server
    if has_permission(user, Permission.SERVERS_READ_ALL) or has_permission(user, Permission.SERVERS_MANAGE):
        return True
    
    # Check if user owns the server
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()
    
    if server and str(server.user_id) == str(user.id):
        return True
    
    return False


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
            # Subscribe to specific channels and pattern for all metrics
            await pubsub.subscribe("metrics:all", "metrics:system")
            await pubsub.psubscribe("metrics:server:*")

            async for message in pubsub.listen():
                if not self._running:
                    break
                if message['type'] in ('message', 'pmessage'):
                    try:
                        data = json.loads(message['data'])
                        channel = message.get('channel', '').decode() if isinstance(message.get('channel'), bytes) else message.get('channel', '')
                        if channel == 'metrics:system' or 'metrics:system' in str(channel):
                            await self._broadcast_system_metric(data)
                        else:
                            await self._broadcast_metric(data)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

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
        """Broadcast system metric to global subscribers only"""
        disconnected = []
        
        # Only broadcast to global room (admin-only)
        if "global" in connections:
            for ws in connections["global"]:
                try:
                    await ws.send_json({
                        "event": "metrics:system",
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

    async def handle_connection(self, websocket: WebSocket):
        """Handle a new WebSocket connection with authentication"""
        
        # Authenticate the connection
        user = await validate_websocket_token(websocket)
        
        if not user:
            await websocket.accept()
            await websocket.send_json({
                "event": "error",
                "message": "Authentication required"
            })
            await websocket.close(code=4001, reason="Authentication required")
            return
        
        await websocket.accept()
        
        # Store user data for this connection
        connection_users[websocket] = {
            'user_id': str(user.id),
            'username': user.username,
            'role': user.role,
        }

        try:
            while True:
                message = await websocket.receive_text()
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')

                    if msg_type == 'subscribe':
                        scope = data.get('scope', 'global')
                        target_id = data.get('target_id')

                        # Check permissions based on scope
                        allowed = False
                        room = "global"

                        if scope == 'server' and target_id:
                            room = f"server:{target_id}"
                            # Check server access
                            async with AsyncSessionLocal() as db:
                                allowed = await check_server_access(user, target_id, db)
                            if not allowed:
                                await websocket.send_json({
                                    "event": "error",
                                    "message": "Access denied to this server"
                                })
                                continue

                        elif scope == 'user' and target_id:
                            room = f"user:{target_id}"
                            # Users can only subscribe to their own user channel
                            # Admins/moderators can subscribe to any
                            if str(target_id) == str(user.id):
                                allowed = True
                            elif has_permission(user, Permission.USERS_READ):
                                allowed = True
                            else:
                                await websocket.send_json({
                                    "event": "error",
                                    "message": "Access denied to this user channel"
                                })
                                continue

                        elif scope == 'global':
                            room = "global"
                            # Only admins can subscribe to global system metrics
                            if has_permission(user, Permission.ADMIN_ACCESS):
                                allowed = True
                            else:
                                await websocket.send_json({
                                    "event": "error",
                                    "message": "Admin access required for global metrics"
                                })
                                continue
                        else:
                            # Unknown scope
                            await websocket.send_json({
                                "event": "error",
                                "message": f"Unknown scope: {scope}"
                            })
                            continue

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
            pass
        except Exception:
            pass
        finally:
            # Clean up on disconnect/error
            connection_users.pop(websocket, None)
            for room in list(connections.keys()):
                connections[room].discard(websocket)
                if not connections[room]:
                    connections.pop(room, None)


manager = MetricsWebSocketManager()
