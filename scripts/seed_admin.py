"""
Create the first super_admin account.

Usage:
    python scripts/seed_admin.py
    python scripts/seed_admin.py --name "Manager" --username admin --password secret
"""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import bcrypt as _bcrypt
from sqlalchemy import select
from backend.database import AsyncSessionLocal
from backend.models.user import AdminUser


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


async def seed(name: str, username: str, password: str, line_id: str | None):
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(AdminUser).where(AdminUser.username == username))
        if existing.scalar_one_or_none():
            print(f"[!] Username '{username}' already exists. Aborting.")
            return

        user = AdminUser(
            name=name,
            username=username,
            hashed_password=hash_password(password),
            line_id=line_id,
            role="super_admin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"[✓] Created super_admin: '{username}' (id={user.id})")
        print(f"    Login at /cms/login with username='{username}'")


def main():
    parser = argparse.ArgumentParser(description="Seed first admin user")
    parser.add_argument("--name",     default="Administrator")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin1234")
    parser.add_argument("--line-id",  default=None)
    args = parser.parse_args()

    print(f"Creating super_admin '{args.username}'...")
    asyncio.run(seed(args.name, args.username, args.password, args.line_id))


if __name__ == "__main__":
    main()
