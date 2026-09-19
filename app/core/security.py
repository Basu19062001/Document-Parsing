import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

security = HTTPBasic()


def verify_docs_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    Verifies HTTP Basic Authentication credentials for API documentation endpoints.
    Uses constant-time comparison (secrets.compare_digest) to prevent timing attacks.

    Args:
        credentials: The HTTP Basic credentials extracted by FastAPI.

    Returns:
        The validated username string.

    Raises:
        HTTPException 401: If username or password does not match configuration.
    """
    is_username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.DOCS_USERNAME.encode("utf-8"),
    )
    is_password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.DOCS_PASSWORD.encode("utf-8"),
    )

    if not (is_username_correct and is_password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
