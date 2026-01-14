from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.project import require_project
from models.api_models import (
    AssetDeleteResponse,
    AssetListResponse,
    AssetReindexResponse,
    AssetResponse,
    AssetUploadResponse,
)
from operators.asset_operator import (
    delete_asset,
    get_asset,
    list_assets,
    reindex_asset,
    upload_asset,
)

router = APIRouter(prefix="/projects/{project_id}/assets", tags=["assets"])


def _asset_to_response(asset) -> AssetResponse:
    """Convert an Assets model to AssetResponse."""
    return AssetResponse(
        asset_id=str(asset.asset_id),
        asset_name=asset.asset_name,
        asset_type=asset.asset_type,
        asset_url=asset.asset_url,
        uploaded_at=asset.uploaded_at,
        indexing_status=asset.indexing_status or "pending",
        indexing_error=asset.indexing_error,
        indexing_attempts=asset.indexing_attempts or 0,
    )


@router.get("/", response_model=AssetListResponse)
async def assets_list(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """List all assets in a project."""
    assets = list_assets(db, project.project_id)
    return AssetListResponse(
        ok=True,
        assets=[_asset_to_response(a) for a in assets],
    )


@router.post("/", response_model=AssetUploadResponse)
async def asset_upload(
    file: UploadFile = File(...),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """Upload a new asset to a project."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        asset = upload_asset(db, project.project_id, file.filename, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload asset: {str(e)}")

    return AssetUploadResponse(ok=True, asset=_asset_to_response(asset))


@router.get("/{asset_id}", response_model=AssetResponse)
async def asset_get(
    asset_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """Get a specific asset by ID."""
    asset = get_asset(db, project.project_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _asset_to_response(asset)


@router.delete("/{asset_id}", response_model=AssetDeleteResponse)
async def asset_delete(
    asset_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """Delete an asset from a project."""
    success = delete_asset(db, project.project_id, asset_id)
    if not success:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetDeleteResponse(ok=True)


@router.post("/{asset_id}/reindex", response_model=AssetReindexResponse)
async def asset_reindex(
    asset_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """
    Trigger a re-index of an asset's metadata.

    Use this endpoint when:
    - An asset's indexing failed and you want to retry
    - You want to refresh the metadata with updated analysis
    """
    asset = reindex_asset(db, project.project_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetReindexResponse(ok=True, asset=_asset_to_response(asset))
