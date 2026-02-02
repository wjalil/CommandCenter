from fastapi import APIRouter
from . import cacfp_routes
from . import food_component_routes
from . import meal_item_routes
from . import program_routes
from . import monthly_menu_routes
from . import invoice_routes
from . import services_routes
from . import html_routes
from . import catering_weekly_ingredients
# Create main catering router
router = APIRouter()

# Include HTML routes (templates) FIRST so specific paths like /create are matched before /{id}
router.include_router(html_routes.router, tags=["Catering UI"])

# Include API sub-routers (JSON endpoints)
router.include_router(cacfp_routes.router, prefix="/cacfp", tags=["CACFP Reference Data"])
router.include_router(food_component_routes.router, prefix="/food-components", tags=["Food Components"])
router.include_router(meal_item_routes.router, prefix="/meal-items", tags=["Meal Items"])
router.include_router(program_routes.router, prefix="/programs", tags=["Catering Programs"])
router.include_router(monthly_menu_routes.router, prefix="/monthly-menus", tags=["Monthly Menus"])
router.include_router(invoice_routes.router, prefix="/invoices", tags=["Invoices"])
router.include_router(services_routes.router, prefix="/services", tags=["Catering Services"])
router.include_router(catering_weekly_ingredients.router, prefix="/weekly-ingredients", tags=["Weekly Ingredients"])

__all__ = ["router"]
