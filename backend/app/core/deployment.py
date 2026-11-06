from fastapi import HTTPException

from app.core.config import is_hosted


def require_hosted() -> None:
    if not is_hosted():
        raise HTTPException(status_code=404, detail="Not Found")
