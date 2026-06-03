from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """
    Liveness check endpoint.

    Returns:
        dict: Status indicator
    """
    return {"status": "ok"}
