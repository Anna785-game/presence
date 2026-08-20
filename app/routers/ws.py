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


@router.websocket("/ws/ecran")
async def ws_ecran(websocket: WebSocket, secret: str = Query(...)):
    """
    Même flux d'événements que /ws/admin (visage_enrole, poste_choisi,
    employe_actif, carte_assignee, ...), mais authentifié avec le secret écran statique
    plutôt que le token admin : l'écran kiosque n'a pas besoin (ni envie)
    de porter les pleins pouvoirs admin, juste de savoir quand féliciter un
    candidat qui vient de choisir son poste depuis son téléphone, ou quand
    une carte vient d'être remise.
    """
    if secret != settings.ECRAN_SHARED_SECRET:
        await websocket.close(code=4403)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
