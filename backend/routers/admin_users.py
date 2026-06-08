import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import bcrypt as _bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models.user import AdminUser
from backend.routers.auth import require_admin, require_super_admin, get_current_user

router = APIRouter()


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


class AdminUserCreate(BaseModel):
    name: str
    username: str | None = None
    password: str | None = None
    line_id: str | None = None
    role: str = "admin"


class AdminUserUpdate(BaseModel):
    name: str | None = None
    username: str | None = None
    password: str | None = None
    line_id: str | None = None
    role: str | None = None
    is_active: bool | None = None


class AdminUserOut(BaseModel):
    id: uuid.UUID
    name: str
    username: str | None
    line_id: str | None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AdminUserOut])
async def list_admin_users(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
):
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=AdminUserOut)
async def create_admin_user(
    data: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
):
    # Only super_admin can create super_admin
    if data.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Only super_admin can create super_admin accounts")

    if data.username:
        existing = await db.execute(select(AdminUser).where(AdminUser.username == data.username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already exists")

    if data.line_id:
        existing = await db.execute(select(AdminUser).where(AdminUser.line_id == data.line_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="LINE ID already registered")

    hashed = hash_password(data.password) if data.password else None
    user = AdminUser(
        name=data.name,
        username=data.username,
        hashed_password=hashed,
        line_id=data.line_id,
        role=data.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/{user_id}", response_model=AdminUserOut)
async def update_admin_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
):
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Only super_admin can change roles or edit super_admins
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Cannot edit super_admin account")
    if data.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Only super_admin can assign super_admin role")

    if data.name is not None:
        user.name = data.name
    if data.username is not None:
        user.username = data.username
    if data.line_id is not None:
        user.line_id = data.line_id
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        # Prevent self-deactivation
        if str(user.id) == str(current_user.id) and not data.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = hash_password(data.password)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}")
async def delete_admin_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
):
    if str(user_id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Cannot delete super_admin account")

    await db.delete(user)
    await db.commit()
    return {"message": "User deleted"}
