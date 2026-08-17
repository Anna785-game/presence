"""
Auth basée sur Supabase Auth.
Les projets récents signent les JWT en ES256 (asymétrique).
On vérifie via le JWKS public de Supabase.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWKClient

from app.core.config import settings

bearer_scheme = HTTPBearer()

# Client JWKS (cache les clés publiques)
_jwks_client = PyJWKClient(
    f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
)


class CurrentUser:
    def __init__(self, id: str, email: str | None, role: str):
        self.id = id
        self.email = email
        self.role = role  # 'admin' | 'user'


def decode_supabase_jwt(token: str) -> dict:
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    payload = decode_supabase_jwt(credentials.credentials)
    user_id = payload.get("sub")
    email = payload.get("email")
    role = (payload.get("user_metadata") or {}).get("role", "user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide")
    return CurrentUser(id=user_id, email=email, role=role)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user
