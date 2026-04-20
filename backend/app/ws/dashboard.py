import json
import logging
import time
from datetime import datetime, timezone
from typing import Set, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class DashboardWebSocketManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            return

        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket client: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.active_connections.discard(conn)

    async def broadcast_instance_status(
        self,
        instance_id: str,
        status: str,
        account_email: str = None,
        current_track: str = None
    ):
        """Broadcast instance status update."""
        await self.broadcast({
            "type": "instance_status",
            "data": {
                "id": str(instance_id),
                "status": status,
                "account_email": account_email,
                "current_track": current_track,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })

    async def broadcast_stream_completed(
        self,
        song_id: str,
        account_id: str,
        instance_id: str,
        duration: int,
        result: str = "success"
    ):
        """Broadcast stream completion event."""
        await self.broadcast({
            "type": "stream_completed",
            "data": {
                "song_id": str(song_id),
                "account_id": str(account_id),
                "instance_id": str(instance_id),
                "duration": duration,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })

    async def broadcast_alert(self, level: str, message: str):
        """Broadcast alert to dashboard."""
        await self.broadcast({
            "type": "alert",
            "data": {
                "level": level,  # "warning" or "error"
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })


# Global manager instance
ws_manager = DashboardWebSocketManager()


async def dashboard_websocket_handler(websocket: WebSocket):
    """Handle WebSocket connections for dashboard."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages if needed
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                # Handle ping/heartbeat
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
