# scripts/import_shopping_items_simple.py
"""
One-off import for Items (+auto-create Category, BusinessLine, Supplier)
Accepts CSV or TSV; handles header variants like 'Catergory' and 'Business Line'.

Usage:
  ENV=development python -m scripts.import_shopping_items_simple --tenant 1 --path ./data/items.csv --dry-run
  ENV=production  python -m scripts.import_shopping_items_simple --tenant 1 --path ./data/items.csv
"""

import argparse, csv, os, sys, io
from typing import Dict, Any, List, Optional

# Load env like the app
from dotenv import load_dotenv
env_file = f".env.{os.getenv('ENV', 'development')}"
load_dotenv(env_file) if os.path.exists(env_file) else load_dotenv()

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session
from app.models.shopping import BusinessLine, Category, Supplier, Item

# ---- Header normalization ----
HEADER_MAP = {
    "item": "name",
    "items": "name",
    "product": "name",
    "name": "name",

    "category": "category",
    "cat": "category",

    "supplier": "default_supplier",
    "default_supplier": "default_supplier",
    "vendor": "default_supplier",

    "business line": "business_line",
    "business_line": "business_line",
    "line": "business_line",
    "bl": "business_line",

    "unit": "unit",
    "uom": "unit",
    "par": "par_level",
    "par_level": "par_level",
    "notes": "notes",
}

def norm_header(h: str) -> str:
    return HEADER_MAP.get((h or "").strip().lower(), (h or "").strip().lower())

def coalesce_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for k, v in raw.items():
        row[norm_header(k)] = v
    return row

def as_int(val, default=0):
    if val is None: return default
    s = str(val).strip()
    if s == "" or s.lower() in {"none", "nan"}: return default
    try:
        return int(float(s))
    except Exception:
        return default

# ---- DB helpers ----
async def get_or_create_by_name(db: AsyncSession, model, tenant_id: int, name: Optional[str]):
    if not name: return None
    name = name.strip()
    q = await db.execute(select(model).where(model.tenant_id == tenant_id, model.name == name))
    m = q.scalars().first()
    if m: return m
    m = model(tenant_id=tenant_id, name=name)
    db.add(m)
    await db.flush()
    return m

async def upsert_item(db: AsyncSession, tenant_id: int, row: Dict[str, Any]) -> bool:
    """Returns True if created, False if updated."""
    name = (row.get("name") or "").strip()
    if not name:
        raise ValueError("Missing 'Item'/'Name' column value")

    category_name = (row.get("category") or "").strip() or None
    bl_name      = (row.get("business_line") or "").strip() or None
    unit         = (row.get("unit") or "ea").strip()
    par_level    = as_int(row.get("par_level"), default=0)
    notes        = (row.get("notes") or "").strip()
    supplier_name= (row.get("default_supplier") or "").strip() or None

    category     = await get_or_create_by_name(db, Category, tenant_id, category_name) if category_name else None
    business_line= await get_or_create_by_name(db, BusinessLine, tenant_id, bl_name) if bl_name else None
    supplier     = await get_or_create_by_name(db, Supplier, tenant_id, supplier_name) if supplier_name else None

    q = await db.execute(select(Item).where(Item.tenant_id == tenant_id, Item.name == name))
    item = q.scalars().first()
    if item:
        item.category_id       = category.id if category else None
        item.business_line_id  = business_line.id if business_line else None
        item.unit              = unit
        item.par_level         = par_level
        item.notes             = notes
        item.default_supplier_id = supplier.id if supplier else None
        return False
    else:
        item = Item(
            tenant_id=tenant_id,
            name=name,
            category_id=category.id if category else None,
            business_line_id=business_line.id if business_line else None,
            unit=unit,
            par_level=par_level,
            notes=notes,
            default_supplier_id=supplier.id if supplier else None,
        )
        db.add(item)
        return True

# ---- File reading ----
def read_delimited(path: str) -> List[Dict[str, Any]]:
    """Reads CSV/TSV. Auto-detects delimiter. Handles UTF-8 BOM and Unicode (e.g., 'Café')."""
    with open(path, "rb") as fb:
        raw_bytes = fb.read()
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
    except Exception:
        # fallback: if we see lots of tabs, use TSV; else CSV
        dialect = csv.excel_tab if sample.count("\t") > sample.count(",") else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [coalesce_row(r) for r in reader]

# ---- CLI ----
async def main():
    ap = argparse.ArgumentParser(description="Import Items from CSV/TSV with auto-created lookups")
    ap.add_argument("--tenant", type=int, required=True, help="Tenant ID to import into")
    ap.add_argument("--path", required=True, help="Path to CSV/TSV")
    ap.add_argument("--dry-run", action="store_true", help="Validate and show counts without committing")
    args = ap.parse_args()

    rows = read_delimited(args.path)
    if not rows:
        print("No rows found."); return

    created, updated, errors = 0, 0, []
    async with async_session() as db:
        for i, rr in enumerate(rows, start=2):  # header = row 1
            try:
                # peek existence for stats (avoid double work by checking name)
                name = (rr.get("name") or "").strip()
                if not name:
                    raise ValueError("Row missing Item/Name")
                # upsert
                was_created = await upsert_item(db, args.tenant, rr)
                if was_created: created += 1
                else: updated += 1
            except Exception as e:
                errors.append({"row": i, "error": str(e), "raw": rr})
        if args.dry_run:
            await db.rollback()
        else:
            await db.commit()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Created: {created}, Updated: {updated}, Errors: {len(errors)}")
    if errors:
        print("Sample errors (up to 20):")
        for e in errors[:20]:
            print(f"  Row {e['row']}: {e['error']} | Raw: {e['raw']}")

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
