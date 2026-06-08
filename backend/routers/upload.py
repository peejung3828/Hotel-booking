import uuid
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import settings
from backend.database import get_db
from backend.models.room import Room, RoomImage
from backend.services.image_service import ImageService
from backend.routers.auth import require_admin

router = APIRouter()


@router.post("/image/{room_id}")
async def upload_room_image(
    room_id: uuid.UUID,
    file: UploadFile = File(...),
    is_cover: bool = False,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=422, detail="Only JPEG, PNG, WebP images allowed")

    contents = await file.read()
    service = ImageService()
    filename = f"{uuid.uuid4()}.jpg"
    upload_dir = Path(settings.UPLOAD_DIR) / str(room_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / filename
    await service.resize_and_save(contents, str(file_path))

    relative_url = f"/static/uploads/{room_id}/{filename}"

    if is_cover:
        # Unset existing cover
        existing_images = await db.execute(
            select(RoomImage).where(RoomImage.room_id == room_id, RoomImage.is_cover == True)
        )
        for img in existing_images.scalars().all():
            img.is_cover = False

    # Get sort order
    count_result = await db.execute(
        select(RoomImage).where(RoomImage.room_id == room_id)
    )
    sort_order = len(count_result.scalars().all())

    image = RoomImage(
        room_id=room_id,
        url=relative_url,
        is_cover=is_cover,
        sort_order=sort_order,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    return {"id": str(image.id), "url": relative_url, "is_cover": is_cover}


@router.put("/image/{image_id}/cover")
async def set_cover_image(
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(RoomImage).where(RoomImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Unset all covers for this room
    existing = await db.execute(
        select(RoomImage).where(RoomImage.room_id == image.room_id, RoomImage.is_cover == True)
    )
    for img in existing.scalars().all():
        img.is_cover = False

    image.is_cover = True
    await db.commit()
    return {"message": "Cover set"}


@router.delete("/image/{image_id}")
async def delete_image(
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    result = await db.execute(select(RoomImage).where(RoomImage.id == image_id))
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Remove physical file
    file_path = Path("backend") / image.url.lstrip("/")
    if file_path.exists():
        file_path.unlink()

    await db.delete(image)
    await db.commit()
    return {"message": "Image deleted"}
