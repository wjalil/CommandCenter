"""
Catering HTML Routes

Serves Jinja2 templates for the catering UI
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import date
import json

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

    # Parse JSON fields for display
    for program in programs:
        program.service_days = json.loads(program.service_days)
        program.meal_types_required = json.loads(program.meal_types_required)

    return templates.TemplateResponse("catering/programs_list.html", {
        "request": request,
        "programs": programs,
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


@router.post("/programs/create")
async def program_create(
    request: Request,
    name: str = Form(...),
    client_name: str = Form(...),
    client_email: Optional[str] = Form(None),
    client_phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    age_group_id: int = Form(...),
    total_children: int = Form(...),
    vegan_count: int = Form(0),
    invoice_prefix: str = Form(...),
    service_days: List[str] = Form(...),
    meal_types_required: List[str] = Form(...),
    start_date: date = Form(...),
    end_date: Optional[str] = Form(None),
    is_active: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Create a new program"""
    tenant_id = request.state.tenant_id

    # Validate vegan count doesn't exceed total children
    if vegan_count > total_children:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Vegan count ({vegan_count}) cannot exceed total children ({total_children})"
        )

    # Parse end_date - convert empty string to None
    parsed_end_date = None
    if end_date and end_date.strip():
        from datetime import datetime
        parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

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
        invoice_prefix=invoice_prefix,
        service_days=service_days,
        meal_types_required=meal_types_required,
        start_date=start_date,
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

    # Parse JSON fields for form display
    program.service_days = json.loads(program.service_days)
    program.meal_types_required = json.loads(program.meal_types_required)

    age_groups = await cacfp_rules.get_all_age_groups(db)

    return templates.TemplateResponse("catering/program_form.html", {
        "request": request,
        "program": program,
        "age_groups": age_groups,
    })


@router.post("/programs/{program_id}/update")
async def program_update(
    request: Request,
    program_id: str,
    name: str = Form(...),
    client_name: str = Form(...),
    client_email: Optional[str] = Form(None),
    client_phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    age_group_id: int = Form(...),
    total_children: int = Form(...),
    vegan_count: int = Form(0),
    invoice_prefix: str = Form(...),
    service_days: List[str] = Form(...),
    meal_types_required: List[str] = Form(...),
    start_date: date = Form(...),
    end_date: Optional[str] = Form(None),
    is_active: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """Update a program"""
    tenant_id = request.state.tenant_id

    # Validate vegan count doesn't exceed total children
    if vegan_count > total_children:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Vegan count ({vegan_count}) cannot exceed total children ({total_children})"
        )

    # Parse end_date - convert empty string to None
    parsed_end_date = None
    if end_date and end_date.strip():
        from datetime import datetime
        parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

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
        invoice_prefix=invoice_prefix,
        service_days=service_days,
        meal_types_required=meal_types_required,
        start_date=start_date,
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

    # If copying from existing menu, duplicate the menu days
    if copy_from_menu_id:
        source_menu = await menu_crud.get_monthly_menu(db, copy_from_menu_id, tenant_id)
        if source_menu and source_menu.menu_days:
            from datetime import datetime
            from calendar import monthrange

            # Get number of days in target month
            num_days = monthrange(year, month)[1]

            # Map source days to target days (by day of month)
            for source_day in source_menu.menu_days:
                source_day_num = source_day.service_date.day

                # Only copy if target month has this day number
                if source_day_num <= num_days:
                    target_date = datetime(year, month, source_day_num).date()

                    from app.schemas.catering import MenuDayAssignment
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
                    await menu_crud.upsert_menu_day(db, monthly_menu.id, day_data)

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

    # Parse program settings
    service_days = json.loads(program.service_days)
    meal_types = json.loads(program.meal_types_required)

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
                    'menu_day': None
                })
            else:
                date_obj = dt_date(monthly_menu.year, monthly_menu.month, day_num)
                date_str = date_obj.isoformat()
                day_name = date_obj.strftime('%A')
                is_service_day = day_name in service_days

                week_data.append({
                    'day': day_num,
                    'date': date_str,
                    'in_month': True,
                    'is_service_day': is_service_day,
                    'menu_day': menu_days_dict.get(date_str)
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
    })


# ==================== INVOICES ====================

@router.get("/invoices")
async def invoices_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    """List invoices"""
    tenant_id = request.state.tenant_id
    invoices = await invoice_crud.get_invoices(db, tenant_id)

    return templates.TemplateResponse("catering/invoices_list.html", {
        "request": request,
        "invoices": invoices,
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

    return RedirectResponse(
        url=f"/catering/invoices?message={len(invoices)} invoices generated",
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

    # Get menu day with all meal item details
    from app.models.catering import CateringMenuDay
    result = await db.execute(
        select(CateringMenuDay)
        .where(CateringMenuDay.id == invoice.menu_day_id)
        .options(
            selectinload(CateringMenuDay.breakfast_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.breakfast_vegan_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.lunch_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.lunch_vegan_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.snack_item).selectinload('components').selectinload('food_component'),
            selectinload(CateringMenuDay.snack_vegan_item).selectinload('components').selectinload('food_component'),
        )
    )
    menu_day = result.scalar_one_or_none()

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
    """Download invoice as PDF (placeholder - use browser print for now)"""
    # For now, redirect to view page where user can print
    # TODO: Implement proper PDF generation with ReportLab
    return RedirectResponse(url=f"/catering/invoices/{invoice_id}/view", status_code=303)


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
