from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.config import get_settings

security = HTTPBearer()

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    settings = get_settings()
    token = credentials.credentials
    
    if not settings.supabase_jwt_secret:
        # Fallback for development if secret is not set
        # In production, this should always be set
        return "dev-user"

    try:
        payload = jwt.decode(
            token, 
            settings.supabase_jwt_secret, 
            algorithms=["HS256"], 
            options={"verify_aud": False}
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
