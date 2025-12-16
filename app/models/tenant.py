# app/models/tenant.py
from sqlalchemy import Column, Integer, String
from app.models.base import Base
from sqlalchemy.orm import relationship, foreign

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    slug = Column(String, unique=True, nullable=True)          # NEW (nullable for migration backfill)
    dispatch_phone = Column(String, nullable=True)  

 # Back-populated relationships
    users = relationship("User", back_populates="tenant")
    customers = relationship("Customer", back_populates="tenant")
    shifts = relationship("Shift", back_populates="tenant")
    documents = relationship("Document", back_populates="tenant")
    internal_tasks = relationship("InternalTask", back_populates="tenant")
    menus = relationship("Menu", back_populates="tenant", cascade="all, delete-orphan")
    customer_orders = relationship("CustomerOrder", back_populates="tenant")
    shortage_logs = relationship("ShortageLog", back_populates="tenant")
    submissions = relationship("TaskSubmission", back_populates="tenant")
    tasks = relationship("Task", back_populates="tenant")
    task_templates = relationship("TaskTemplate", back_populates="tenant")

    # Custom modules
    driver_orders = relationship("DriverOrder", back_populates="tenant")
    machines = relationship("Machine", back_populates="tenant")
    vending_logs = relationship("VendingLog", back_populates="tenant")
