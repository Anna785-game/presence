from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from slowapi.util import get_remote_address
from app.routers.historique_jour import router as historique_jour_router
from app.routers import (
    auth,
    candidats,
    biometrie,
    cartes,
    employes,
    pointage,
    porte,
    postes,
    presences,
    simulation,   
    ws,
    presences_live_and_parcours,
    demo,
)

app = FastAPI(title="Système de Sécurité et Pointage API", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(employes.router)
app.include_router(postes.router)
app.include_router(cartes.router)
app.include_router(presences.router)
app.include_router(pointage.router)
app.include_router(porte.router)
app.include_router(auth.router)
app.include_router(candidats.router)
app.include_router(simulation.router)  
app.include_router(ws.router)
app.include_router(biometrie.router) 
app.include_router(presences_live_and_parcours.router) 
app.include_router(historique_jour_router)
app.include_router(demo.router)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur."})