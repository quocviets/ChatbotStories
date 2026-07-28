from fastapi import APIRouter, status
from app.api.v1.responses import api_response
from app.config import MODEL_REGISTRY

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("", status_code=status.HTTP_200_OK)
async def list_models():
    models_list = [
        {
            "alias": alias,
            "provider": spec["provider"],
            "enabled": spec["enabled"],
            "capabilities": [c.upper() for c in spec["capabilities"]],
            "recommended_for": spec["recommended_for"]
        }
        for alias, spec in MODEL_REGISTRY.items()
    ]
    return api_response(200, "Models retrieved successfully", data=models_list)
