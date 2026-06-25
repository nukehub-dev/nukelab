import asyncio
import contextlib
import json
import logging
import time

import jwt
import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.permissions import Permission
from app.core.prometheus_metrics import set_active_websocket_connections
from app.core.roles import get_role_permissions
from app.db.session import AsyncSessionLocal
from app.models.server import Server
from app.models.user import User

logger = logging.getLogger(__name__)

# Role → WebSocket message RPM limits
_WS_MSG_LIMITS = {
    "guest": settings.rate_limit_guest_rpm,
    "user": settings.rate_limit_user_rpm,
    "support": settings.rate_limit_support_rpm,
    "moderator": settings.rate_limit_moderator_rpm,
    "admin": settings.rate_limit_admin_rpm,
    "super_admin": settings.rate_limit_super_admin_rpm,
}

# Atomic Lua: INCR + conditional EXPIRE
_LUA_INCR_EXPIRE = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local exists = redis.call('EXISTS', key)
local count = redis.call('INCR', key)
if exists == 0 then
    redis.call('EXPIRE', key, ttl)
end
return count
"""

# Track active connections
connections: dict[str, set[WebSocket]] = {}

# Track authenticated users per connection
connection_users: dict[WebSocket, dict] = {}

# Track active log streaming tasks
log_streams: dict[str, asyncio.Task] = {}


def _update_active_websocket_connections() -> None:
    """Update Prometheus gauge with total active WebSocket connections."""
    total = sum(len(ws_set) for ws_set in connections.values())
    set_active_websocket_connections(total)


async def stream_logs_to_websocket(
    websocket: WebSocket, server_id: str, container_id: str, tail: int = 100
):
    """Stream container logs to a WebSocket connection"""
    from app.container.client import get_container_client

    try:
        container_client = await get_container_client()
        container = await container_client.client.containers.get(container_id)

        # Send initial message
        await websocket.send_json(
            {"event": "logs:started", "server_id": server_id, "message": "Log streaming started"}
        )

        # Stream logs
        logs = await container.log(
            stdout=True, stderr=True, tail=tail, follow=True, timestamps=True
        )

        async for line in logs:
            if websocket not in connection_users:
                break

            room = f"logs:{server_id}"
            if room not in connections or websocket not in connections.get(room, set()):
                break

            try:
                await websocket.send_json(
                    {"event": "logs:data", "server_id": server_id, "data": line}
                )
            except Exception:
                break

    except Exception as e:
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"event": "logs:error", "server_id": server_id, "error": str(e)}
            )
    finally:
        # Clean up
        room = f"logs:{server_id}"
        if room in connections:
            connections[room].discard(websocket)
            if not connections[room]:
                connections.pop(room, None)

        task_key = f"{id(websocket)}:{server_id}"
        if task_key in log_streams:
            log_streams.pop(task_key, None)


async def validate_token(token: str) -> User | None:
    """Validate a JWT token string and return the user."""
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
    except (jwt.InvalidTokenError, Exception):
        return None


async def validate_websocket_token(websocket: WebSocket) -> User | None:
    """Validate JWT token from WebSocket query parameters"""
    return await validate_token(websocket.query_params.get("token") or "")


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission"""
    user_permissions = get_role_permissions(user.role)
    return Permission.ALL in user_permissions or permission in user_permissions


async def check_server_access(user: User, server_id: str, db: AsyncSession) -> bool:
    """Check if user can access a specific server"""
    # Admin/moderator/support with read_all can access any server
    if has_permission(user, Permission.SERVERS_READ_ALL) or has_permission(
        user, Permission.SERVERS_WRITE_ALL
    ):
        return True

    # Check if user owns the server
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    return bool(server and str(server.user_id) == str(user.id))


class MetricsWebSocketManager:
    """Manages WebSocket connections and metric broadcasting"""

    def __init__(self):
        self.redis_client = None
        self._pubsub_task = None
        self._running = False
        self._shutting_down = False

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
            await pubsub.psubscribe("metrics:server:*", "user:*")

            async for message in pubsub.listen():
                if not self._running:
                    break
                if message["type"] in ("message", "pmessage"):
                    try:
                        data = json.loads(message["data"])
                        channel = (
                            message.get("channel", "").decode()
                            if isinstance(message.get("channel"), bytes)
                            else message.get("channel", "")
                        )
                        channel_str = str(channel)
                        if channel_str.startswith("user:"):
                            await self._broadcast_user_event(data)
                        elif channel == "metrics:system" or "metrics:system" in channel_str:
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
        if self.redis_client:
            with contextlib.suppress(Exception):
                await self.redis_client.close()
            self.redis_client = None

    async def close_all_connections(self, timeout: float = 5.0):
        """Gracefully close all active WebSocket connections.

        Closes every authenticated connection in parallel so the shutdown
        window is bounded even when there are hundreds of open sockets.
        """
        self._shutting_down = True
        # Collect from both connection_users (all authenticated) and connections
        # (room memberships) to ensure nothing is missed.
        all_websockets: set = set(connection_users.keys())
        for room in connections.values():
            all_websockets.update(room)

        if not all_websockets:
            connections.clear()
            log_streams.clear()
            return

        async def _close_one(ws):
            with contextlib.suppress(Exception):
                await ws.close(code=1001, reason="Server shutting down")

        # Close in parallel — bounded by *timeout* regardless of connection count
        close_tasks = [asyncio.create_task(_close_one(ws)) for ws in all_websockets]
        done, pending = await asyncio.wait(close_tasks, timeout=timeout)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        connections.clear()
        connection_users.clear()
        log_streams.clear()

    async def _broadcast_metric(self, metric: dict):
        """Broadcast metric to subscribed clients"""
        server_id = metric.get("server_id")
        disconnected = []

        # Broadcast to server-specific subscribers
        if server_id:
            room = f"server:{server_id}"
            if room in connections:
                for ws in connections[room]:
                    try:
                        await ws.send_json({"event": "metrics:server", "data": metric})
                    except Exception:
                        disconnected.append((room, ws))

        # Broadcast to global subscribers
        if "global" in connections:
            for ws in connections["global"]:
                try:
                    await ws.send_json({"event": "metrics:all", "data": metric})
                except Exception:
                    disconnected.append(("global", ws))

        self._cleanup_disconnected(disconnected)

    def _cleanup_disconnected(self, disconnected: list):
        """Remove disconnected clients from rooms."""
        for room, ws in disconnected:
            if room in connections:
                connections[room].discard(ws)
                if not connections[room]:
                    connections.pop(room, None)

    async def _broadcast_user_event(self, payload: dict):
        """Broadcast user-specific events (e.g. notifications) to their room."""
        user_id = payload.get("user_id")
        if not user_id:
            return
        room = f"user:{user_id}"
        if room not in connections:
            return
        disconnected = []
        for ws in connections[room]:
            try:
                await ws.send_json(
                    {"event": payload.get("event", "user:event"), "data": payload.get("data", {})}
                )
            except Exception:
                disconnected.append((room, ws))
        self._cleanup_disconnected(disconnected)

    async def _broadcast_system_metric(self, metric: dict):
        """Broadcast system metric to global subscribers only"""
        disconnected = []

        # Only broadcast to global room (admin-only)
        if "global" in connections:
            for ws in connections["global"]:
                try:
                    await ws.send_json({"event": "metrics:system", "data": metric})
                except Exception:
                    disconnected.append(("global", ws))

        self._cleanup_disconnected(disconnected)

    async def _authenticate(self, websocket: WebSocket) -> User | None:
        """Authenticate a WebSocket connection.

        First tries query parameter (backward compat), then waits for
        an 'auth' message post-connection. Returns None if auth fails.
        """
        # Phase 1: Try query param (legacy clients)
        user = await validate_websocket_token(websocket)
        if user:
            return user

        # Phase 2: Wait for auth message (modern clients — token not in URL)
        try:
            message = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            data = json.loads(message)
            if data.get("type") == "auth":
                return await validate_token(data.get("token") or "")
        except TimeoutError:
            pass
        except Exception:
            pass
        return None

    async def handle_connection(self, websocket: WebSocket):
        """Handle a new WebSocket connection with authentication"""
        await websocket.accept()

        user = await self._authenticate(websocket)
        if not user:
            try:
                await websocket.send_json(
                    {"event": "auth:error", "message": "Authentication required"}
                )
                await websocket.close(code=4001, reason="Authentication required")
            except Exception:
                pass
            return

        # Reject new connections if server is shutting down
        if self._shutting_down:
            try:
                await websocket.send_json({"event": "error", "message": "Server shutting down"})
                await websocket.close(code=1001, reason="Server shutting down")
            except Exception:
                pass
            return

        await websocket.send_json({"event": "auth:success"})
        _update_active_websocket_connections()

        # Store user data for this connection
        connection_users[websocket] = {
            "user_id": str(user.id),
            "username": user.username,
            "role": user.role,
        }

        try:
            # Lazy-init Redis for WS message throttling
            ws_redis: redis.Redis | None = None
            if settings.rate_limit_enabled:
                try:
                    ws_redis = redis.from_url(settings.redis_url)
                except Exception:
                    ws_redis = None

            while True:
                # If shutdown starts while we're in the loop, stop processing
                if self._shutting_down:
                    break

                message = await websocket.receive_text()

                # ─── WebSocket message-level rate limiting ───
                if ws_redis and settings.rate_limit_enabled:
                    user_id = connection_users[websocket]["user_id"]
                    role = connection_users[websocket]["role"]
                    is_limited, limit, remaining = await _check_ws_message_rate_limit(
                        ws_redis, user_id, role
                    )
                    if is_limited:
                        await websocket.send_json(
                            {
                                "event": "rate_limited",
                                "message": "Too many messages. Please slow down.",
                                "retry_after": settings.rate_limit_window_seconds,
                            }
                        )
                        continue

                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "subscribe":
                        scope = data.get("scope", "global")
                        target_id = data.get("target_id")

                        # Check permissions based on scope
                        allowed = False
                        room = "global"

                        if scope == "server" and target_id:
                            room = f"server:{target_id}"
                            # Check server access
                            async with AsyncSessionLocal() as db:
                                allowed = await check_server_access(user, target_id, db)
                            if not allowed:
                                await websocket.send_json(
                                    {"event": "error", "message": "Access denied to this server"}
                                )
                                continue

                        elif scope == "user" and target_id:
                            room = f"user:{target_id}"
                            # Users can only subscribe to their own user channel
                            # Admins/moderators can subscribe to any
                            if str(target_id) == str(user.id) or has_permission(
                                user, Permission.USERS_READ
                            ):
                                allowed = True
                            else:
                                await websocket.send_json(
                                    {
                                        "event": "error",
                                        "message": "Access denied to this user channel",
                                    }
                                )
                                continue

                        elif scope == "global":
                            room = "global"
                            # Only admins can subscribe to global system metrics
                            if has_permission(user, Permission.ADMIN_ACCESS):
                                allowed = True
                            else:
                                await websocket.send_json(
                                    {
                                        "event": "error",
                                        "message": "Admin access required for global metrics",
                                    }
                                )
                                continue
                        else:
                            # Unknown scope
                            await websocket.send_json(
                                {"event": "error", "message": f"Unknown scope: {scope}"}
                            )
                            continue

                        if room not in connections:
                            connections[room] = set()
                        connections[room].add(websocket)

                        await websocket.send_json(
                            {"event": "subscribed", "scope": scope, "target_id": target_id}
                        )

                    elif msg_type == "subscribe_logs":
                        server_id = data.get("server_id")
                        tail = data.get("tail", 100)

                        if not server_id:
                            await websocket.send_json(
                                {
                                    "event": "error",
                                    "message": "server_id is required for log streaming",
                                }
                            )
                            continue

                        # Check server access
                        async with AsyncSessionLocal() as db:
                            allowed = await check_server_access(user, server_id, db)

                        if not allowed:
                            await websocket.send_json(
                                {"event": "error", "message": "Access denied to this server"}
                            )
                            continue

                        # Get container ID
                        async with AsyncSessionLocal() as db:
                            result = await db.execute(select(Server).where(Server.id == server_id))
                            server = result.scalar_one_or_none()

                        if not server or not server.container_id:
                            await websocket.send_json(
                                {
                                    "event": "error",
                                    "message": "Server not found or no container running",
                                }
                            )
                            continue

                        room = f"logs:{server_id}"
                        if room not in connections:
                            connections[room] = set()
                        connections[room].add(websocket)

                        # Start log streaming task
                        task_key = f"{id(websocket)}:{server_id}"
                        if task_key in log_streams:
                            log_streams[task_key].cancel()

                        task = asyncio.create_task(
                            stream_logs_to_websocket(
                                websocket, server_id, server.container_id, tail
                            )
                        )
                        log_streams[task_key] = task

                        await websocket.send_json(
                            {"event": "logs:subscribed", "server_id": server_id}
                        )

                    elif msg_type == "unsubscribe_logs":
                        server_id = data.get("server_id")

                        if server_id:
                            room = f"logs:{server_id}"
                            if room in connections:
                                connections[room].discard(websocket)
                                if not connections[room]:
                                    connections.pop(room, None)

                            task_key = f"{id(websocket)}:{server_id}"
                            if task_key in log_streams:
                                log_streams[task_key].cancel()
                                log_streams.pop(task_key, None)

                        await websocket.send_json(
                            {"event": "logs:unsubscribed", "server_id": server_id}
                        )

                    elif msg_type == "unsubscribe":
                        scope = data.get("scope", "global")
                        target_id = data.get("target_id")

                        if scope == "server" and target_id:
                            room = f"server:{target_id}"
                        elif scope == "user" and target_id:
                            room = f"user:{target_id}"
                        else:
                            room = "global"

                        if room in connections:
                            connections[room].discard(websocket)
                            if not connections[room]:
                                connections.pop(room, None)

                        await websocket.send_json(
                            {"event": "unsubscribed", "scope": scope, "target_id": target_id}
                        )

                except json.JSONDecodeError:
                    await websocket.send_json({"event": "error", "message": "Invalid JSON"})

        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            # Close Redis client if opened
            if ws_redis is not None:
                with contextlib.suppress(Exception):
                    await ws_redis.aclose()

            # Clean up on disconnect/error
            connection_users.pop(websocket, None)
            for room in list(connections.keys()):
                connections[room].discard(websocket)
                if not connections[room]:
                    connections.pop(room, None)

            _update_active_websocket_connections()

            # Cancel any active log streaming tasks for this connection
            tasks_to_cancel = [
                task for key, task in log_streams.items() if key.startswith(f"{id(websocket)}:")
            ]
            for task in tasks_to_cancel:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _check_ws_message_rate_limit(
    redis_client: redis.Redis,
    user_id: str,
    role: str,
) -> tuple[bool, int, int]:
    """
    Check WebSocket message rate limit for a user.

    Returns: (is_limited, limit, remaining)
    """
    if not settings.rate_limit_enabled:
        return False, 0, 0

    limit = _WS_MSG_LIMITS.get(role.lower(), _WS_MSG_LIMITS["user"])
    window = settings.rate_limit_window_seconds
    bucket = int(time.time()) // window
    key = f"rl:ws_msg:{user_id}:{bucket}"
    ttl = window * settings.rate_limit_bucket_ttl_multiplier

    try:
        lua_sha = await redis_client.script_load(_LUA_INCR_EXPIRE)
        current = int(await redis_client.evalsha(lua_sha, 1, key, ttl))
        remaining = max(0, limit - current)

        if current > limit:
            return True, limit, 0
        return False, limit, remaining
    except Exception as e:
        logger.warning(f"WS rate limiter Redis error (fail-open): {e}")
        return False, 0, 0


manager = MetricsWebSocketManager()
