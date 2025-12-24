"""
CACFP Validation Service

Validates that meal items meet USDA CACFP portion requirements
for specific age groups and meal types.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.catering import (
    CateringMealItem,
    CACFPPortionRule,
    CACFPComponentType
)
from typing import Dict, List
from decimal import Decimal


class CACFPValidationError(Exception):
    """Raised when a meal doesn't meet CACFP requirements"""
    pass


class CACFPValidator:
    """Validates meals against CACFP portion requirements"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_meal_item(
        self,
        meal_item: CateringMealItem,
        age_group_id: int
    ) -> Dict[str, any]:
        """
        Validate a meal item against CACFP requirements for an age group.

        Returns:
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str],
                "component_analysis": Dict[component_name, portion_info]
            }
        """
        errors = []
        warnings = []
        component_analysis = {}

        # Get portion rules for this age group and meal type
        result = await self.db.execute(
            select(CACFPPortionRule).where(
                CACFPPortionRule.age_group_id == age_group_id,
                CACFPPortionRule.meal_type == meal_item.meal_type
            )
        )
        portion_rules = {rule.component_type_id: rule for rule in result.scalars().all()}

        if not portion_rules:
            errors.append(f"No CACFP portion rules found for age group {age_group_id} and meal type {meal_item.meal_type}")
            return {
                "valid": False,
                "errors": errors,
                "warnings": warnings,
                "component_analysis": {}
            }

        # Track which components are present in the meal
        component_portions = {}

        # Analyze each component in the meal item
        for meal_component in meal_item.components:
            food_comp = meal_component.food_component
            component_type_id = food_comp.component_type_id
            portion_oz = meal_component.portion_oz

            # Get the component type name
            comp_type = await self.db.get(CACFPComponentType, component_type_id)
            comp_name = comp_type.name if comp_type else f"Component {component_type_id}"

            # Add to portions (sum if multiple items of same type)
            if component_type_id not in component_portions:
                component_portions[component_type_id] = {
                    "name": comp_name,
                    "total_oz": Decimal(0),
                    "items": []
                }

            component_portions[component_type_id]["total_oz"] += portion_oz
            component_portions[component_type_id]["items"].append({
                "food": food_comp.name,
                "portion": float(portion_oz)
            })

        # Validate each component against rules
        for component_type_id, rule in portion_rules.items():
            comp_type = await self.db.get(CACFPComponentType, component_type_id)
            comp_name = comp_type.name if comp_type else f"Component {component_type_id}"

            if component_type_id in component_portions:
                # Component is present - check if portion is adequate
                total_oz = component_portions[component_type_id]["total_oz"]

                analysis = {
                    "required_min": float(rule.min_portion_oz),
                    "required_max": float(rule.max_portion_oz) if rule.max_portion_oz else None,
                    "actual": float(total_oz),
                    "items": component_portions[component_type_id]["items"],
                    "notes": rule.notes
                }

                # Check minimum
                if total_oz < rule.min_portion_oz:
                    errors.append(
                        f"{comp_name}: Insufficient portion. "
                        f"Required {rule.min_portion_oz} oz, got {total_oz} oz"
                    )
                    analysis["status"] = "insufficient"

                # Check maximum (if specified)
                elif rule.max_portion_oz and total_oz > rule.max_portion_oz:
                    warnings.append(
                        f"{comp_name}: Portion exceeds maximum. "
                        f"Max {rule.max_portion_oz} oz, got {total_oz} oz"
                    )
                    analysis["status"] = "excessive"
                else:
                    analysis["status"] = "compliant"

                component_analysis[comp_name] = analysis

            else:
                # Component is missing
                if rule.min_portion_oz > 0:
                    errors.append(
                        f"{comp_name}: Required component missing. "
                        f"Need {rule.min_portion_oz} oz"
                    )
                    component_analysis[comp_name] = {
                        "required_min": float(rule.min_portion_oz),
                        "required_max": float(rule.max_portion_oz) if rule.max_portion_oz else None,
                        "actual": 0,
                        "status": "missing",
                        "notes": rule.notes
                    }
                else:
                    # Optional component
                    component_analysis[comp_name] = {
                        "required_min": 0,
                        "required_max": float(rule.max_portion_oz) if rule.max_portion_oz else None,
                        "actual": 0,
                        "status": "optional_not_provided",
                        "notes": rule.notes
                    }

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "component_analysis": component_analysis
        }

    async def validate_menu_day(
        self,
        menu_day,
        program
    ) -> Dict[str, any]:
        """
        Validate all meals for a menu day against program requirements.

        Returns validation results for each meal type in the program.
        """
        results = {}
        age_group_id = program.age_group_id

        # Parse meal types required
        import json
        meal_types_required = json.loads(program.meal_types_required)

        # Check each required meal type
        for meal_type in meal_types_required:
            meal_type_lower = meal_type.lower()

            # Get the appropriate meal item ID
            regular_item_id = getattr(menu_day, f"{meal_type_lower}_item_id", None)
            vegan_item_id = getattr(menu_day, f"{meal_type_lower}_vegan_item_id", None)

            # Validate regular meal
            if regular_item_id:
                meal_item = await self.db.get(CateringMealItem, regular_item_id)
                if meal_item:
                    validation = await self.validate_meal_item(meal_item, age_group_id)
                    results[f"{meal_type} (Regular)"] = validation
            else:
                results[f"{meal_type} (Regular)"] = {
                    "valid": False,
                    "errors": [f"No {meal_type} item assigned"],
                    "warnings": [],
                    "component_analysis": {}
                }

            # Validate vegan meal if program has vegan children
            if program.vegan_count > 0:
                if vegan_item_id:
                    meal_item = await self.db.get(CateringMealItem, vegan_item_id)
                    if meal_item:
                        validation = await self.validate_meal_item(meal_item, age_group_id)
                        results[f"{meal_type} (Vegan)"] = validation
                else:
                    results[f"{meal_type} (Vegan)"] = {
                        "valid": False,
                        "errors": [f"No vegan {meal_type} item assigned (program has {program.vegan_count} vegan children)"],
                        "warnings": [],
                        "component_analysis": {}
                    }

        return results
