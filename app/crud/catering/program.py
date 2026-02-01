from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.catering import CateringProgram, CateringProgramHoliday
from app.schemas.catering import CateringProgramCreate, CateringProgramUpdate
import uuid
import json


async def create_program(db: AsyncSession, program: CateringProgramCreate):
    """Create a new catering program"""
    new_program = CateringProgram(
        id=str(uuid.uuid4()),
        name=program.name,
        client_name=program.client_name,
        client_email=program.client_email,
        client_phone=program.client_phone,
        address=program.address,
        age_group_id=program.age_group_id,
        total_children=program.total_children,
        vegan_count=program.vegan_count,
        invoice_prefix=program.invoice_prefix,
        service_days=json.dumps(program.service_days),
        meal_types_required=json.dumps(program.meal_types_required),
        start_date=program.start_date,
        end_date=program.end_date,
        is_active=program.is_active,
        tenant_id=program.tenant_id
    )
    db.add(new_program)
    await db.flush()

    # Add holidays
    for holiday in program.holidays:
        program_holiday = CateringProgramHoliday(
            id=str(uuid.uuid4()),
            program_id=new_program.id,
            holiday_date=holiday.holiday_date,
            description=holiday.description
        )
        db.add(program_holiday)

    await db.commit()
    await db.refresh(new_program)
    return new_program


async def get_programs(db: AsyncSession, tenant_id: int, active_only: bool = False):
    """Get all programs for a tenant"""
    query = select(CateringProgram).where(CateringProgram.tenant_id == tenant_id)

    if active_only:
        query = query.where(CateringProgram.is_active == True)

    query = query.options(
        selectinload(CateringProgram.age_group),
        selectinload(CateringProgram.holidays)
    ).order_by(CateringProgram.name)

    result = await db.execute(query)
    return result.scalars().all()


async def get_program(db: AsyncSession, program_id: str, tenant_id: int):
    """Get a specific program"""
    result = await db.execute(
        select(CateringProgram)
        .where(CateringProgram.id == program_id, CateringProgram.tenant_id == tenant_id)
        .options(
            selectinload(CateringProgram.age_group),
            selectinload(CateringProgram.holidays)
        )
    )
    return result.scalar_one_or_none()


async def update_program(db: AsyncSession, program_id: str, tenant_id: int, updates: CateringProgramUpdate):
    """Update a program"""
    program = await get_program(db, program_id, tenant_id)
    if not program:
        return None

    # Support both Pydantic v1 (.dict()) and v2 (.model_dump())
    if hasattr(updates, 'model_dump'):
        update_data = updates.model_dump(exclude_unset=True, exclude={'holidays'})
    else:
        update_data = updates.dict(exclude_unset=True, exclude={'holidays'})

    # Handle JSON fields
    if 'service_days' in update_data:
        update_data['service_days'] = json.dumps(update_data['service_days'])
    if 'meal_types_required' in update_data:
        update_data['meal_types_required'] = json.dumps(update_data['meal_types_required'])

    for key, value in update_data.items():
        setattr(program, key, value)

    # Update holidays if provided
    if updates.holidays is not None:
        # Delete existing holidays
        for holiday in program.holidays:
            await db.delete(holiday)

        # Add new holidays
        for holiday in updates.holidays:
            program_holiday = CateringProgramHoliday(
                id=str(uuid.uuid4()),
                program_id=program.id,
                holiday_date=holiday.holiday_date,
                description=holiday.description
            )
            db.add(program_holiday)

    await db.commit()
    await db.refresh(program)
    return program


async def delete_program(db: AsyncSession, program_id: str, tenant_id: int):
    """Delete a program"""
    program = await get_program(db, program_id, tenant_id)
    if program:
        await db.delete(program)
        await db.commit()
    return program


async def increment_invoice_number(db: AsyncSession, program_id: str) -> str:
    """Increment and return the next invoice number for a program"""
    program = await db.get(CateringProgram, program_id)
    if not program:
        return None

    program.last_invoice_number += 1
    next_number = program.last_invoice_number
    await db.commit()

    return f"{program.invoice_prefix}-{next_number:04d}"
