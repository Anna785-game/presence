from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.core.config import settings
from app.core.ws_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket, token: str = Query(...)):
    if token != settings.ADMIN_WS_TOKEN:
        await websocket.close(code=4403)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # garde la connexion vivante
    except WebSocketDisconnect:
        manager.disconnect(websocket)
