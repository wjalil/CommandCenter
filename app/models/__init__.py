from .base import Base
from .shift import Shift
from .task import Task, TaskSubmission,TaskTemplate, TaskItem
from .document import Document
from .user import User
from .shortage_log import ShortageLog
from .custom_modules.driver_order import DriverOrder
from .menu.menu_item import MenuItem
from .menu.menu import Menu
from .menu.menu_category import MenuCategory
from .customer.customer import Customer
from .customer.customer_order import CustomerOrder
from .internal_task import InternalTask
from .custom_modules.machine import Machine
from .shopping import *
from app.models.tenant_module import TenantModule
from .timeclock import TimeEntry  # ← CRITICAL: Was missing - caused time_entries table to be dropped
from .taskboard import DailyTask  # ← CRITICAL: Was missing - caused daily_tasks table to be dropped
from .catering import (
    CACFPAgeGroup,
    CACFPComponentType,
    CACFPPortionRule,
    FoodComponent,
    CateringMealItem,
    CateringMealComponent,
    CateringProgram,
    CateringProgramHoliday,
    CateringMonthlyMenu,
    CateringMenuDay,
    CateringInvoice,
)