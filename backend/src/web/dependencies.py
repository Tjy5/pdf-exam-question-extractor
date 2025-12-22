"""
Authentication and authorization dependencies.
"""

from typing import Optional

from fastapi import Header, HTTPException, status


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> str:
    """
    Authenticate user from request headers.

    For now, we accept a simple user_id from X-User-Id.
    """
    if x_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    user_id = x_user_id.strip()
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    return user_id


def verify_owner(resource_user_id: str, current_user_id: str) -> None:
    """Raise 403 if the current user does not own the resource."""
    if str(resource_user_id) != str(current_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
