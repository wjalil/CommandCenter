"""
Catering HTML Routes

Serves Jinja2 templates for the catering UI
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import date
from collections import defaultdict
import json
import io
import zipfile

from app.db import get_db
from app.auth.dependencies import get_current_admin_user
from app.models.user import User
from app.models.catering import (
    CateringProgram,
    CateringMealItem,
    CateringMonthlyMenu,
    CateringInvoice,
    FoodComponent,
    CACFPAgeGroup
)
from app.crud.catering import (
    program as program_crud,
    meal_item as meal_item_crud,
    monthly_menu as menu_crud,
    invoice as invoice_crud,
    food_component as food_component_crud,
    cacfp_rules
)
from app.schemas.catering import (
    CateringProgramCreate,
    CateringMealItemCreate,
    MonthlyMenuCreate
)
from decimal import Decimal

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ==================== DASHBOARD ====================

@router.get("/")
async def catering_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Catering dashboard - main landing page"""
    tenant_id = request.state.tenant_id

    # Get counts
    program_count = len(await program_crud.get_programs(db, tenant_id, active_only=True))
    meal_item_count = len(await meal_item_crud.get_meal_items(db, tenant_id))
    menu_count = len(await menu_crud.get_monthly_menus(db, tenant_id))
    invoice_count = len(await invoice_crud.get_invoices(db, tenant_id))

    return templates.TemplateResponse("catering/dashboard.html", {
        "request": request,
        "program_count": program_count,
        "meal_item_count": meal_item_count,
        "menu_count": menu_count,
        "invoice_count": invoice_count,
    })


# ==================== PROGRAMS ====================

@router.get("/programs")
async def programs_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List all catering programs"""
    tenant_id = request.state.tenant_id
    programs = await program_crud.get_programs(db, tenant_id)

    # Convert to dicts to safely parse JSON fields without modifying SQLAlchemy objects
    programs_data = []
    for program in programs:
        service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
        meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

        programs_data.append({
            "id": program.id,
            "name": program.name,
            "client_name": program.client_name,
            "total_children": program.total_children,
            "vegan_count": program.vegan_count,
            "is_active": program.is_active,
            "age_group": program.age_group,
            "service_days": service_days,
            "meal_types_required": meal_types,
        })

    return templates.TemplateResponse("catering/programs_list.html", {
        "request": request,
        "programs": programs_data,
    })


@router.get("/programs/create")
async def program_create_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show program creation form"""
    age_groups = await cacfp_rules.get_all_age_groups(db)

    return templates.TemplateResponse("catering/program_form.html", {
        "request": request,
        "program": None,
        "age_groups": age_groups,
    })


def parse_optional_int(value) -> Optional[int]:
    """Convert form value to int or None (handles empty strings)"""
    if value is None or value == '' or value == 'None':
        return None
    return int(value)


@router.post("/programs/create")
async def program_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new program"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    # Parse required fields
    name = form.get("name")
    client_name = form.get("client_name")
    client_email = form.get("client_email") or None
    client_phone = form.get("client_phone") or None
    address = form.get("address") or None
    age_group_id = int(form.get("age_group_id"))
    invoice_prefix = form.get("invoice_prefix")
    service_days = form.getlist("service_days")
    meal_types_required = form.getlist("meal_types_required")
    start_date_str = form.get("start_date")
    end_date_str = form.get("end_date")
    is_active = "is_active" in form

    # Parse optional meal counts (handle empty strings)
    breakfast_count = parse_optional_int(form.get("breakfast_count"))
    breakfast_vegan_count = int(form.get("breakfast_vegan_count") or 0)
    lunch_count = parse_optional_int(form.get("lunch_count"))
    lunch_vegan_count = int(form.get("lunch_vegan_count") or 0)
    snack_count = parse_optional_int(form.get("snack_count"))

    # Set legacy total_children from the highest meal count for backward compat
    counts = [c for c in [breakfast_count, lunch_count, snack_count] if c is not None]
    total_children = max(counts) if counts else 0
    vegan_count = lunch_vegan_count  # Use lunch vegan as the legacy fallback

    # Parse dates
    from datetime import datetime as dt
    parsed_start_date = dt.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    parsed_end_date = None
    if end_date_str and end_date_str.strip():
        parsed_end_date = dt.strptime(end_date_str, "%Y-%m-%d").date()

    from app.schemas.catering import CateringProgramCreate
    program_data = CateringProgramCreate(
        name=name,
        client_name=client_name,
        client_email=client_email,
        client_phone=client_phone,
        address=address,
        age_group_id=age_group_id,
        total_children=total_children,
        vegan_count=vegan_count,
        breakfast_count=breakfast_count,
        breakfast_vegan_count=breakfast_vegan_count,
        lunch_count=lunch_count,
        lunch_vegan_count=lunch_vegan_count,
        snack_count=snack_count,
        invoice_prefix=invoice_prefix,
        service_days=service_days,
        meal_types_required=meal_types_required,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        is_active=is_active,
        tenant_id=tenant_id,
        holidays=[]
    )

    await program_crud.create_program(db, program_data)
    return RedirectResponse(url="/catering/programs", status_code=303)


@router.get("/programs/{program_id}/edit")
async def program_edit_form(
    request: Request,
    program_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show program edit form"""
    tenant_id = request.state.tenant_id
    program = await program_crud.get_program(db, program_id, tenant_id)

    if not program:
        return RedirectResponse(url="/catering/programs", status_code=303)

    # Parse JSON fields into separate variables (don't modify the model object)
    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types_required = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    age_groups = await cacfp_rules.get_all_age_groups(db)

    # Create a dict with program data for the template
    program_data = {
        "id": program.id,
        "name": program.name,
        "client_name": program.client_name,
        "client_email": program.client_email,
        "client_phone": program.client_phone,
        "address": program.address,
        "age_group_id": program.age_group_id,
        "total_children": program.total_children,
        "vegan_count": program.vegan_count,
        "breakfast_count": program.breakfast_count,
        "breakfast_vegan_count": program.breakfast_vegan_count,
        "lunch_count": program.lunch_count,
        "lunch_vegan_count": program.lunch_vegan_count,
        "snack_count": program.snack_count,
        "invoice_prefix": program.invoice_prefix,
        "start_date": program.start_date,
        "end_date": program.end_date,
        "is_active": program.is_active,
        "service_days": service_days,
        "meal_types_required": meal_types_required,
    }

    return templates.TemplateResponse("catering/program_form.html", {
        "request": request,
        "program": program_data,
        "age_groups": age_groups,
    })


@router.post("/programs/{program_id}/update")
async def program_update(
    request: Request,
    program_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Update a program"""
    tenant_id = request.state.tenant_id
    form = await request.form()

    # Parse required fields
    name = form.get("name")
    client_name = form.get("client_name")
    client_email = form.get("client_email") or None
    client_phone = form.get("client_phone") or None
    address = form.get("address") or None
    age_group_id = int(form.get("age_group_id"))
    invoice_prefix = form.get("invoice_prefix")
    service_days = form.getlist("service_days")
    meal_types_required = form.getlist("meal_types_required")
    start_date_str = form.get("start_date")
    end_date_str = form.get("end_date")
    is_active = "is_active" in form

    # Parse optional meal counts (handle empty strings)
    breakfast_count = parse_optional_int(form.get("breakfast_count"))
    breakfast_vegan_count = int(form.get("breakfast_vegan_count") or 0)
    lunch_count = parse_optional_int(form.get("lunch_count"))
    lunch_vegan_count = int(form.get("lunch_vegan_count") or 0)
    snack_count = parse_optional_int(form.get("snack_count"))

    # Set legacy total_children from the highest meal count for backward compat
    counts = [c for c in [breakfast_count, lunch_count, snack_count] if c is not None]
    total_children = max(counts) if counts else 0
    vegan_count = lunch_vegan_count  # Use lunch vegan as the legacy fallback

    # Parse dates
    from datetime import datetime as dt
    parsed_start_date = dt.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    parsed_end_date = None
    if end_date_str and end_date_str.strip():
        parsed_end_date = dt.strptime(end_date_str, "%Y-%m-%d").date()

    from app.schemas.catering import CateringProgramUpdate
    program_data = CateringProgramUpdate(
        name=name,
        client_name=client_name,
        client_email=client_email,
        client_phone=client_phone,
        address=address,
        age_group_id=age_group_id,
        total_children=total_children,
        vegan_count=vegan_count,
        breakfast_count=breakfast_count,
        breakfast_vegan_count=breakfast_vegan_count,
        lunch_count=lunch_count,
        lunch_vegan_count=lunch_vegan_count,
        snack_count=snack_count,
        invoice_prefix=invoice_prefix,
        service_days=service_days,
        meal_types_required=meal_types_required,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        is_active=is_active,
    )

    await program_crud.update_program(db, program_id, tenant_id, program_data)
    return RedirectResponse(url="/catering/programs", status_code=303)


# ==================== MEAL ITEMS ====================

@router.get("/meal-items")
async def meal_items_list(
    request: Request,
    meal_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List meal items"""
    tenant_id = request.state.tenant_id
    meal_items = await meal_item_crud.get_meal_items(db, tenant_id, meal_type)

    return templates.TemplateResponse("catering/meal_items_list.html", {
        "request": request,
        "meal_items": meal_items,
        "meal_type_filter": meal_type or "all",
    })


@router.get("/meal-items/create")
async def meal_item_create_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show meal item creation form"""
    tenant_id = request.state.tenant_id
    food_components = await food_component_crud.get_food_components(db, tenant_id)
    component_types = await cacfp_rules.get_all_component_types(db)

    return templates.TemplateResponse("catering/meal_item_form.html", {
        "request": request,
        "meal_item": None,
        "food_components": food_components,
        "component_types": component_types,
    })


@router.post("/meal-items/create")
async def meal_item_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new meal item with food components"""
    tenant_id = request.state.tenant_id
    form_data = await request.form()

    # Parse component data from form
    from app.schemas.catering import CateringMealItemCreate, MealComponentCreate
    from decimal import Decimal

    component_ids = form_data.getlist("component_ids[]")
    component_portions = form_data.getlist("component_portions[]")

    components = []
    for comp_id, portion in zip(component_ids, component_portions):
        if comp_id and portion:  # Skip empty rows
            components.append(MealComponentCreate(
                food_component_id=comp_id,
                portion_oz=Decimal(str(portion))
            ))

    meal_item_data = CateringMealItemCreate(
        name=form_data.get("name"),
        description=form_data.get("description"),
        meal_type=form_data.get("meal_type"),
        is_vegan=bool(form_data.get("is_vegan")),
        is_vegetarian=bool(form_data.get("is_vegetarian")),
        tenant_id=tenant_id,
        components=components
    )

    await meal_item_crud.create_meal_item(db, meal_item_data)
    return RedirectResponse(url="/catering/meal-items", status_code=303)


@router.get("/meal-items/{item_id}/edit")
async def meal_item_edit_form(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show meal item edit form"""
    tenant_id = request.state.tenant_id
    meal_item = await meal_item_crud.get_meal_item(db, item_id, tenant_id)

    if not meal_item:
        return RedirectResponse(url="/catering/meal-items", status_code=303)

    food_components = await food_component_crud.get_food_components(db, tenant_id)
    component_types = await cacfp_rules.get_all_component_types(db)

    return templates.TemplateResponse("catering/meal_item_form.html", {
        "request": request,
        "meal_item": meal_item,
        "food_components": food_components,
        "component_types": component_types,
    })


@router.post("/meal-items/{item_id}/update")
async def meal_item_update(
    request: Request,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Update a meal item with food components"""
    tenant_id = request.state.tenant_id
    form_data = await request.form()

    # Parse component data from form
    from app.schemas.catering import MealComponentCreate
    from decimal import Decimal

    component_ids = form_data.getlist("component_ids[]")
    component_portions = form_data.getlist("component_portions[]")

    components = []
    for comp_id, portion in zip(component_ids, component_portions):
        if comp_id and portion:  # Skip empty rows
            components.append(MealComponentCreate(
                food_component_id=comp_id,
                portion_oz=Decimal(str(portion))
            ))

    # Update the meal item
    await meal_item_crud.update_meal_item_with_components(
        db, item_id, tenant_id,
        name=form_data.get("name"),
        description=form_data.get("description"),
        meal_type=form_data.get("meal_type"),
        is_vegan=bool(form_data.get("is_vegan")),
        is_vegetarian=bool(form_data.get("is_vegetarian")),
        components=components
    )

    return RedirectResponse(url="/catering/meal-items", status_code=303)


# ==================== MONTHLY MENUS ====================

@router.get("/monthly-menus")
async def monthly_menus_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List monthly menus"""
    tenant_id = request.state.tenant_id
    monthly_menus = await menu_crud.get_monthly_menus(db, tenant_id)

    return templates.TemplateResponse("catering/monthly_menus_list.html", {
        "request": request,
        "monthly_menus": monthly_menus,
    })


@router.get("/monthly-menus/create")
async def menu_create_form(
    request: Request,
    program_id: Optional[str] = None,
    copy_from: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show menu creation form"""
    tenant_id = request.state.tenant_id
    programs = await program_crud.get_programs(db, tenant_id, active_only=True)
    existing_menus = await menu_crud.get_monthly_menus(db, tenant_id)

    return templates.TemplateResponse("catering/menu_generate_form.html", {
        "request": request,
        "programs": programs,
        "existing_menus": existing_menus,
        "selected_program_id": program_id,
        "selected_copy_from": copy_from,
        "selected_month": month,
        "selected_year": year,
    })


@router.post("/monthly-menus/create")
async def menu_create(
    request: Request,
    program_id: str = Form(...),
    month: int = Form(...),
    year: int = Form(...),
    copy_from_menu_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new monthly menu"""
    tenant_id = request.state.tenant_id

    # Check if menu already exists for this program/month/year
    existing = await menu_crud.get_monthly_menus(db, tenant_id, program_id)
    for menu in existing:
        if menu.month == month and menu.year == year:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"A menu already exists for {month}/{year}"
            )

    # Create the monthly menu
    from app.schemas.catering import MonthlyMenuCreate
    menu_data = MonthlyMenuCreate(
        program_id=program_id,
        month=month,
        year=year,
        status="draft",
        tenant_id=tenant_id
    )
    monthly_menu = await menu_crud.create_monthly_menu(db, menu_data)

    # If copying from existing menu, duplicate the menu days and components
    if copy_from_menu_id:
        source_menu = await menu_crud.get_monthly_menu(db, copy_from_menu_id, tenant_id)
        if source_menu and source_menu.menu_days:
            from datetime import datetime
            from calendar import monthrange
            from app.crud.catering import menu_day_component as mdc_crud
            from app.schemas.catering import MenuDayAssignment
            from app.models.catering import MenuDayComponent
            import uuid

            # Get number of days in target month
            num_days = monthrange(year, month)[1]

            # Map source days to target days (by day of month)
            for source_day in source_menu.menu_days:
                source_day_num = source_day.service_date.day

                # Only copy if target month has this day number
                if source_day_num <= num_days:
                    target_date = datetime(year, month, source_day_num).date()

                    # Create/update the menu day with pre-built meal items
                    day_data = MenuDayAssignment(
                        service_date=target_date,
                        breakfast_item_id=source_day.breakfast_item_id,
                        breakfast_vegan_item_id=source_day.breakfast_vegan_item_id,
                        lunch_item_id=source_day.lunch_item_id,
                        lunch_vegan_item_id=source_day.lunch_vegan_item_id,
                        snack_item_id=source_day.snack_item_id,
                        snack_vegan_item_id=source_day.snack_vegan_item_id,
                        notes=source_day.notes
                    )
                    new_day = await menu_crud.upsert_menu_day(db, monthly_menu.id, day_data)

                    # Also copy the MenuDayComponent records (component-first mode)
                    if hasattr(source_day, 'components') and source_day.components:
                        for source_comp in source_day.components:
                            new_comp = MenuDayComponent(
                                id=str(uuid.uuid4()),
                                menu_day_id=new_day.id,
                                component_id=source_comp.component_id,
                                meal_slot=source_comp.meal_slot,
                                is_vegan=source_comp.is_vegan,
                                quantity=source_comp.quantity,
                                sort_order=source_comp.sort_order if hasattr(source_comp, 'sort_order') else 0,
                                notes=source_comp.notes
                            )
                            db.add(new_comp)

            # Commit all the component copies
            await db.commit()

    return RedirectResponse(
        url=f"/catering/monthly-menus/{monthly_menu.id}/calendar",
        status_code=303
    )


@router.get("/monthly-menus/{menu_id}/duplicate")
async def menu_duplicate_redirect(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Redirect to create form with next month pre-filled"""
    tenant_id = request.state.tenant_id

    # Get the source menu
    source_menu = await menu_crud.get_monthly_menu(db, menu_id, tenant_id)
    if not source_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Calculate next month
    next_month = source_menu.month + 1
    next_year = source_menu.year
    if next_month > 12:
        next_month = 1
        next_year += 1

    # Redirect to create form with params
    return RedirectResponse(
        url=f"/catering/monthly-menus/create?program_id={source_menu.program_id}&copy_from={menu_id}&month={next_month}&year={next_year}",
        status_code=303
    )


@router.post("/monthly-menus/{menu_id}/delete")
async def menu_delete(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Delete a monthly menu and all its menu days"""
    tenant_id = request.state.tenant_id

    await menu_crud.delete_monthly_menu(db, menu_id, tenant_id)

    return RedirectResponse(url="/catering/monthly-menus", status_code=303)


@router.get("/monthly-menus/{menu_id}/calendar")
async def menu_calendar_view(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show calendar view for editing a monthly menu"""
    tenant_id = request.state.tenant_id

    # Get the monthly menu
    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, tenant_id)
    if not monthly_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Get the program
    program = await program_crud.get_program(db, monthly_menu.program_id, tenant_id)
    if not program:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Parse program settings (read-only, don't modify model)
    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    # Get all meal items
    all_meal_items = await meal_item_crud.get_meal_items(db, tenant_id)
    breakfast_items = [item for item in all_meal_items if item.meal_type == "Breakfast"]
    lunch_items = [item for item in all_meal_items if item.meal_type == "Lunch"]
    snack_items = [item for item in all_meal_items if item.meal_type == "Snack"]

    # Filter vegan options
    breakfast_vegan_items = [item for item in breakfast_items if item.is_vegan]
    lunch_vegan_items = [item for item in lunch_items if item.is_vegan]
    snack_vegan_items = [item for item in snack_items if item.is_vegan]

    # Build calendar
    from calendar import monthcalendar, month_name, setfirstweekday, SUNDAY
    from datetime import datetime, date as dt_date

    # Set calendar to start on Sunday (US standard)
    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)

    # Get existing menu days
    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}

    # Helper to build component preview strings for a menu day
    def get_component_preview(menu_day):
        """Returns dict with breakfast, lunch, snack component name strings"""
        preview = {'breakfast': '', 'lunch': '', 'snack': ''}
        if not menu_day or not hasattr(menu_day, 'components') or not menu_day.components:
            return preview

        for slot in ['breakfast', 'lunch', 'snack']:
            # Sort by sort_order and filter to non-vegan components for the preview
            slot_components = sorted(
                [comp for comp in menu_day.components if comp.meal_slot == slot and not comp.is_vegan and comp.food_component],
                key=lambda c: c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0
            )
            names = [comp.food_component.name for comp in slot_components]
            preview[slot] = ', '.join(names)
        return preview

    # Build calendar data structure
    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                # Not in this month
                week_data.append({
                    'day': '',
                    'date': '',
                    'in_month': False,
                    'is_service_day': False,
                    'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)

                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'menu_day': menu_day,
                    'component_preview': get_component_preview(menu_day)
                })
        calendar_weeks.append(week_data)

    # Prepare menu days JSON for JavaScript
    menu_days_json = json.dumps([
        {
            'service_date': day.service_date.isoformat(),
            'breakfast_item_id': day.breakfast_item_id,
            'breakfast_vegan_item_id': day.breakfast_vegan_item_id,
            'lunch_item_id': day.lunch_item_id,
            'lunch_vegan_item_id': day.lunch_vegan_item_id,
            'snack_item_id': day.snack_item_id,
            'snack_vegan_item_id': day.snack_vegan_item_id,
            'notes': day.notes
        }
        for day in monthly_menu.menu_days
    ])

    # Create meal items map for JavaScript
    meal_items_map = {item.id: item.name for item in all_meal_items}

    # Create components map for JavaScript (meal_id -> [component names])
    meal_items_components_map = {}
    for item in all_meal_items:
        if item.components:
            meal_items_components_map[item.id] = [comp.food_component.name for comp in item.components]
        else:
            meal_items_components_map[item.id] = []

    # Get all food components for component-first mode
    food_components = await food_component_crud.get_food_components(db, tenant_id)

    # Build food_components_map for JavaScript
    food_components_map = {}
    for comp in food_components:
        food_components_map[comp.id] = {
            "name": comp.name,
            "type": comp.component_type.name if comp.component_type else None,
            "is_vegan": comp.is_vegan,
            "default_portion_oz": float(comp.default_portion_oz) if comp.default_portion_oz else None
        }

    # Build menu_day_components_json for each day
    menu_day_components = {}
    for day in monthly_menu.menu_days:
        date_str = day.service_date.isoformat()
        menu_day_components[date_str] = {
            "breakfast": [],
            "breakfast_vegan": [],
            "lunch": [],
            "lunch_vegan": [],
            "snack": [],
            "snack_vegan": []
        }
        if hasattr(day, 'components') and day.components:
            # Sort components by sort_order before adding
            sorted_components = sorted(day.components, key=lambda c: (c.meal_slot, c.is_vegan, c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0))
            for comp in sorted_components:
                slot_key = comp.meal_slot
                if comp.is_vegan:
                    slot_key = f"{comp.meal_slot}_vegan"
                menu_day_components[date_str][slot_key].append({
                    "id": comp.id,
                    "component_id": comp.component_id,
                    "name": comp.food_component.name if comp.food_component else None,
                    "type": comp.food_component.component_type.name if comp.food_component and comp.food_component.component_type else None,
                    "sort_order": comp.sort_order if hasattr(comp, 'sort_order') else 0
                })

    return templates.TemplateResponse("catering/menu_calendar.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "breakfast_items": breakfast_items,
        "lunch_items": lunch_items,
        "snack_items": snack_items,
        "breakfast_vegan_items": breakfast_vegan_items,
        "lunch_vegan_items": lunch_vegan_items,
        "snack_vegan_items": snack_vegan_items,
        "menu_days_json": menu_days_json,
        "meal_items_map": json.dumps(meal_items_map),
        "meal_items_components_map": json.dumps(meal_items_components_map),
        "food_components": food_components,
        "food_components_map": json.dumps(food_components_map),
        "menu_day_components_json": json.dumps(menu_day_components),
    })


# ==================== SHAREABLE MENU ====================

@router.get("/monthly-menus/{menu_id}/share")
async def menu_share_view(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Show shareable/printable menu view"""
    tenant_id = request.state.tenant_id

    # Get the monthly menu with all related data
    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, tenant_id)
    if not monthly_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Get the program
    program = await program_crud.get_program(db, monthly_menu.program_id, tenant_id)
    if not program:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Parse program settings
    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    # Build calendar (same logic as calendar view)
    from calendar import monthcalendar, month_name, setfirstweekday, SUNDAY
    from datetime import datetime, date as dt_date

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)

    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}

    def get_component_preview(menu_day):
        preview = {'breakfast': '', 'lunch': '', 'snack': ''}
        if not menu_day or not hasattr(menu_day, 'components') or not menu_day.components:
            return preview
        for slot in ['breakfast', 'lunch', 'snack']:
            # Sort by sort_order for consistent display order
            slot_components = sorted(
                [comp for comp in menu_day.components if comp.meal_slot == slot and not comp.is_vegan and comp.food_component],
                key=lambda c: c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0
            )
            names = [comp.food_component.name for comp in slot_components]
            preview[slot] = ', '.join(names)
        return preview

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '',
                    'date': '',
                    'in_month': False,
                    'is_service_day': False,
                    'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)

                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'menu_day': menu_day,
                    'component_preview': get_component_preview(menu_day)
                })
        calendar_weeks.append(week_data)

    from datetime import datetime as dt
    generated_date = dt.now().strftime('%B %d, %Y')

    # Check which weekend days are service days
    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    return templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": generated_date,
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
    })


@router.get("/monthly-menus/{menu_id}/pdf")
async def menu_pdf_download(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Generate and download menu as PDF"""
    tenant_id = request.state.tenant_id

    # Get the monthly menu with all related data
    monthly_menu = await menu_crud.get_monthly_menu(db, menu_id, tenant_id)
    if not monthly_menu:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Get the program
    program = await program_crud.get_program(db, monthly_menu.program_id, tenant_id)
    if not program:
        return RedirectResponse(url="/catering/monthly-menus", status_code=303)

    # Parse program settings
    service_days = json.loads(program.service_days) if isinstance(program.service_days, str) else (program.service_days or [])
    meal_types = json.loads(program.meal_types_required) if isinstance(program.meal_types_required, str) else (program.meal_types_required or [])

    # Build calendar
    from calendar import monthcalendar, month_name, setfirstweekday, SUNDAY
    from datetime import datetime, date as dt_date

    setfirstweekday(SUNDAY)
    month_weeks = monthcalendar(monthly_menu.year, monthly_menu.month)

    menu_days_dict = {day.service_date.isoformat(): day for day in monthly_menu.menu_days}

    def get_component_preview(menu_day):
        preview = {'breakfast': '', 'lunch': '', 'snack': ''}
        if not menu_day or not hasattr(menu_day, 'components') or not menu_day.components:
            return preview
        for slot in ['breakfast', 'lunch', 'snack']:
            # Sort by sort_order for consistent display order
            slot_components = sorted(
                [comp for comp in menu_day.components if comp.meal_slot == slot and not comp.is_vegan and comp.food_component],
                key=lambda c: c.sort_order if hasattr(c, 'sort_order') and c.sort_order else 0
            )
            names = [comp.food_component.name for comp in slot_components]
            preview[slot] = ', '.join(names)
        return preview

    calendar_weeks = []
    for week in month_weeks:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day': '',
                    'date': '',
                    'in_month': False,
                    'is_service_day': False,
                    'menu_day': None,
                    'component_preview': {'breakfast': '', 'lunch': '', 'snack': ''}
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days
                menu_day = menu_days_dict.get(date_str)

                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'menu_day': menu_day,
                    'component_preview': get_component_preview(menu_day)
                })
        calendar_weeks.append(week_data)

    from datetime import datetime as dt
    generated_date = dt.now().strftime('%B %d, %Y')

    # Check which weekend days are service days
    show_sunday = 'Sunday' in service_days
    show_saturday = 'Saturday' in service_days

    # Render the template to HTML string
    html_content = templates.TemplateResponse("catering/menu_share.html", {
        "request": request,
        "monthly_menu": monthly_menu,
        "program": program,
        "month_name": month_name[monthly_menu.month],
        "year": monthly_menu.year,
        "service_days": service_days,
        "meal_types": meal_types,
        "calendar_weeks": calendar_weeks,
        "generated_date": generated_date,
        "show_sunday": show_sunday,
        "show_saturday": show_saturday,
    }).body.decode('utf-8')

    # Generate PDF using WeasyPrint
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_content, base_url=str(request.base_url)).write_pdf()

        filename = f"{program.name.replace(' ', '_')}_{month_name[monthly_menu.month]}_{monthly_menu.year}_Menu.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except ImportError as e:
        # WeasyPrint not installed
        import logging
        logging.error(f"WeasyPrint not installed: {e}")
        return RedirectResponse(
            url=f"/catering/monthly-menus/{menu_id}/share?error=PDF+library+not+installed",
            status_code=303
        )
    except Exception as e:
        # Handle other errors - log the actual error
        import logging
        logging.error(f"PDF generation failed: {e}")
        return RedirectResponse(
            url=f"/catering/monthly-menus/{menu_id}/share?error=PDF+generation+failed:+{str(e)[:50]}",
            status_code=303
        )


# ==================== INVOICES ====================

async def _get_menu_day_for_invoice(db: AsyncSession, menu_day_id: str):
    """Load a menu day with all meal item and component relationships for PDF rendering."""
    from app.models.catering import CateringMenuDay, CateringMealItem, CateringMealComponent, MenuDayComponent
    if not menu_day_id:
        return None
    result = await db.execute(
        select(CateringMenuDay)
        .where(CateringMenuDay.id == menu_day_id)
        .options(
            selectinload(CateringMenuDay.components).selectinload(MenuDayComponent.food_component),
            selectinload(CateringMenuDay.breakfast_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
            selectinload(CateringMenuDay.breakfast_vegan_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
            selectinload(CateringMenuDay.lunch_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
            selectinload(CateringMenuDay.lunch_vegan_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
            selectinload(CateringMenuDay.snack_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
            selectinload(CateringMenuDay.snack_vegan_item).selectinload(CateringMealItem.components).selectinload(CateringMealComponent.food_component),
        )
    )
    return result.scalar_one_or_none()


async def _generate_invoice_pdf_bytes(request: Request, db: AsyncSession, invoice) -> bytes:
    """Generate PDF bytes for a single invoice using WeasyPrint."""
    from weasyprint import HTML
    menu_day = await _get_menu_day_for_invoice(db, invoice.menu_day_id)
    html_content = templates.TemplateResponse("catering/invoice_view.html", {
        "request": request,
        "invoice": invoice,
        "menu_day": menu_day,
    }).body.decode('utf-8')
    return HTML(string=html_content, base_url=str(request.base_url)).write_pdf()


@router.get("/invoices")
async def invoices_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List invoices grouped by program"""
    tenant_id = request.state.tenant_id
    invoices = await invoice_crud.get_invoices(db, tenant_id)

    # Group invoices by program
    grouped = defaultdict(list)
    for inv in invoices:
        grouped[inv.program].append(inv)

    # Sort programs alphabetically by name
    programs_with_invoices = sorted(grouped.items(), key=lambda x: x[0].name)

    return templates.TemplateResponse("catering/invoices_list.html", {
        "request": request,
        "programs_with_invoices": programs_with_invoices,
    })


@router.post("/invoices/generate/{menu_day_id}")
async def generate_single_invoice(
    request: Request,
    menu_day_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Generate invoice for a single menu day"""
    tenant_id = request.state.tenant_id

    invoice = await invoice_crud.generate_invoice_from_menu_day(db, menu_day_id, tenant_id)

    if invoice:
        return RedirectResponse(url=f"/catering/invoices/{invoice.id}/view", status_code=303)
    else:
        # Invoice already exists or menu day not found
        return RedirectResponse(url="/catering/invoices", status_code=303)


@router.post("/monthly-menus/{menu_id}/generate-invoices")
async def generate_bulk_invoices(
    request: Request,
    menu_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Generate invoices for all days in a monthly menu"""
    tenant_id = request.state.tenant_id

    invoices = await invoice_crud.generate_bulk_invoices_for_month(db, menu_id, tenant_id)

    msg = f"{len(invoices)} invoices generated/updated" if invoices else "No menu days with meals found"
    return RedirectResponse(
        url=f"/catering/invoices?message={msg}",
        status_code=303
    )


@router.get("/invoices/{invoice_id}/view")
async def view_invoice(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """View invoice details"""
    tenant_id = request.state.tenant_id

    invoice = await invoice_crud.get_invoice(db, invoice_id, tenant_id)
    if not invoice:
        return RedirectResponse(url="/catering/invoices", status_code=303)

    menu_day = await _get_menu_day_for_invoice(db, invoice.menu_day_id)

    return templates.TemplateResponse("catering/invoice_view.html", {
        "request": request,
        "invoice": invoice,
        "menu_day": menu_day,
    })


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Download invoice as PDF"""
    tenant_id = request.state.tenant_id

    invoice = await invoice_crud.get_invoice(db, invoice_id, tenant_id)
    if not invoice:
        return RedirectResponse(url="/catering/invoices", status_code=303)

    try:
        pdf_bytes = await _generate_invoice_pdf_bytes(request, db, invoice)

        date_str = invoice.service_date.strftime('%Y-%m-%d')
        filename = f"Invoice_{invoice.invoice_number}_{date_str}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except ImportError as e:
        import logging
        logging.error(f"WeasyPrint not installed: {e}")
        return RedirectResponse(
            url=f"/catering/invoices/{invoice_id}/view?error=PDF+library+not+installed",
            status_code=303
        )
    except Exception as e:
        import logging
        logging.error(f"Invoice PDF generation failed: {e}")
        return RedirectResponse(
            url=f"/catering/invoices/{invoice_id}/view?error=PDF+generation+failed",
            status_code=303
        )


@router.get("/invoices/program/{program_id}/download-all")
async def download_program_invoices_zip(
    request: Request,
    program_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Download all invoices for a program as a zip file"""
    tenant_id = request.state.tenant_id

    invoices = await invoice_crud.get_invoices(db, tenant_id, program_id=program_id)
    if not invoices:
        return RedirectResponse(url="/catering/invoices", status_code=303)

    program_name = invoices[0].program.name

    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for invoice in invoices:
                pdf_bytes = await _generate_invoice_pdf_bytes(request, db, invoice)
                date_str = invoice.service_date.strftime('%Y-%m-%d')
                pdf_filename = f"Invoice_{invoice.invoice_number}_{date_str}.pdf"
                zf.writestr(pdf_filename, pdf_bytes)

        zip_buffer.seek(0)
        safe_name = program_name.replace(' ', '_').replace('/', '-')
        zip_filename = f"{safe_name}_invoices.zip"

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_filename}"'
            }
        )
    except ImportError as e:
        import logging
        logging.error(f"WeasyPrint not installed: {e}")
        return RedirectResponse(
            url="/catering/invoices?error=PDF+library+not+installed",
            status_code=303
        )
    except Exception as e:
        import logging
        logging.error(f"Bulk PDF generation failed: {e}")
        return RedirectResponse(
            url="/catering/invoices?error=Bulk+PDF+generation+failed",
            status_code=303
        )


@router.post("/invoices/{invoice_id}/delete")
async def delete_invoice_route(
    request: Request,
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Delete an invoice"""
    tenant_id = request.state.tenant_id
    await invoice_crud.delete_invoice(db, invoice_id, tenant_id)
    return RedirectResponse(url="/catering/invoices", status_code=303)


# ==================== FOOD COMPONENTS ====================

@router.get("/food-components")
async def food_components_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List food components"""
    tenant_id = request.state.tenant_id
    components = await food_component_crud.get_food_components(db, tenant_id)
    component_types = await cacfp_rules.get_all_component_types(db)

    return templates.TemplateResponse("catering/food_components_list.html", {
        "request": request,
        "components": components,
        "component_types": component_types,
    })


@router.post("/food-components/create")
async def food_component_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new food component"""
    tenant_id = request.state.tenant_id
    form_data = await request.form()

    # Handle checkboxes properly - unchecked boxes don't send data
    is_vegetarian = "is_vegetarian" in form_data
    is_vegan = "is_vegan" in form_data

    from app.schemas.catering import FoodComponentCreate
    from decimal import Decimal

    component_data = FoodComponentCreate(
        name=form_data.get("name"),
        component_type_id=int(form_data.get("component_type_id")),
        default_portion_oz=Decimal(str(form_data.get("default_portion_oz"))),
        is_vegan=is_vegan,
        is_vegetarian=is_vegetarian,
        tenant_id=tenant_id
    )

    await food_component_crud.create_food_component(db, component_data)
    return RedirectResponse(url="/catering/food-components", status_code=303)


# ==================== CACFP REFERENCE ====================

@router.get("/cacfp-reference")
async def cacfp_reference(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """View CACFP reference data"""
    age_groups = await cacfp_rules.get_all_age_groups(db)
    component_types = await cacfp_rules.get_all_component_types(db)
    portion_rules = await cacfp_rules.get_portion_rules(db)

    return templates.TemplateResponse("catering/cacfp_reference.html", {
        "request": request,
        "age_groups": age_groups,
        "component_types": component_types,
        "portion_rules": portion_rules,
    })


# ==================== SEED JANUARY MENU DATA ====================

@router.post("/seed-sample-data")
async def seed_sample_data(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Seed food components and meal items based on January 2026 menu"""
    from app.models.catering import CateringMealComponent

    tenant_id = request.state.tenant_id

    # Check if data already exists
    existing = await food_component_crud.get_food_components(db, tenant_id)
    if existing:
        return RedirectResponse(url="/catering?error=Data+already+exists", status_code=303)

    # Component Type IDs (from CACFP)
    MILK, PROTEIN, GRAIN, VEGETABLE, FRUIT = 1, 2, 3, 4, 5

    # Food Components based on January 2026 menu
    # Format: (name, type_id, portion_oz, is_vegan, is_vegetarian)
    food_components_data = [
        # MILK/DAIRY
        ("Whole Milk", MILK, 6.0, False, True),
        ("Yogurt", MILK, 4.0, False, True),
        ("Cream Cheese", MILK, 1.0, False, True),

        # PROTEINS
        ("Beef Meatballs", PROTEIN, 2.0, False, False),
        ("Dominican Chicken", PROTEIN, 2.0, False, False),
        ("Chicken Dumplings", PROTEIN, 2.0, False, False),
        ("Chicken Nuggets", PROTEIN, 2.0, False, False),
        ("Orange Chicken", PROTEIN, 2.0, False, False),
        ("Chicken Samosas", PROTEIN, 2.0, False, False),
        ("Chicken Burger Patty", PROTEIN, 2.0, False, False),
        ("Chicken Tenders", PROTEIN, 2.0, False, False),
        ("Korean BBQ Chicken", PROTEIN, 2.0, False, False),
        ("Shredded Chicken", PROTEIN, 2.0, False, False),
        ("Popcorn Chicken", PROTEIN, 2.0, False, False),
        ("Beef Ravioli", PROTEIN, 3.0, False, False),
        ("Beef Chili", PROTEIN, 3.0, False, False),
        ("Mozzarella Sticks", PROTEIN, 2.0, False, True),
        ("Cheese Pizza Slice", PROTEIN, 2.0, False, True),
        ("Mac & Cheese", PROTEIN, 4.0, False, True),
        ("Egg Patty", PROTEIN, 1.5, False, True),
        ("Scrambled Eggs", PROTEIN, 1.5, False, True),
        ("Cheddar Cheese", PROTEIN, 1.0, False, True),

        # GRAINS - Breakfast
        ("French Toast", GRAIN, 2.0, True, True),
        ("Waffle", GRAIN, 2.0, True, True),
        ("Pancakes", GRAIN, 2.0, True, True),
        ("Mini Croissant", GRAIN, 1.5, True, True),
        ("Whole Grain Toast", GRAIN, 1.0, True, True),
        ("English Muffin", GRAIN, 2.0, True, True),
        ("Hashbrowns", GRAIN, 2.0, True, True),

        # GRAINS - Lunch/Other
        ("Penne Pasta", GRAIN, 4.0, True, True),
        ("White Rice", GRAIN, 4.0, True, True),
        ("Brown Rice", GRAIN, 4.0, True, True),
        ("Jasmine Rice", GRAIN, 4.0, True, True),
        ("Flour Tortilla", GRAIN, 2.0, True, True),

        # GRAINS - Snacks
        ("Cheez-Its", GRAIN, 0.75, True, True),
        ("Animal Crackers", GRAIN, 0.75, True, True),
        ("Goldfish Crackers", GRAIN, 0.75, True, True),
        ("Blueberry Muffin", GRAIN, 2.0, True, True),
        ("Corn Bread", GRAIN, 2.0, True, True),
        ("Corn Muffin", GRAIN, 2.0, True, True),

        # VEGETABLES
        ("Green Beans", VEGETABLE, 2.0, True, True),
        ("Pinto Beans", VEGETABLE, 2.0, True, True),
        ("Kidney Beans", VEGETABLE, 2.0, True, True),
        ("Yams", VEGETABLE, 3.0, True, True),
        ("California Mixed Veggies", VEGETABLE, 2.0, True, True),
        ("Carrots", VEGETABLE, 2.0, True, True),
        ("Corn", VEGETABLE, 2.0, True, True),
        ("Mashed Potatoes", VEGETABLE, 3.0, True, True),
        ("Broccoli", VEGETABLE, 2.0, True, True),
        ("Sweet Potato Fries", VEGETABLE, 3.0, True, True),
        ("Roasted Potatoes", VEGETABLE, 3.0, True, True),
        ("Marinara Sauce", VEGETABLE, 2.0, True, True),

        # FRUITS
        ("Banana", FRUIT, 3.0, True, True),
        ("Strawberries", FRUIT, 2.0, True, True),
        ("Apple", FRUIT, 2.0, True, True),
        ("Orange", FRUIT, 2.0, True, True),
        ("Mandarin Orange", FRUIT, 2.0, True, True),
        ("Apple Slices", FRUIT, 2.0, True, True),
    ]

    # Create food components
    from app.schemas.catering import FoodComponentCreate
    component_map = {}

    for name, type_id, portion, is_vegan, is_veg in food_components_data:
        comp_data = FoodComponentCreate(
            name=name,
            component_type_id=type_id,
            default_portion_oz=Decimal(str(portion)),
            is_vegan=is_vegan,
            is_vegetarian=is_veg,
            tenant_id=tenant_id
        )
        comp = await food_component_crud.create_food_component(db, comp_data)
        component_map[name] = comp.id

    # Meal Items based on actual January 2026 menu
    # Format: (name, desc, meal_type, is_vegan, [(component_name, portion), ...])
    meal_items_data = [
        # ========== BREAKFAST ==========
        ("French Toast w/ Banana", "French toast served with fresh banana", "Breakfast", False,
         [("French Toast", 2.0), ("Banana", 3.0), ("Whole Milk", 6.0)]),
        ("Waffle w/ Strawberries", "Golden waffle with fresh strawberries", "Breakfast", False,
         [("Waffle", 2.0), ("Strawberries", 2.0), ("Whole Milk", 6.0)]),
        ("Pancakes w/ Apple", "Fluffy pancakes with fresh apple", "Breakfast", False,
         [("Pancakes", 2.0), ("Apple", 2.0), ("Whole Milk", 6.0)]),
        ("Mini Croissant w/ Orange", "Mini croissant with orange slices", "Breakfast", False,
         [("Mini Croissant", 1.5), ("Orange", 2.0), ("Whole Milk", 6.0)]),
        ("Egg Patty w/ Toast", "Egg patty with whole grain toast", "Breakfast", False,
         [("Egg Patty", 1.5), ("Whole Grain Toast", 1.0), ("Whole Milk", 6.0)]),
        ("Waffle w/ Banana", "Golden waffle with fresh banana", "Breakfast", False,
         [("Waffle", 2.0), ("Banana", 3.0), ("Whole Milk", 6.0)]),
        ("English Muffin w/ Cream Cheese & Banana", "English muffin with cream cheese and banana", "Breakfast", False,
         [("English Muffin", 2.0), ("Cream Cheese", 1.0), ("Banana", 3.0), ("Whole Milk", 6.0)]),
        ("Hashbrowns w/ Toast", "Crispy hashbrowns with whole grain toast", "Breakfast", False,
         [("Hashbrowns", 2.0), ("Whole Grain Toast", 1.0), ("Whole Milk", 6.0)]),
        ("French Toast w/ Apple", "French toast with fresh apple", "Breakfast", False,
         [("French Toast", 2.0), ("Apple", 2.0), ("Whole Milk", 6.0)]),
        ("Pancakes w/ Orange", "Fluffy pancakes with orange slices", "Breakfast", False,
         [("Pancakes", 2.0), ("Orange", 2.0), ("Whole Milk", 6.0)]),
        ("Pancakes w/ Banana", "Fluffy pancakes with fresh banana", "Breakfast", False,
         [("Pancakes", 2.0), ("Banana", 3.0), ("Whole Milk", 6.0)]),
        ("French Toast w/ Strawberries", "French toast with fresh strawberries", "Breakfast", False,
         [("French Toast", 2.0), ("Strawberries", 2.0), ("Whole Milk", 6.0)]),
        ("Waffle w/ Apple", "Golden waffle with fresh apple", "Breakfast", False,
         [("Waffle", 2.0), ("Apple", 2.0), ("Whole Milk", 6.0)]),
        ("Scrambled Eggs w/ Toast", "Scrambled eggs with whole grain toast", "Breakfast", False,
         [("Scrambled Eggs", 1.5), ("Whole Grain Toast", 1.0), ("Whole Milk", 6.0)]),
        ("Hashbrowns w/ Toast & Orange", "Hashbrowns and toast with orange", "Breakfast", False,
         [("Hashbrowns", 2.0), ("Whole Grain Toast", 1.0), ("Orange", 2.0), ("Whole Milk", 6.0)]),

        # ========== LUNCH ==========
        ("Beef Meatballs w/ Penne & Green Beans", "Savory beef meatballs with penne pasta and green beans", "Lunch", False,
         [("Beef Meatballs", 2.0), ("Penne Pasta", 4.0), ("Green Beans", 2.0), ("Whole Milk", 6.0)]),
        ("Dominican Chicken w/ Rice & Pinto Beans", "Seasoned Dominican chicken with rice and beans", "Lunch", False,
         [("Dominican Chicken", 2.0), ("White Rice", 4.0), ("Pinto Beans", 2.0), ("Whole Milk", 6.0)]),
        ("Mac & Cheese w/ Yams & Mixed Veggies", "Creamy mac and cheese with yams and vegetables", "Lunch", False,
         [("Mac & Cheese", 4.0), ("Yams", 3.0), ("California Mixed Veggies", 2.0), ("Whole Milk", 6.0)]),
        ("Chicken Dumplings w/ Carrots & Corn", "Chicken dumplings with carrots and corn", "Lunch", False,
         [("Chicken Dumplings", 2.0), ("Carrots", 2.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),
        ("Chicken Nuggets w/ Mashed Potatoes & Broccoli", "Crispy chicken nuggets with mashed potatoes and broccoli", "Lunch", False,
         [("Chicken Nuggets", 2.0), ("Mashed Potatoes", 3.0), ("Broccoli", 2.0), ("Whole Milk", 6.0)]),
        ("Orange Chicken w/ Rice & Carrots", "Sweet orange chicken with rice and carrots", "Lunch", False,
         [("Orange Chicken", 2.0), ("White Rice", 4.0), ("Carrots", 2.0), ("Whole Milk", 6.0)]),
        ("Chicken Samosas w/ Corn & Sweet Potato Fries", "Chicken samosas with corn and sweet potato fries", "Lunch", False,
         [("Chicken Samosas", 2.0), ("Corn", 2.0), ("Sweet Potato Fries", 3.0), ("Whole Milk", 6.0)]),
        ("Cheese Pizza w/ Broccoli & Carrots", "Cheese pizza slice with broccoli and carrots", "Lunch", False,
         [("Cheese Pizza Slice", 2.0), ("Broccoli", 2.0), ("Carrots", 2.0), ("Whole Milk", 6.0)]),
        ("Beef Ravioli w/ Marinara & Green Beans", "Beef ravioli with marinara sauce and green beans", "Lunch", False,
         [("Beef Ravioli", 3.0), ("Marinara Sauce", 2.0), ("Green Beans", 2.0), ("Whole Milk", 6.0)]),
        ("Chicken Burger w/ Mashed Potatoes & Corn", "Chicken burger patty with mashed potatoes and corn", "Lunch", False,
         [("Chicken Burger Patty", 2.0), ("Mashed Potatoes", 3.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),
        ("Beef & Bean Burrito w/ Roasted Potato & Corn", "Beef and bean burrito with potatoes and corn", "Lunch", False,
         [("Beef Chili", 2.0), ("Flour Tortilla", 2.0), ("Roasted Potatoes", 3.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),
        ("Mozzarella Sticks w/ Marinara & Green Beans", "Crispy mozzarella sticks with marinara and green beans", "Lunch", False,
         [("Mozzarella Sticks", 2.0), ("Marinara Sauce", 2.0), ("Green Beans", 2.0), ("Whole Milk", 6.0)]),
        ("Beef Meatballs w/ Penne & Carrots", "Beef meatballs with penne pasta and carrots", "Lunch", False,
         [("Beef Meatballs", 2.0), ("Penne Pasta", 4.0), ("Carrots", 2.0), ("Whole Milk", 6.0)]),
        ("Chicken Tenders w/ Mashed Potatoes & Corn", "Crispy chicken tenders with mashed potatoes and corn", "Lunch", False,
         [("Chicken Tenders", 2.0), ("Mashed Potatoes", 3.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),
        ("Beef Chili w/ Brown Rice & Kidney Beans", "Hearty beef chili with brown rice and kidney beans", "Lunch", False,
         [("Beef Chili", 3.0), ("Brown Rice", 4.0), ("Kidney Beans", 2.0), ("Whole Milk", 6.0)]),
        ("Korean BBQ Chicken w/ Jasmine Rice & Corn", "Korean BBQ chicken with jasmine rice and corn", "Lunch", False,
         [("Korean BBQ Chicken", 2.0), ("Jasmine Rice", 4.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),
        ("Shredded Chicken Quesadilla w/ Corn & Potatoes", "Shredded chicken quesadilla with corn and roasted potatoes", "Lunch", False,
         [("Shredded Chicken", 2.0), ("Flour Tortilla", 2.0), ("Cheddar Cheese", 1.0), ("Corn", 2.0), ("Roasted Potatoes", 3.0), ("Whole Milk", 6.0)]),
        ("Popcorn Chicken w/ Mashed Potatoes & Corn", "Popcorn chicken with mashed potatoes and corn", "Lunch", False,
         [("Popcorn Chicken", 2.0), ("Mashed Potatoes", 3.0), ("Corn", 2.0), ("Whole Milk", 6.0)]),

        # ========== SNACKS ==========
        ("Cheez-Its w/ Banana", "Cheez-It crackers with fresh banana", "Snack", False,
         [("Cheez-Its", 0.75), ("Banana", 3.0), ("Whole Milk", 4.0)]),
        ("Animal Crackers w/ Banana", "Animal crackers with fresh banana", "Snack", False,
         [("Animal Crackers", 0.75), ("Banana", 3.0), ("Whole Milk", 4.0)]),
        ("Goldfish Crackers w/ Banana", "Goldfish crackers with fresh banana", "Snack", False,
         [("Goldfish Crackers", 0.75), ("Banana", 3.0), ("Whole Milk", 4.0)]),
        ("Blueberry Muffin w/ Apple", "Blueberry muffin with fresh apple", "Snack", False,
         [("Blueberry Muffin", 2.0), ("Apple", 2.0), ("Whole Milk", 4.0)]),
        ("Corn Bread w/ Orange", "Corn bread with orange slices", "Snack", False,
         [("Corn Bread", 2.0), ("Orange", 2.0), ("Whole Milk", 4.0)]),
        ("Cheez-Its w/ Strawberries", "Cheez-It crackers with fresh strawberries", "Snack", False,
         [("Cheez-Its", 0.75), ("Strawberries", 2.0), ("Whole Milk", 4.0)]),
        ("Corn Muffin w/ Yogurt", "Corn muffin served with yogurt", "Snack", False,
         [("Corn Muffin", 2.0), ("Yogurt", 4.0)]),
        ("Animal Crackers w/ Apple", "Animal crackers with fresh apple", "Snack", False,
         [("Animal Crackers", 0.75), ("Apple", 2.0), ("Whole Milk", 4.0)]),
        ("Mini Croissant w/ Yogurt", "Mini croissant served with yogurt", "Snack", False,
         [("Mini Croissant", 1.5), ("Yogurt", 4.0)]),
        ("Blueberry Muffin w/ Yogurt", "Blueberry muffin served with yogurt", "Snack", False,
         [("Blueberry Muffin", 2.0), ("Yogurt", 4.0)]),
        ("Goldfish Crackers w/ Mandarin Orange", "Goldfish crackers with mandarin oranges", "Snack", False,
         [("Goldfish Crackers", 0.75), ("Mandarin Orange", 2.0), ("Whole Milk", 4.0)]),
        ("Goldfish Crackers w/ Apple Slices", "Goldfish crackers with apple slices", "Snack", False,
         [("Goldfish Crackers", 0.75), ("Apple Slices", 2.0), ("Whole Milk", 4.0)]),
        ("Cheez-Its w/ Apple", "Cheez-It crackers with fresh apple", "Snack", False,
         [("Cheez-Its", 0.75), ("Apple", 2.0), ("Whole Milk", 4.0)]),
    ]

    # Create meal items with components
    for name, desc, meal_type, is_vegan, components in meal_items_data:
        meal_item = CateringMealItem(
            name=name,
            description=desc,
            meal_type=meal_type,
            is_vegan=is_vegan,
            is_vegetarian=True,
            tenant_id=tenant_id
        )
        db.add(meal_item)
        await db.flush()

        for comp_name, portion in components:
            if comp_name in component_map:
                meal_comp = CateringMealComponent(
                    meal_item_id=meal_item.id,
                    food_component_id=component_map[comp_name],
                    portion_oz=Decimal(str(portion))
                )
                db.add(meal_comp)

    await db.commit()

    return RedirectResponse(url="/catering?success=Sample+data+loaded", status_code=303)
