import os

# 📁 Centralized Upload Paths for All Modules
BASE_STATIC_PATH = os.path.join("app", "static")

UPLOAD_PATHS = {
    "documents": os.path.join(BASE_STATIC_PATH, "documents"),
    "driver_orders": os.path.join(BASE_STATIC_PATH, "driver_orders"),
    "vending_logs": os.path.join(BASE_STATIC_PATH, "vending_logs"),
    "vending_qr_photos": os.path.join(BASE_STATIC_PATH, "vending_logs", "vending_qr_photos"),
    "shortage_logs": os.path.join(BASE_STATIC_PATH, "shortages"),
    "task_attachments": os.path.join(BASE_STATIC_PATH, "task_attachments"),
}

# Ensure all folders exist
for path in UPLOAD_PATHS.values():
    os.makedirs(path, exist_ok=True)
