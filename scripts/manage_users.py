# scripts/manage_users.py

import asyncio
import argparse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete  
from app.db import get_async_engine, async_session
from app.models.user import User
import uuid
from app.models.tenant import Tenant  
import sys
import asyncio

# 🎯 USERS TO SEED
USERS_TO_SEED = [
    {"name": "Wahid", "pin_code": "9560", "role": "admin"},
    {"name": "Jahir", "pin_code": "6014", "role": "admin"},
    {"name": "Pema", "pin_code": "0843", "role": "worker"},
    {"name": "Johan", "pin_code": "2900", "role": "worker"},
    {"name": "Ridwan", "pin_code": "2352", "role": "worker"},
]

if sys.platform.startswith('win') and sys.version_info < (3, 10):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())



async def seed_users():
    async with async_session() as session:
        # 🔁 Step 1: Ensure a Tenant exists
        result = await session.execute(select(Tenant).where(Tenant.name == "Chai and Biscuit"))
        tenant = result.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="Chai and Biscuit")
            session.add(tenant)
            await session.commit()  # Commit once so tenant.id gets populated
            print(f"🏢 Created tenant: {tenant.name}")

        # 🔁 Step 2: Seed Users linked to Tenant
        for user_data in USERS_TO_SEED:
            result = await session.execute(select(User).where(User.name == user_data["name"]))
            existing = result.scalar_one_or_none()
            if existing:
                print(f"⚠️  User '{user_data['name']}' already exists. Skipping.")
                continue
            user = User(
                id=str(uuid.uuid4()),
                name=user_data["name"],
                pin_code=user_data["pin_code"],
                role=user_data["role"],
                tenant_id=tenant.id,  # 🔐 Link user to tenant
            )
            session.add(user)
            print(f"✅ Created: {user.name} ({user.role}) — tenant: {tenant.name}")
        
        await session.commit()
        print("✅ Done seeding users.\n")


async def delete_users(name=None, role=None):
    async with async_session() as session:
        if name:
            result = await session.execute(select(User).where(User.name == name))
            user = result.scalar_one_or_none()
            if user:
                await session.delete(user)
                await session.commit()
                print(f"🗑️  Deleted user: {name}")
            else:
                print(f"⚠️  No user found with name: {name}")
        elif role:
            result = await session.execute(select(User).where(User.role == role))
            users = result.scalars().all()
            if users:
                for user in users:
                    await session.delete(user)
                await session.commit()
                print(f"🗑️  Deleted all users with role: {role}")
            else:
                print(f"⚠️  No users found with role: {role}")
        else:
            print("❌ Specify either --name or --role to delete users.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage CookieOps Users")
    parser.add_argument("--seed", action="store_true", help="Seed initial users")
    parser.add_argument("--delete", action="store_true", help="Delete users")
    parser.add_argument("--name", type=str, help="Name of user to delete")
    parser.add_argument("--role", type=str, help="Role of users to delete (admin/worker)")

    args = parser.parse_args()

    if args.seed:
        asyncio.run(seed_users())
    elif args.delete:
        asyncio.run(delete_users(name=args.name, role=args.role))
    else:
        print("❗ Usage:")
        print("  python -m scripts.manage_users --seed")
        print("  python -m scripts.manage_users --delete --name Pema")
        print("  python -m scripts.manage_users --delete --role worker")


### Action	Command
#Seed all users	python -m scripts.manage_users --seed
#Delete one user	python -m scripts.manage_users --delete --name Pema
#Delete all workers	python -m scripts.manage_users --delete --role worker