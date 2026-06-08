"""
Run this once to create the first super_admin user.
Usage: python create_admin.py
"""
import asyncio
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from backend.config import settings
from backend.database import Base
from backend.models.user import AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    username = input("Username [admin]: ").strip() or "admin"
    password = input("Password: ").strip()
    name = input("Display name [Admin]: ").strip() or "Admin"
    role = input("Role (admin/super_admin) [super_admin]: ").strip() or "super_admin"

    hashed = pwd_context.hash(password)
    user = AdminUser(
        username=username,
        hashed_password=hashed,
        name=name,
        role=role,
        is_active=True,
    )

    async with Session() as db:
        db.add(user)
        await db.commit()
        await db.refresh(user)

    print(f"\n✅ Created {role}: {username} (id={user.id})")
    await engine.dispose()


asyncio.run(main())
