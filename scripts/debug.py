# utils/inspect_models.py (or in a debug route / test script)

from app.models.base import Base

def print_model_columns():
    for class_ in Base.registry._class_registry.values():
        if hasattr(class_, '__table__'):
            print(f"🧩 {class_.__tablename__}:")
            print("  📌 Columns:")
            for col in class_.__table__.columns:
                print(f"    - {col.name}")
            print()

print_model_columns()