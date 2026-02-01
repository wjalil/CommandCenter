"""
Seed Sample Catering Data: Food Components

This script populates food components for catering programs.
It is SAFE to run multiple times (idempotent).

Requires CACFP base data to already exist (run seed_cacfp_data.py first).

Usage:
    python scripts/seed_catering_samples.py --tenant-id <ID>
"""

import asyncio
import sys
import os
import argparse
from decimal import Decimal

# -------------------------------------------------------------------
# WINDOWS EVENT LOOP FIX (CRITICAL)
# -------------------------------------------------------------------
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.future import select
from app.models.catering import FoodComponent
from app.models.tenant import Tenant
from app.db import async_session

# -------------------------------------------------------------------
# CACFP COMPONENT TYPE IDS
# -------------------------------------------------------------------
MILK = 1
PROTEIN = 2
GRAIN = 3
VEGETABLE = 4
FRUIT = 5

# -------------------------------------------------------------------
# FOOD COMPONENT SEED DATA
# (name, component_type_id, default_portion_oz, is_vegan, is_vegetarian)
# -------------------------------------------------------------------
FOOD_COMPONENTS = [
    # MILK
    ("Whole Milk", MILK, 6.0, False, True),
    ("1% Milk", MILK, 6.0, False, True),
    ("Skim Milk", MILK, 6.0, False, True),
    ("Soy Milk", MILK, 6.0, True, True),
    ("Almond Milk", MILK, 6.0, True, True),
    ("Oat Milk", MILK, 6.0, True, True),

    # PROTEIN
    ("Chicken Breast", PROTEIN, 2.0, False, False),
    ("Dominican Chicken", PROTEIN, 2.0, False, False),
    ("Korean BBQ Chicken", PROTEIN, 2.0, False, False),
    ("Orange Chicken", PROTEIN, 2.0, False, False),
    ("Shredded Chicken", PROTEIN, 2.0, False, False),
    ("Popcorn Chicken", PROTEIN, 2.0, False, False),
    ("Chicken Nuggets", PROTEIN, 2.0, False, False),
    ("Chicken Tenders", PROTEIN, 2.0, False, False),
    ("Chicken Burger Patty", PROTEIN, 2.0, False, False),
    ("Chicken Dumplings", PROTEIN, 2.0, False, False),
    ("Chicken Samosas", PROTEIN, 2.0, False, False),

    ("Beef Meatballs", PROTEIN, 2.0, False, False),
    ("Beef Ravioli", PROTEIN, 2.0, False, False),
    ("Beef Chili", PROTEIN, 2.0, False, False),
    ("Beef and Bean Burrito Filling", PROTEIN, 2.0, False, False),

    ("Egg Patty", PROTEIN, 1.5, False, True),
    ("Scrambled Eggs", PROTEIN, 1.5, False, True),

    ("Mozzarella Cheese", PROTEIN, 1.0, False, True),
    ("Mozzarella Sticks", PROTEIN, 1.5, False, True),
    ("Cheddar Cheese", PROTEIN, 1.0, False, True),
    ("Cheese Pizza Cheese", PROTEIN, 1.5, False, True),

    ("Yogurt", PROTEIN, 4.0, False, True),

    ("Kidney Beans", PROTEIN, 2.0, True, True),
    ("Pinto Beans", PROTEIN, 2.0, True, True),

    # GRAIN
    ("French Toast", GRAIN, 2.0, True, True),
    ("Waffle", GRAIN, 2.0, True, True),
    ("Pancakes", GRAIN, 2.0, True, True),
    ("Mini Croissant", GRAIN, 1.5, True, True),
    ("English Muffin", GRAIN, 1.0, True, True),
    ("Whole Grain Toast", GRAIN, 1.0, True, True),
    ("Hashbrowns", GRAIN, 2.0, True, True),

    ("White Rice", GRAIN, 4.0, True, True),
    ("Brown Rice", GRAIN, 4.0, True, True),
    ("Jasmine Rice", GRAIN, 4.0, True, True),
    ("Penne Pasta", GRAIN, 4.0, True, True),
    ("Macaroni Pasta", GRAIN, 4.0, True, True),

    ("Pizza Crust", GRAIN, 2.0, True, True),
    ("Flour Tortilla", GRAIN, 1.5, True, True),
    ("Cornbread", GRAIN, 1.5, True, True),

    ("Animal Crackers", GRAIN, 1.0, True, True),
    ("Goldfish Crackers", GRAIN, 1.0, True, True),
    ("Cheez-Its", GRAIN, 1.0, True, True),

    ("Blueberry Muffin", GRAIN, 2.0, True, True),
    ("Corn Muffin", GRAIN, 2.0, True, True),

    # VEGETABLE
    ("Green Beans", VEGETABLE, 2.0, True, True),
    ("Carrots", VEGETABLE, 2.0, True, True),
    ("Corn", VEGETABLE, 2.0, True, True),
    ("Broccoli", VEGETABLE, 2.0, True, True),
    ("Sweet Potato Fries", VEGETABLE, 3.0, True, True),
    ("Mashed Potatoes", VEGETABLE, 3.0, True, True),
    ("Roasted Potatoes", VEGETABLE, 3.0, True, True),
    ("Yams", VEGETABLE, 3.0, True, True),
    ("California Mixed Vegetables", VEGETABLE, 2.0, True, True),
    ("Marinara Sauce", VEGETABLE, 1.0, True, True),

    # FRUIT
    ("Banana", FRUIT, 2.0, True, True),
    ("Apple", FRUIT, 2.0, True, True),
    ("Apple Slices", FRUIT, 2.0, True, True),
    ("Orange", FRUIT, 2.0, True, True),
    ("Mandarin Orange", FRUIT, 2.0, True, True),
    ("Strawberries", FRUIT, 2.0, True, True),
]

# -------------------------------------------------------------------
# SEED FUNCTION
# -------------------------------------------------------------------
async def seed_catering_samples(tenant_id: int):

    async with async_session() as session:
        print(f"\n{'='*60}")
        print(f"Seeding Food Components for Tenant ID: {tenant_id}")
        print(f"{'='*60}\n")

        # Verify tenant
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            print(f"Error: Tenant ID {tenant_id} not found.")
            return

        print(f"Tenant: {tenant.name}\n")

        # Load existing component names
        result = await session.execute(
            select(FoodComponent.name).where(FoodComponent.tenant_id == tenant_id)
        )
        existing_names = {row[0] for row in result.all()}

        created = 0
        skipped = 0

        print("Seeding food components...")

        for name, type_id, portion, is_vegan, is_veg in FOOD_COMPONENTS:
            if name in existing_names:
                skipped += 1
                continue

            session.add(
                FoodComponent(
                    name=name,
                    component_type_id=type_id,
                    default_portion_oz=Decimal(str(portion)),
                    is_vegan=is_vegan,
                    is_vegetarian=is_veg,
                    tenant_id=tenant_id,
                )
            )
            created += 1

        await session.commit()

        print("\nSeed complete.")
        print(f"  Created: {created}")
        print(f"  Skipped (already existed): {skipped}")
        print(f"  Total defined in seed: {len(FOOD_COMPONENTS)}")


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------
async def list_tenants():
    async with async_session() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()

        print("\nAvailable Tenants:")
        for t in tenants:
            print(f"  {t.id}: {t.name}")

        return tenants


async def main():
    parser = argparse.ArgumentParser(description="Seed catering food components")
    parser.add_argument("--tenant-id", type=int)
    args = parser.parse_args()

    tenant_id = args.tenant_id

    if not tenant_id:
        tenants = await list_tenants()
        tenant_id = int(input("\nEnter Tenant ID to seed: "))

    await seed_catering_samples(tenant_id)


if __name__ == "__main__":
    asyncio.run(main())
