"""
Master Menu routes (HTML)

One tenant-wide menu per month, uploaded from a CSV, reviewed on a preview screen,
then published into every program's monthly menu in one step.

    GET  /catering/master-menus                     list
    GET  /catering/master-menus/upload              upload form
    GET  /catering/master-menus/template.csv        blank sheet to fill in
    POST /catering/master-menus/upload              parse file -> preview
    POST /catering/master-menus/import/preview      re-check after edits -> preview
    POST /catering/master-menus/import/confirm      save master menu
    GET  /catering/master-menus/{id}                grid + publish panel
    POST /catering/master-menus/{id}/publish        publish to selected programs
    POST /catering/master-menus/{id}/delete
"""
import json
import re
from calendar import month_name
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin_user
from app.db import get_db
from app.models.catering import (
    CACFPComponentType,
    CateringMasterMenu,
    CateringMasterMenuComponent,
    CateringMasterMenuDay,
    CateringMenuDay,
    CateringMonthlyMenu,
    CateringProgram,
    FoodComponent,
)
from app.models.user import User
from app.services.catering import master_menu_import as mmi
from app.services.catering.master_menu_publish import (
    LOCKED_STATUSES,
    load_master_menu,
    program_slots,
    publish_master_menu,
    slot_mapping,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_UPLOAD_BYTES = 1_000_000
TEMPLATE_CSV = (
    "Date,Day,Breakfast,Breakfast Fruit,Lunch,Lunch Vegetable,Lunch Fruit,PM Snack,Notes\n"
    "10/1/2026,Thursday,Mini Croissant,Pineapple,Chicken Tacos w/ Tortilla,Fajita Peppers & Corn,Pineapple,Yogurt + Pineapple,\n"
    "10/12/2026,Monday,OFF,,OFF,,,,Columbus Day\n"
)


# ==================== helpers ====================

def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


async def _tenant_components(db: AsyncSession, tenant_id: int) -> List[FoodComponent]:
    result = await db.execute(
        select(FoodComponent).where(FoodComponent.tenant_id == tenant_id).order_by(FoodComponent.name)
    )
    return result.scalars().all()


async def _component_types(db: AsyncSession) -> List[CACFPComponentType]:
    result = await db.execute(select(CACFPComponentType).order_by(CACFPComponentType.sort_order))
    return result.scalars().all()


async def _existing_master(db: AsyncSession, tenant_id: int, name: str, month: int, year: int) -> Optional[CateringMasterMenu]:
    result = await db.execute(select(CateringMasterMenu).where(
        CateringMasterMenu.tenant_id == tenant_id,
        func.lower(CateringMasterMenu.name) == name.strip().lower(),
        CateringMasterMenu.month == month,
        CateringMasterMenu.year == year,
    ))
    return result.scalars().first()


def _cell_edits(form) -> Dict[Tuple[int, int], str]:
    edits = {}
    for key, value in form.items():
        m = re.fullmatch(r"tok__(\d+)__(\d+)", key)
        if m:
            edits[(int(m.group(1)), int(m.group(2)))] = value
    return edits


def _decisions(form) -> Dict[str, dict]:
    """The user's per-name choices from the preview, keyed by match key."""
    decisions = {}
    for key, value in form.items():
        m = re.fullmatch(r"key__(\d+)", key)
        if not m:
            continue
        i = m.group(1)
        decisions[value] = {
            "choice": form.get(f"choice__{i}", ""),
            "new_type": form.get(f"newtype__{i}", ""),
            "new_name": (form.get(f"newname__{i}") or "").strip(),
        }
    return decisions


async def _render_preview(
    request: Request, db: AsyncSession, tenant_id: int, sheet: mmi.Sheet, name: str,
    source_filename: str, decisions: Optional[Dict[str, dict]] = None, errors: Optional[List[str]] = None,
):
    components = await _tenant_components(db, tenant_id)
    types = await _component_types(db)
    type_id_by_name = {t.name: t.id for t in types}
    matches = mmi.match_tokens(sheet, [(c.id, c.name) for c in components])

    decisions = decisions or {}
    rows = []
    for m in matches.values():
        d = decisions.get(m.key, {})
        if d.get("choice"):
            choice = d["choice"]
        else:
            choice = f"c:{m.component_id}" if m.component_id else "new"
        rows.append({
            "m": m,
            "choice": choice,
            "new_type": int(d["new_type"]) if d.get("new_type") else type_id_by_name.get(m.guessed_type),
            "new_name": d.get("new_name") or m.name,
        })
    status_by_key = {r["m"].key: ("new" if r["choice"] == "new" else r["m"].status) for r in rows}

    existing = await _existing_master(db, tenant_id, name, sheet.month, sheet.year)
    return templates.TemplateResponse("catering/master_menu_preview.html", {
        "request": request,
        "sheet": sheet,
        "sheet_json": json.dumps(sheet.to_json_dict()),
        "name": name,
        "source_filename": source_filename,
        "month_label": f"{month_name[sheet.month]} {sheet.year}",
        "match_rows": rows,
        "status_by_key": status_by_key,
        "match_key": mmi.match_key,
        "components": components,
        "component_types": types,
        "existing": existing,
        "errors": errors or [],
        "counts": {
            "days": sum(1 for r in sheet.rows if not r.closed_reason),
            "closed": sum(1 for r in sheet.rows if r.closed_reason),
            "matched": sum(1 for r in rows if r["choice"] != "new" and r["m"].status == "matched"),
            "suggested": sum(1 for r in rows if r["choice"] != "new" and r["m"].status == "suggested"),
            "new": sum(1 for r in rows if r["choice"] == "new"),
        },
    })


def _grid_columns(master: CateringMasterMenu) -> List[Tuple[str, bool]]:
    present = {(c.meal_slot, c.is_vegan) for d in master.days for c in d.components}
    return [(slot, vegan) for slot in mmi.SLOT_ORDER for vegan in (False, True) if (slot, vegan) in present]


async def _render_master(request: Request, db: AsyncSession, master: CateringMasterMenu, results=None, form_opts=None):
    tenant_id = master.tenant_id
    columns = _grid_columns(master)
    grid = []
    for day in master.days:
        cells = {}
        for comp in day.components:
            cells.setdefault((comp.meal_slot, comp.is_vegan), []).append(comp.food_component.name if comp.food_component else "?")
        grid.append({"day": day, "cells": [cells.get(col, []) for col in columns]})

    programs = (await db.execute(
        select(CateringProgram)
        .where(CateringProgram.tenant_id == tenant_id, CateringProgram.is_active == True)  # noqa: E712
        .order_by(CateringProgram.name)
    )).scalars().all()
    menus = (await db.execute(
        select(CateringMonthlyMenu)
        .where(
            CateringMonthlyMenu.tenant_id == tenant_id,
            CateringMonthlyMenu.month == master.month,
            CateringMonthlyMenu.year == master.year,
            CateringMonthlyMenu.menu_type == "regular",
        )
        .options(selectinload(CateringMonthlyMenu.master_menu))
    )).scalars().all()
    menus_by_program = {m.program_id: m for m in menus}

    day_counts = {}
    if menus:
        rows = (await db.execute(
            select(
                CateringMenuDay.monthly_menu_id,
                func.count(CateringMenuDay.id),
                func.sum(case((CateringMenuDay.is_customized == True, 1), else_=0)),  # noqa: E712
            )
            .where(CateringMenuDay.monthly_menu_id.in_([m.id for m in menus]))
            .group_by(CateringMenuDay.monthly_menu_id)
        )).all()
        day_counts = {r[0]: (r[1], int(r[2] or 0)) for r in rows}

    master_slots = {c.meal_slot for d in master.days for c in d.components}
    program_rows = []
    for p in programs:
        menu = menus_by_program.get(p.id)
        total_days, customized = day_counts.get(menu.id, (0, 0)) if menu else (0, 0)
        mapping = slot_mapping(program_slots(p), master_slots)
        if not menu:
            state, default_checked = "new", True
        elif menu.master_menu_id == master.id:
            state, default_checked = "linked", True
        elif menu.master_menu_id:
            state, default_checked = "other_master", False
        elif total_days:
            state, default_checked = "hand_built", False
        else:
            state, default_checked = "empty", True
        locked = bool(menu and menu.status in LOCKED_STATUSES)
        program_rows.append({
            "program": p,
            "menu": menu,
            "state": state,
            "locked": locked,
            "checked": default_checked and not locked and bool(mapping),
            "total_days": total_days,
            "customized": customized,
            "slots": [mmi.SLOT_LABELS[s] for s in dict.fromkeys(mapping.values())],
            "no_slots": not mapping,
        })

    return templates.TemplateResponse("catering/master_menu_view.html", {
        "request": request,
        "master": master,
        "month_label": f"{month_name[master.month]} {master.year}",
        "columns": [{"label": mmi.SLOT_LABELS[s] + (" (Vegan)" if v else ""), "slot": s} for s, v in columns],
        "grid": grid,
        "program_rows": program_rows,
        "results": results,
        "imported": request.query_params.get("imported") == "1",
        "created_count": request.query_params.get("created", "0"),
        "opts": form_opts or {"include_locked": False, "overwrite_customized": False, "closed_as_holidays": True},
    })


# ==================== list / upload ====================

@router.get("/master-menus")
async def master_menus_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    masters = (await db.execute(
        select(CateringMasterMenu)
        .where(CateringMasterMenu.tenant_id == tenant_id)
        .order_by(CateringMasterMenu.year.desc(), CateringMasterMenu.month.desc(), CateringMasterMenu.name)
    )).scalars().all()

    stats = {}
    if masters:
        ids = [m.id for m in masters]
        day_rows = (await db.execute(
            select(CateringMasterMenuDay.master_menu_id, func.count(CateringMasterMenuDay.id))
            .where(CateringMasterMenuDay.master_menu_id.in_(ids), CateringMasterMenuDay.is_closed == False)  # noqa: E712
            .group_by(CateringMasterMenuDay.master_menu_id)
        )).all()
        program_rows = (await db.execute(
            select(CateringMonthlyMenu.master_menu_id, func.count(CateringMonthlyMenu.id))
            .where(CateringMonthlyMenu.master_menu_id.in_(ids))
            .group_by(CateringMonthlyMenu.master_menu_id)
        )).all()
        days = dict(day_rows)
        progs = dict(program_rows)
        stats = {mid: {"days": days.get(mid, 0), "programs": progs.get(mid, 0)} for mid in ids}

    return templates.TemplateResponse("catering/master_menus_list.html", {
        "request": request,
        "masters": masters,
        "stats": stats,
        "month_name": month_name,
    })


@router.get("/master-menus/template.csv")
async def master_menu_template(user: User = Depends(get_current_admin_user)):
    return Response(
        content=TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="master_menu_template.csv"'},
    )


@router.get("/master-menus/upload")
async def master_menu_upload_form(
    request: Request,
    user: User = Depends(get_current_admin_user),
):
    return templates.TemplateResponse("catering/master_menu_upload.html", {
        "request": request, "error": None, "name": "Standard",
    })


@router.post("/master-menus/upload")
async def master_menu_upload(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form("Standard"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    name = (name or "").strip() or "Standard"
    filename = file.filename or "menu.csv"

    def form_error(msg):
        return templates.TemplateResponse("catering/master_menu_upload.html", {
            "request": request, "error": msg, "name": name,
        }, status_code=400)

    if filename.lower().endswith((".xlsx", ".xls", ".numbers")):
        return form_error("Please save the spreadsheet as CSV first (File → Save As / Download → CSV) and upload that.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return form_error("That file is over 1 MB — a monthly menu CSV should be a few KB.")

    components = await _tenant_components(db, tenant_id)
    try:
        sheet = mmi.parse_csv(_decode(raw), [c.name for c in components])
    except mmi.ImportError_ as e:
        return form_error(str(e))
    return await _render_preview(request, db, tenant_id, sheet, name, filename)


def _sheet_from_form(form) -> mmi.Sheet:
    sheet = mmi.Sheet.from_json_dict(json.loads(form["sheet_json"]))
    mmi.apply_token_edits(sheet, _cell_edits(form))
    return sheet


@router.post("/master-menus/import/preview")
async def master_menu_import_preview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    form = await request.form()
    sheet = _sheet_from_form(form)
    return await _render_preview(
        request, db, tenant_id, sheet, (form.get("name") or "Standard").strip(),
        form.get("source_filename") or "", decisions=_decisions(form),
    )


@router.post("/master-menus/import/confirm")
async def master_menu_import_confirm(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    form = await request.form()
    sheet = _sheet_from_form(form)
    name = (form.get("name") or "Standard").strip()
    source_filename = form.get("source_filename") or ""
    decisions = _decisions(form)

    existing = await _existing_master(db, tenant_id, name, sheet.month, sheet.year)
    if existing and form.get("replace_existing") != "1":
        return await _render_preview(
            request, db, tenant_id, sheet, name, source_filename, decisions,
            errors=[f"A '{existing.name}' master menu for {month_name[sheet.month]} {sheet.year} already exists. "
                    "Tick 'Replace it' to overwrite it, or use a different name."],
        )

    components = await _tenant_components(db, tenant_id)
    by_id = {c.id: c for c in components}
    by_norm = {mmi.normalize(c.name): c for c in components}
    types = {t.id: t for t in await _component_types(db)}
    type_id_by_name = {t.name: t.id for t in types.values()}
    matches = mmi.match_tokens(sheet, [(c.id, c.name) for c in components])

    # Resolve every sheet name to a component id, creating the new ones
    resolved: Dict[str, int] = {}
    created = 0
    for m in matches.values():
        d = decisions.get(m.key, {})
        choice = d.get("choice") or (f"c:{m.component_id}" if m.component_id else "new")
        if choice.startswith("c:") and choice[2:].isdigit() and int(choice[2:]) in by_id:
            resolved[m.key] = int(choice[2:])
            continue
        new_name = mmi.clean_token(d.get("new_name") or m.name)
        hit = by_norm.get(mmi.normalize(new_name))
        if hit:
            resolved[m.key] = hit.id
            continue
        type_id = int(d["new_type"]) if (d.get("new_type") or "").isdigit() and int(d["new_type"]) in types else type_id_by_name.get(m.guessed_type)
        if type_id is None:
            type_id = next(iter(types))
        comp = FoodComponent(
            name=new_name,
            component_type_id=type_id,
            default_portion_oz=Decimal(str(mmi.DEFAULT_PORTION_OZ.get(types[type_id].name, 0.5))),
            is_vegan=False,
            is_vegetarian=mmi.guess_vegetarian(new_name),
            tenant_id=tenant_id,
        )
        db.add(comp)
        await db.flush()
        by_id[comp.id] = comp
        by_norm[mmi.normalize(new_name)] = comp
        resolved[m.key] = comp.id
        created += 1

    if existing:
        master = await load_master_menu(db, existing.id, tenant_id)
        master.days.clear()
        await db.flush()
        master.source_filename = source_filename or master.source_filename
    else:
        master = CateringMasterMenu(
            tenant_id=tenant_id, name=name, month=sheet.month, year=sheet.year,
            status="draft", source_filename=source_filename,
        )
        master.days = []
        db.add(master)

    for row in sheet.rows:
        day = CateringMasterMenuDay(
            service_date=row.date_obj,
            is_closed=bool(row.closed_reason),
            closed_reason=row.closed_reason,
            notes=row.notes,
        )
        day.components = []
        seen = set()
        order_by_slot: Dict[Tuple[str, bool], int] = {}
        for col, tokens in zip(sheet.columns, row.cells):
            for token in tokens:
                comp_id = resolved.get(mmi.match_key(token))
                slot_key = (col.slot, col.is_vegan)
                if comp_id is None or (comp_id,) + slot_key in seen:
                    continue  # e.g. same fruit listed under Breakfast Fruit twice
                seen.add((comp_id,) + slot_key)
                order_by_slot[slot_key] = order_by_slot.get(slot_key, -1) + 1
                day.components.append(CateringMasterMenuComponent(
                    component_id=comp_id, meal_slot=col.slot, is_vegan=col.is_vegan,
                    sort_order=order_by_slot[slot_key],
                ))
        master.days.append(day)

    await db.commit()
    return RedirectResponse(
        url=f"/catering/master-menus/{master.id}?imported=1&created={created}", status_code=303,
    )


# ==================== view / publish ====================

@router.get("/master-menus/{master_id}")
async def master_menu_view(
    request: Request,
    master_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    master = await load_master_menu(db, master_id, request.state.tenant_id)
    if not master:
        return RedirectResponse(url="/catering/master-menus", status_code=303)
    return await _render_master(request, db, master)


@router.post("/master-menus/{master_id}/publish")
async def master_menu_publish(
    request: Request,
    master_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    tenant_id = request.state.tenant_id
    master = await load_master_menu(db, master_id, tenant_id)
    if not master:
        return RedirectResponse(url="/catering/master-menus", status_code=303)
    form = await request.form()
    opts = {
        "include_locked": form.get("include_locked") == "1",
        "overwrite_customized": form.get("overwrite_customized") == "1",
        "closed_as_holidays": form.get("closed_as_holidays") == "1",
    }
    program_ids = form.getlist("program_ids")
    results = []
    if program_ids:
        results = await publish_master_menu(db, master, program_ids, **opts)
        db.expire_all()
    master = await load_master_menu(db, master_id, tenant_id)
    return await _render_master(request, db, master, results=results, form_opts=opts)


@router.post("/master-menus/{master_id}/delete")
async def master_menu_delete(
    request: Request,
    master_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """Deletes the master menu only; program menus already published keep their days."""
    master = await load_master_menu(db, master_id, request.state.tenant_id)
    if master:
        await db.delete(master)
        await db.commit()
    return RedirectResponse(url="/catering/master-menus", status_code=303)
