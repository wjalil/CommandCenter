"""
Master Menu CSV Import

Turns a kitchen's monthly menu spreadsheet (saved as CSV) into a structure the
preview screen can show and the confirm step can save:

    Date,Day,Breakfast,Breakfast Fruit,Lunch,Lunch Vegetable,Lunch Fruit,PM Snack
    10/1/2026,Thursday,Mini Croissant,Pineapple,Chicken Tacos w/ Tortilla,...

- Headers map to a meal slot by keyword ("Lunch Vegetable" -> lunch, type hint
  Vegetable; "Vegan Lunch" -> lunch, vegan). Date is required; Day is ignored;
  Notes becomes the day's note.
- Each cell is split into food components on "w/", "with", "+", "," and "&"
  ("Chicken Nuggets w/ Mashed Potatoes & Bread" -> 3 components), except when the
  whole phrase is already a known component ("Carrot & Cucumber Sticks").
- A row whose meal cells say OFF / CLOSED / HOLIDAY is a closed day.
- Every distinct component name is matched to the tenant's FoodComponents
  (exact, then singular/plural, then a close-spelling suggestion); anything left
  is created on confirm with a CACFP type guessed from the column and keywords.

Everything here is pure (no DB) so it can be re-run on each preview round-trip.
"""
import csv
import difflib
import io
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

SLOT_LABELS = {
    "breakfast": "Breakfast",
    "am_snack": "AM Snack",
    "lunch": "Lunch",
    "snack": "Snack",
    "pm_snack": "PM Snack",
}
SLOT_ORDER = list(SLOT_LABELS)

CLOSED_WORDS = {"off", "closed", "holiday", "no school", "no service", "school closed"}

# CACFP component type names, as seeded in cacfp_component_types
MILK, MEAT, GRAIN, VEG, FRUIT = "Milk", "Meat/Meat Alternate", "Grain", "Vegetable", "Fruit"

# Child 3-5 lunch minimums — only a starting portion for components the import creates;
# the kitchen can adjust it on the Food Components page.
DEFAULT_PORTION_OZ = {MILK: 6.0, MEAT: 1.5, GRAIN: 0.5, VEG: 0.25, FRUIT: 0.25}

# Header words that pin a column's component type ("Lunch Fruit", "Breakfast Grain")
HEADER_TYPE_WORDS = [
    ("vegetable", VEG), ("veggie", VEG), ("veg", VEG),
    ("fruit", FRUIT), ("grain", GRAIN), ("bread", GRAIN),
    ("milk", MILK), ("protein", MEAT), ("meat", MEAT), ("entree", MEAT), ("entrée", MEAT),
]

# Checked in this order, so "Orange Chicken" is a protein and "Cornbread" a grain
TYPE_KEYWORDS: List[Tuple[str, List[str]]] = [
    (MILK, ["milk"]),
    (MEAT, [
        "chicken", "beef", "turkey", "pork", "ham", "fish", "tuna", "salmon", "meatball", "burger",
        "nugget", "sausage", "bolognese", "egg", "cheese", "yogurt", "yoghurt", "hummus", "tofu",
        "lentil", "bean", "pizza", "parmesan", "taco", "chili",
    ]),
    (GRAIN, [
        "cornbread", "croissant", "muffin", "bagel", "waffle", "pancake", "toast", "cereal", "oatmeal",
        "grits", "rice", "pasta", "spaghetti", "noodle", "macaroni", "bun", "bread", "tortilla",
        "cracker", "roll", "biscuit", "pita", "pretzel", "graham", "granola", "couscous", "quinoa",
    ]),
    (VEG, [
        "broccoli", "corn", "carrot", "pepper", "yam", "potato", "zucchini", "vegetable", "veggie",
        "green bean", "peas", "spinach", "cucumber", "lettuce", "salad", "tomato", "cauliflower",
        "squash", "celery", "kale", "cabbage", "edamame",
    ]),
    (FRUIT, [
        "apple", "banana", "orange", "pineapple", "cantaloupe", "strawberr", "blueberr", "berries",
        "watermelon", "pear", "honeydew", "grape", "peach", "mango", "melon", "kiwi", "raisin",
        "plum", "tangerine", "clementine", "mandarin", "fruit", "cherr",
    ]),
]
SLOT_DEFAULT_TYPE = {"breakfast": GRAIN, "lunch": MEAT, "snack": GRAIN, "am_snack": GRAIN, "pm_snack": GRAIN}
ANIMAL_WORDS = ["chicken", "beef", "turkey", "pork", "ham", "fish", "tuna", "salmon", "meatball",
                "sausage", "bolognese", "nugget", "pepperoni", "bacon"]

# Splits a cell into components. "&"/"and" are handled separately (see split_cell).
_HARD_SPLIT = re.compile(r"\s+w/\s*|\s+with\s+|\s*\+\s*|\s*,\s*|\s*;\s*|\s*/\s+|\n", re.IGNORECASE)
_SOFT_SPLIT = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)
# "Carrot & Cucumber Sticks" shares its noun, so it's one item, not "Carrot" + "Cucumber Sticks"
# Dishes whose "&" is part of the name, before the tenant has them as components
WHOLE_DISHES = ["Mac & Cheese", "Macaroni & Cheese", "Rice & Beans", "Beans & Rice", "Peanut Butter & Jelly",
                "Ham & Cheese", "Franks & Beans", "Fish & Chips", "Chips & Salsa", "Cheese & Crackers"]
SHARED_NOUNS = {"sticks", "slices", "bites", "chips", "cubes", "wedges", "fries", "strips", "coins", "spears"}


# ==================== data shapes ====================

@dataclass
class ColumnSpec:
    header: str
    slot: str
    is_vegan: bool = False
    type_hint: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{SLOT_LABELS[self.slot]}{' (Vegan)' if self.is_vegan else ''}"


@dataclass
class SheetRow:
    service_date: str  # ISO
    closed_reason: Optional[str] = None
    notes: Optional[str] = None
    cells: List[List[str]] = field(default_factory=list)  # one token list per column

    @property
    def date_obj(self) -> date:
        return date.fromisoformat(self.service_date)


@dataclass
class Sheet:
    columns: List[ColumnSpec]
    rows: List[SheetRow]
    month: int
    year: int
    warnings: List[str] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        return {
            "columns": [asdict(c) for c in self.columns],
            "rows": [asdict(r) for r in self.rows],
            "month": self.month,
            "year": self.year,
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> "Sheet":
        return cls(
            columns=[ColumnSpec(**c) for c in data["columns"]],
            rows=[SheetRow(**r) for r in data["rows"]],
            month=int(data["month"]),
            year=int(data["year"]),
        )


class ImportError_(ValueError):
    """The file can't be turned into a menu at all (shown to the user as-is)."""


# ==================== names ====================

def normalize(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def match_key(name: str) -> str:
    """Looser key so "Tortillas" matches "Tortilla" and "Mashed Potato" matches "Mashed Potatoes"."""
    return " ".join(_singular(w) for w in normalize(name).split())


def clean_token(token: str) -> str:
    token = re.sub(r"\s+", " ", token.strip(" -–—.\t"))
    return token[:1].upper() + token[1:] if token else token


# ==================== headers & cells ====================

def parse_header(header: str) -> Optional[ColumnSpec]:
    """Map a sheet header to a meal slot, or None for columns that aren't meals."""
    h = normalize(header)
    if not h:
        return None
    if "am snack" in h or "morning snack" in h:
        slot = "am_snack"
    elif "pm snack" in h or "afternoon snack" in h:
        slot = "pm_snack"
    elif "snack" in h:
        slot = "snack"
    elif "breakfast" in h:
        slot = "breakfast"
    elif "lunch" in h:
        slot = "lunch"
    else:
        return None
    words = h.split()
    type_hint = None
    for word, type_name in HEADER_TYPE_WORDS:
        if word in words:
            type_hint = type_name
            break
    return ColumnSpec(header=header.strip(), slot=slot, is_vegan="vegan" in words, type_hint=type_hint)


def split_cell(text: str, known_keys: set) -> List[str]:
    """Split one cell into component names; keeps known "X & Y" components whole."""
    text = (text or "").strip()
    if not text:
        return []
    if match_key(text) in known_keys:
        return [clean_token(text)]
    tokens = []
    for piece in _HARD_SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if match_key(piece) in known_keys:
            tokens.append(clean_token(piece))
            continue
        parts = [p for p in _SOFT_SPLIT.split(piece) if p.strip()]
        if len(parts) > 1 and normalize(parts[-1]).split()[-1:] and normalize(parts[-1]).split()[-1] in SHARED_NOUNS:
            parts = [piece]
        tokens.extend(clean_token(p) for p in parts)
    # de-dupe within a cell, keep order
    seen, out = set(), []
    for t in tokens:
        k = match_key(t)
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y", "%a %m/%d/%Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _is_closed_word(text: str) -> bool:
    return normalize(text) in CLOSED_WORDS


# ==================== sheet ====================

def parse_csv(text: str, known_names: List[str]) -> Sheet:
    """Parse the uploaded CSV text into a Sheet. `known_names` are the tenant's existing
    FoodComponent names, used to keep multi-word components ("Mac & Cheese") whole."""
    known_keys = {match_key(n) for n in list(known_names) + WHOLE_DISHES}
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ImportError_("The file is empty.")

    header = rows[0]
    date_idx = next((i for i, h in enumerate(header) if normalize(h) in ("date", "service date", "day date")), None)
    if date_idx is None:
        raise ImportError_("No 'Date' column found. The first row must be headers, with one column named Date.")
    notes_idx = next((i for i, h in enumerate(header) if normalize(h) in ("notes", "note", "comments")), None)

    columns: List[ColumnSpec] = []
    col_indexes: List[int] = []
    ignored = []
    for i, h in enumerate(header):
        if i in (date_idx, notes_idx):
            continue
        spec = parse_header(h)
        if spec:
            columns.append(spec)
            col_indexes.append(i)
        elif h.strip() and normalize(h) not in ("day", "weekday", "day of week"):
            ignored.append(h.strip())
    if not columns:
        raise ImportError_("No meal columns found. Name columns like Breakfast, Lunch, Lunch Vegetable, PM Snack.")

    warnings = []
    if ignored:
        warnings.append(f"Ignored columns that aren't a meal: {', '.join(ignored)}.")

    parsed: List[Tuple[date, SheetRow]] = []
    seen_dates = set()
    for line_no, raw in enumerate(rows[1:], start=2):
        raw = raw + [""] * (len(header) - len(raw))
        d = parse_date(raw[date_idx])
        if not d:
            if raw[date_idx].strip():
                warnings.append(f"Row {line_no}: couldn't read date '{raw[date_idx].strip()}' — skipped.")
            continue
        if d in seen_dates:
            warnings.append(f"Row {line_no}: {d:%m/%d/%Y} appears twice — kept the first one.")
            continue
        seen_dates.add(d)

        meal_values = [raw[i].strip() for i in col_indexes]
        filled = [v for v in meal_values if v]
        closed_reason = None
        if filled and all(_is_closed_word(v) for v in filled):
            closed_reason = filled[0].strip()
        row = SheetRow(
            service_date=d.isoformat(),
            closed_reason=closed_reason,
            notes=(raw[notes_idx].strip() or None) if notes_idx is not None else None,
            cells=[[] if closed_reason else split_cell(v, known_keys) for v in meal_values],
        )
        parsed.append((d, row))

    if not parsed:
        raise ImportError_("No rows with a readable date were found.")

    (year, month), _ = Counter((d.year, d.month) for d, _ in parsed).most_common(1)[0]
    outside = [d for d, _ in parsed if (d.year, d.month) != (year, month)]
    if outside:
        warnings.append(
            f"{len(outside)} row(s) outside {date(year, month, 1):%B %Y} were skipped "
            f"(one month per upload): {', '.join(f'{d:%m/%d}' for d in outside[:5])}{'…' if len(outside) > 5 else ''}."
        )
    kept = sorted((r for d, r in parsed if (d.year, d.month) == (year, month)), key=lambda r: r.service_date)
    return Sheet(columns=columns, rows=kept, month=month, year=year, warnings=warnings)


# ==================== component matching ====================

def guess_type(name: str, column: Optional[ColumnSpec] = None) -> str:
    if column and column.type_hint:
        return column.type_hint
    n = normalize(name)
    for type_name, words in TYPE_KEYWORDS:
        if any(w in n for w in words):
            return type_name
    return SLOT_DEFAULT_TYPE.get(column.slot if column else "", GRAIN)


def guess_vegetarian(name: str) -> bool:
    n = normalize(name)
    return not any(w in n for w in ANIMAL_WORDS)


@dataclass
class TokenMatch:
    key: str                         # match_key of the name
    name: str                        # display name, as first seen in the sheet
    status: str                      # "matched" | "suggested" | "new"
    component_id: Optional[int] = None
    component_name: Optional[str] = None
    guessed_type: str = GRAIN
    uses: int = 0


def match_tokens(sheet: Sheet, components: List[Tuple[int, str]]) -> Dict[str, TokenMatch]:
    """
    Match every distinct token in the sheet against (id, name) FoodComponents.
    Returns {match_key: TokenMatch}, in first-seen order.
    """
    by_norm = {normalize(n): (cid, n) for cid, n in components}
    by_key = {}
    for cid, n in components:
        by_key.setdefault(match_key(n), (cid, n))
    all_keys = list(by_key)

    matches: Dict[str, TokenMatch] = {}
    for row in sheet.rows:
        for col, tokens in zip(sheet.columns, row.cells):
            for token in tokens:
                key = match_key(token)
                if key in matches:
                    matches[key].uses += 1
                    continue
                m = TokenMatch(key=key, name=token, status="new", guessed_type=guess_type(token, col), uses=1)
                hit = by_norm.get(normalize(token)) or by_key.get(key)
                if hit:
                    m.status, (m.component_id, m.component_name) = "matched", hit
                else:
                    close = difflib.get_close_matches(key, all_keys, n=1, cutoff=0.86)
                    if close:
                        m.status, (m.component_id, m.component_name) = "suggested", by_key[close[0]]
                matches[key] = m
    return matches


def apply_token_edits(sheet: Sheet, edits: Dict[Tuple[int, int], str]) -> None:
    """Overwrite cells with the user's edited component lists from the preview grid
    ("Carrot & Cucumber Sticks; Hummus" — split on ';' only, no guessing)."""
    for (r, c), text in edits.items():
        if r < len(sheet.rows) and c < len(sheet.columns):
            row = sheet.rows[r]
            if row.closed_reason:
                continue
            tokens, seen = [], set()
            for t in text.split(";"):
                t = clean_token(t)
                if t and match_key(t) not in seen:
                    seen.add(match_key(t))
                    tokens.append(t)
            row.cells[c] = tokens
