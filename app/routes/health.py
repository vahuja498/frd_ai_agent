from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "FRD AI Agent"}


@router.get("/")
async def root():
    return {
        "service": "FRD AI Agent",
        "version": "1.0.0",
        "description": "Automated FRD generator from Azure DevOps Work Items",
    }
