from fastapi import APIRouter

router = APIRouter(
    prefix="/test",
    tags=["test"],
)


@router.get("/", tags=["test"])
async def read_test():
    return {"message": "This is a test endpoint from FastAPI!"}
