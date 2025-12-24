"""
Menu Generation Service

Automatically generates monthly menus for catering programs based on:
- Program service days
- Required meal types
- Available meal items
- Holidays
- Variety preferences
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.catering import (
    CateringProgram,
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringMealItem
)
from app.crud.catering import monthly_menu as menu_crud
from datetime import date, timedelta
import calendar
import json
import random
from typing import List, Dict


class MenuGenerator:
    """Generates monthly menus for catering programs"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def get_service_dates(
        self,
        program: CateringProgram,
        month: int,
        year: int
    ) -> List[date]:
        """
        Get all service dates for a program in a given month.

        Excludes holidays and non-service days.
        """
        # Parse service days
        service_days = json.loads(program.service_days)
        service_day_numbers = []

        day_map = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2,
            "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
        }

        for day in service_days:
            if day in day_map:
                service_day_numbers.append(day_map[day])

        # Get all days in the month
        num_days = calendar.monthrange(year, month)[1]
        dates = []

        # Get holidays for this program
        holiday_dates = {holiday.holiday_date for holiday in program.holidays}

        for day in range(1, num_days + 1):
            d = date(year, month, day)

            # Check if it's a service day
            if d.weekday() in service_day_numbers:
                # Check if it's not a holiday
                if d not in holiday_dates:
                    # Check if it's within program dates
                    if d >= program.start_date:
                        if not program.end_date or d <= program.end_date:
                            dates.append(d)

        return dates

    async def get_available_meal_items(
        self,
        tenant_id: int,
        meal_type: str,
        vegan_only: bool = False
    ) -> List[CateringMealItem]:
        """Get available meal items for a tenant, meal type, and dietary preference"""
        query = select(CateringMealItem).where(
            CateringMealItem.tenant_id == tenant_id,
            CateringMealItem.meal_type == meal_type
        )

        if vegan_only:
            query = query.where(CateringMealItem.is_vegan == True)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def generate_monthly_menu(
        self,
        program_id: str,
        month: int,
        year: int,
        variety_window: int = 5
    ) -> CateringMonthlyMenu:
        """
        Generate a monthly menu for a program.

        Args:
            program_id: The program to generate menu for
            month: Month (1-12)
            year: Year
            variety_window: Number of days to avoid repeating same meal (default 5)

        Returns:
            Created CateringMonthlyMenu with all menu days
        """
        # Get the program
        program = await self.db.get(CateringProgram, program_id)
        if not program:
            raise ValueError(f"Program {program_id} not found")

        # Create the monthly menu
        from app.schemas.catering import MonthlyMenuCreate
        menu_create = MonthlyMenuCreate(
            program_id=program_id,
            month=month,
            year=year,
            tenant_id=program.tenant_id
        )
        monthly_menu = await menu_crud.create_monthly_menu(self.db, menu_create)

        # Get service dates
        service_dates = self.get_service_dates(program, month, year)

        # Parse meal types required
        meal_types_required = json.loads(program.meal_types_required)

        # Track recent meals for variety
        recent_meals = {meal_type: [] for meal_type in meal_types_required}

        # Generate menu days
        for service_date in service_dates:
            menu_day_data = {
                "service_date": service_date,
                "notes": None
            }

            # Assign meals for each required meal type
            for meal_type in meal_types_required:
                meal_type_lower = meal_type.lower()

                # Get available meals for this type
                regular_meals = await self.get_available_meal_items(
                    program.tenant_id,
                    meal_type,
                    vegan_only=False
                )

                # Select regular meal with variety
                if regular_meals:
                    selected_meal = self._select_meal_with_variety(
                        regular_meals,
                        recent_meals[meal_type],
                        variety_window
                    )
                    menu_day_data[f"{meal_type_lower}_item_id"] = selected_meal.id

                    # Track for variety
                    recent_meals[meal_type].append(selected_meal.id)
                    if len(recent_meals[meal_type]) > variety_window:
                        recent_meals[meal_type].pop(0)

                # If program has vegan children, assign vegan meals
                if program.vegan_count > 0:
                    vegan_meals = await self.get_available_meal_items(
                        program.tenant_id,
                        meal_type,
                        vegan_only=True
                    )

                    if vegan_meals:
                        selected_vegan = self._select_meal_with_variety(
                            vegan_meals,
                            recent_meals.get(f"{meal_type}_vegan", []),
                            variety_window
                        )
                        menu_day_data[f"{meal_type_lower}_vegan_item_id"] = selected_vegan.id

            # Create menu day
            from app.schemas.catering import MenuDayAssignment
            menu_day_assignment = MenuDayAssignment(**menu_day_data)
            await menu_crud.upsert_menu_day(self.db, monthly_menu.id, menu_day_assignment)

        # Refresh to get all menu days
        await self.db.refresh(monthly_menu)
        return monthly_menu

    def _select_meal_with_variety(
        self,
        available_meals: List[CateringMealItem],
        recent_meal_ids: List[str],
        variety_window: int
    ) -> CateringMealItem:
        """
        Select a meal from available options, avoiding recent selections.

        If all meals have been used recently, picks the least recent one.
        """
        # Filter out recently used meals
        non_recent = [
            meal for meal in available_meals
            if meal.id not in recent_meal_ids
        ]

        if non_recent:
            return random.choice(non_recent)
        else:
            # All have been used recently, pick randomly
            return random.choice(available_meals)

    async def regenerate_menu_day(
        self,
        menu_day_id: str,
        meal_type: str = None
    ):
        """
        Regenerate a specific menu day or specific meal type within a day.

        Useful for manually refreshing meals while keeping variety.
        """
        menu_day = await self.db.get(CateringMenuDay, menu_day_id)
        if not menu_day:
            raise ValueError(f"Menu day {menu_day_id} not found")

        # Get the monthly menu and program
        monthly_menu = await self.db.get(CateringMonthlyMenu, menu_day.monthly_menu_id)
        program = await self.db.get(CateringProgram, monthly_menu.program_id)

        # Regenerate specific meal type or all
        meal_types = [meal_type] if meal_type else json.loads(program.meal_types_required)

        for mt in meal_types:
            mt_lower = mt.lower()

            # Regular meal
            regular_meals = await self.get_available_meal_items(
                program.tenant_id,
                mt,
                vegan_only=False
            )
            if regular_meals:
                selected = random.choice(regular_meals)
                setattr(menu_day, f"{mt_lower}_item_id", selected.id)

            # Vegan meal
            if program.vegan_count > 0:
                vegan_meals = await self.get_available_meal_items(
                    program.tenant_id,
                    mt,
                    vegan_only=True
                )
                if vegan_meals:
                    selected_vegan = random.choice(vegan_meals)
                    setattr(menu_day, f"{mt_lower}_vegan_item_id", selected_vegan.id)

        await self.db.commit()
        await self.db.refresh(menu_day)
        return menu_day
