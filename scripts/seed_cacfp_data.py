"""
Seed CACFP data: Age Groups, Component Types, and Portion Rules

This script populates the CACFP lookup tables with USDA meal pattern requirements.
Run once after creating the catering tables.

Usage: python scripts/seed_cacfp_data.py
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.future import select
from app.models.catering import CACFPAgeGroup, CACFPComponentType, CACFPPortionRule
from app.db import async_session


async def seed_cacfp_data():
    """Seed all CACFP reference data"""

    async with async_session() as session:
        print("🌱 Seeding CACFP data...\n")

        # Check if data already exists
        result = await session.execute(select(CACFPAgeGroup))
        if result.scalars().first():
            print("⚠️  CACFP data already exists. Skipping seed.")
            return

        # 1. Seed Age Groups
        print("📊 Creating Age Groups...")
        age_groups = [
            CACFPAgeGroup(id=1, name="Infant 0-5 months", age_min_months=0, age_max_months=5, sort_order=1),
            CACFPAgeGroup(id=2, name="Infant 6-11 months", age_min_months=6, age_max_months=11, sort_order=2),
            CACFPAgeGroup(id=3, name="Child 1-2 years", age_min_months=12, age_max_months=24, sort_order=3),
            CACFPAgeGroup(id=4, name="Child 3-5 years", age_min_months=36, age_max_months=60, sort_order=4),
            CACFPAgeGroup(id=5, name="Child 6-12 years", age_min_months=72, age_max_months=144, sort_order=5),
            CACFPAgeGroup(id=6, name="Adult", age_min_months=216, age_max_months=None, sort_order=6),
        ]
        session.add_all(age_groups)
        await session.flush()
        print(f"✅ Created {len(age_groups)} age groups")

        # 2. Seed Component Types
        print("\n🥗 Creating Component Types...")
        component_types = [
            CACFPComponentType(id=1, name="Milk", description="Fluid milk", sort_order=1),
            CACFPComponentType(id=2, name="Meat/Meat Alternate", description="Protein sources", sort_order=2),
            CACFPComponentType(id=3, name="Grain", description="Grains and bread products", sort_order=3),
            CACFPComponentType(id=4, name="Vegetable", description="Vegetables", sort_order=4),
            CACFPComponentType(id=5, name="Fruit", description="Fruits", sort_order=5),
        ]
        session.add_all(component_types)
        await session.flush()
        print(f"✅ Created {len(component_types)} component types")

        # 3. Seed Portion Rules
        print("\n📏 Creating Portion Rules...")

        # CACFP Portion Rules (based on USDA guidelines)
        # Format: (age_group_id, component_type_id, meal_type, min_oz, max_oz, notes)

        portion_rules_data = [
            # INFANT 0-5 MONTHS (breastmilk/formula only - simplified)
            (1, 1, "Breakfast", 4.0, 6.0, "Breastmilk or formula"),
            (1, 1, "Lunch", 4.0, 6.0, "Breastmilk or formula"),
            (1, 1, "Snack", 4.0, 6.0, "Breastmilk or formula"),

            # INFANT 6-11 MONTHS
            (2, 1, "Breakfast", 6.0, 8.0, "Breastmilk or formula"),
            (2, 2, "Breakfast", 0.0, 0.5, "Meat/meat alternate (optional)"),
            (2, 3, "Breakfast", 0.0, 2.0, "Infant cereal or bread"),
            (2, 5, "Breakfast", 0.0, 4.0, "Fruit or vegetable"),
            (2, 1, "Lunch", 6.0, 8.0, "Breastmilk or formula"),
            (2, 2, "Lunch", 1.0, 1.5, "Meat/meat alternate"),
            (2, 3, "Lunch", 0.0, 2.0, "Infant cereal or bread"),
            (2, 4, "Lunch", 1.0, 2.0, "Vegetable"),
            (2, 5, "Lunch", 1.0, 2.0, "Fruit"),
            (2, 1, "Snack", 6.0, 8.0, "Breastmilk or formula"),
            (2, 3, "Snack", 0.0, 0.5, "Bread or cracker"),

            # CHILD 1-2 YEARS
            (3, 1, "Breakfast", 4.0, None, "Whole milk"),
            (3, 2, "Breakfast", 0.5, None, "Meat/meat alternate"),
            (3, 3, "Breakfast", 0.5, None, "Grain (oz eq)"),
            (3, 5, "Breakfast", 0.25, None, "Fruit or vegetable (cup)"),
            (3, 1, "Lunch", 4.0, None, "Whole milk"),
            (3, 2, "Lunch", 1.0, None, "Meat/meat alternate"),
            (3, 3, "Lunch", 0.5, None, "Grain (oz eq)"),
            (3, 4, "Lunch", 0.125, None, "Vegetable (cup)"),
            (3, 5, "Lunch", 0.125, None, "Fruit (cup)"),
            (3, 1, "Snack", 4.0, None, "Whole milk"),
            (3, 2, "Snack", 0.5, None, "Meat/meat alternate"),
            (3, 3, "Snack", 0.5, None, "Grain (oz eq)"),
            (3, 4, "Snack", 0.5, None, "Vegetable (cup)"),
            (3, 5, "Snack", 0.5, None, "Fruit (cup)"),

            # CHILD 3-5 YEARS (Preschool)
            (4, 1, "Breakfast", 6.0, None, "Milk (fluid ounces)"),
            (4, 2, "Breakfast", 0.5, None, "Meat/meat alternate (oz eq)"),
            (4, 3, "Breakfast", 0.5, None, "Grain (oz eq)"),
            (4, 5, "Breakfast", 0.5, None, "Fruit or vegetable (cup)"),
            (4, 1, "Lunch", 6.0, None, "Milk (fluid ounces)"),
            (4, 2, "Lunch", 1.5, None, "Meat/meat alternate (oz eq)"),
            (4, 3, "Lunch", 0.5, None, "Grain (oz eq)"),
            (4, 4, "Lunch", 0.25, None, "Vegetable (cup)"),
            (4, 5, "Lunch", 0.25, None, "Fruit (cup)"),
            (4, 1, "Snack", 4.0, None, "Milk (fluid ounces)"),
            (4, 2, "Snack", 0.5, None, "Meat/meat alternate (oz eq)"),
            (4, 3, "Snack", 0.5, None, "Grain (oz eq)"),
            (4, 4, "Snack", 0.5, None, "Vegetable (cup)"),
            (4, 5, "Snack", 0.5, None, "Fruit (cup)"),

            # CHILD 6-12 YEARS (School Age)
            (5, 1, "Breakfast", 8.0, None, "Milk (fluid ounces)"),
            (5, 2, "Breakfast", 1.0, None, "Meat/meat alternate (oz eq)"),
            (5, 3, "Breakfast", 1.0, None, "Grain (oz eq)"),
            (5, 5, "Breakfast", 0.5, None, "Fruit or vegetable (cup)"),
            (5, 1, "Lunch", 8.0, None, "Milk (fluid ounces)"),
            (5, 2, "Lunch", 2.0, None, "Meat/meat alternate (oz eq)"),
            (5, 3, "Lunch", 1.0, None, "Grain (oz eq)"),
            (5, 4, "Lunch", 0.5, None, "Vegetable (cup)"),
            (5, 5, "Lunch", 0.25, None, "Fruit (cup)"),
            (5, 1, "Snack", 8.0, None, "Milk (fluid ounces)"),
            (5, 2, "Snack", 1.0, None, "Meat/meat alternate (oz eq)"),
            (5, 3, "Snack", 1.0, None, "Grain (oz eq)"),
            (5, 4, "Snack", 0.75, None, "Vegetable (cup)"),
            (5, 5, "Snack", 0.75, None, "Fruit (cup)"),

            # ADULT
            (6, 1, "Breakfast", 8.0, None, "Milk (fluid ounces)"),
            (6, 2, "Breakfast", 1.0, None, "Meat/meat alternate (oz eq)"),
            (6, 3, "Breakfast", 1.0, None, "Grain (oz eq)"),
            (6, 5, "Breakfast", 0.5, None, "Fruit or vegetable (cup)"),
            (6, 1, "Lunch", 8.0, None, "Milk (fluid ounces)"),
            (6, 2, "Lunch", 2.0, None, "Meat/meat alternate (oz eq)"),
            (6, 3, "Lunch", 2.0, None, "Grain (oz eq)"),
            (6, 4, "Lunch", 0.5, None, "Vegetable (cup)"),
            (6, 5, "Lunch", 0.5, None, "Fruit (cup)"),
            (6, 1, "Snack", 8.0, None, "Milk (fluid ounces)"),
            (6, 2, "Snack", 1.0, None, "Meat/meat alternate (oz eq)"),
            (6, 3, "Snack", 1.0, None, "Grain (oz eq)"),
            (6, 4, "Snack", 0.75, None, "Vegetable (cup)"),
            (6, 5, "Snack", 0.75, None, "Fruit (cup)"),
        ]

        portion_rules = []
        for age_id, comp_id, meal, min_oz, max_oz, notes in portion_rules_data:
            rule = CACFPPortionRule(
                age_group_id=age_id,
                component_type_id=comp_id,
                meal_type=meal,
                min_portion_oz=min_oz,
                max_portion_oz=max_oz,
                notes=notes
            )
            portion_rules.append(rule)

        session.add_all(portion_rules)
        await session.commit()
        print(f"✅ Created {len(portion_rules)} portion rules")

        print("\n🎉 CACFP seed data completed successfully!")
        print("\nSummary:")
        print(f"  - {len(age_groups)} Age Groups")
        print(f"  - {len(component_types)} Component Types")
        print(f"  - {len(portion_rules)} Portion Rules")
        print("\n✨ Ready to create programs, meal items, and menus!")


if __name__ == "__main__":
    asyncio.run(seed_cacfp_data())
