from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client
from app.config import get_settings

security = HTTPBearer()

# Module-level singleton — created once, reused for all requests
_supabase_client = None

def _get_client():
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        if settings.supabase_url and settings.supabase_service_role_key:
            _supabase_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _supabase_client

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    client = _get_client()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase is not configured on this server.",
        )

    try:
        response = client.auth.get_user(token)
        user = response.user
        if not user or not user.id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
            )
        return str(user.id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
        )
