"""create_catering_tables

Revision ID: d34f91888ad6
Revises: 6b01f7a6ab52
Create Date: 2025-12-22 21:21:25.180594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd34f91888ad6'
down_revision: Union[str, Sequence[str], None] = '6b01f7a6ab52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
      # 1. CACFP Age Groups
      op.create_table(
          'cacfp_age_groups',
          sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
          sa.Column('name', sa.String(), nullable=False),
          sa.Column('age_min_months', sa.Integer(), nullable=False),
          sa.Column('age_max_months', sa.Integer(), nullable=True),
          sa.Column('sort_order', sa.Integer(), nullable=False),
      )

      # 2. CACFP Component Types
      op.create_table(
          'cacfp_component_types',
          sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
          sa.Column('name', sa.String(), nullable=False),
          sa.Column('description', sa.Text(), nullable=True),
          sa.Column('sort_order', sa.Integer(), nullable=False),
      )

      # 3. CACFP Portion Rules
      op.create_table(
          'cacfp_portion_rules',
          sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
          sa.Column('age_group_id', sa.Integer(), sa.ForeignKey('cacfp_age_groups.id'), nullable=False),
          sa.Column('component_type_id', sa.Integer(), sa.ForeignKey('cacfp_component_types.id'), nullable=False),
          sa.Column('meal_type', sa.String(), nullable=False),
          sa.Column('min_portion_oz', sa.Numeric(5, 2), nullable=False),
          sa.Column('max_portion_oz', sa.Numeric(5, 2), nullable=True),
          sa.Column('notes', sa.Text(), nullable=True),
      )
      op.create_unique_constraint('uq_portion_rule', 'cacfp_portion_rules', ['age_group_id', 'component_type_id', 'meal_type'])

      # 4. Food Components
      op.create_table(
          'food_components',
          sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
          sa.Column('name', sa.String(), nullable=False),
          sa.Column('component_type_id', sa.Integer(), sa.ForeignKey('cacfp_component_types.id'), nullable=False),
          sa.Column('default_portion_oz', sa.Numeric(5, 2), nullable=False),
          sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
          sa.Column('is_vegetarian', sa.Boolean(), nullable=False, server_default=sa.true()),
          sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
          sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
      )
      op.create_unique_constraint('uq_food_component_tenant_name', 'food_components', ['tenant_id', 'name'])
      op.create_index('idx_food_components_tenant', 'food_components', ['tenant_id'])
      op.create_index('idx_food_components_type', 'food_components', ['component_type_id'])

      # 5. Catering Meal Items
      op.create_table(
          'catering_meal_items',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('name', sa.String(), nullable=False),
          sa.Column('description', sa.Text(), nullable=True),
          sa.Column('meal_type', sa.String(), nullable=False),
          sa.Column('is_vegan', sa.Boolean(), nullable=False, server_default=sa.false()),
          sa.Column('is_vegetarian', sa.Boolean(), nullable=False, server_default=sa.false()),
          sa.Column('photo_filename', sa.String(), nullable=True),
          sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
          sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
          sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
      )
      op.create_unique_constraint('uq_meal_item_tenant_name', 'catering_meal_items', ['tenant_id', 'name'])
      op.create_index('idx_catering_meal_items_tenant', 'catering_meal_items', ['tenant_id'])
      op.create_index('idx_catering_meal_items_type', 'catering_meal_items', ['meal_type'])

      # 6. Catering Meal Components
      op.create_table(
          'catering_meal_components',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('meal_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id', ondelete='CASCADE'), nullable=False),
          sa.Column('food_component_id', sa.Integer(), sa.ForeignKey('food_components.id'), nullable=False),
          sa.Column('portion_oz', sa.Numeric(5, 2), nullable=False),
      )
      op.create_unique_constraint('uq_meal_component', 'catering_meal_components', ['meal_item_id', 'food_component_id'])
      op.create_index('idx_meal_components_meal', 'catering_meal_components', ['meal_item_id'])

      # 7. Catering Programs
      op.create_table(
          'catering_programs',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('name', sa.String(), nullable=False),
          sa.Column('client_name', sa.String(), nullable=False),
          sa.Column('client_email', sa.String(), nullable=True),
          sa.Column('client_phone', sa.String(), nullable=True),
          sa.Column('address', sa.Text(), nullable=True),
          sa.Column('age_group_id', sa.Integer(), sa.ForeignKey('cacfp_age_groups.id'), nullable=False),
          sa.Column('total_children', sa.Integer(), nullable=False),
          sa.Column('vegan_count', sa.Integer(), nullable=False, server_default='0'),
          sa.Column('invoice_prefix', sa.String(), nullable=False),
          sa.Column('last_invoice_number', sa.Integer(), nullable=False, server_default='0'),
          sa.Column('service_days', sa.String(), nullable=False),
          sa.Column('meal_types_required', sa.String(), nullable=False),
          sa.Column('start_date', sa.Date(), nullable=False),
          sa.Column('end_date', sa.Date(), nullable=True),
          sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
          sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
          sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
          sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
      )
      op.create_index('idx_catering_programs_tenant', 'catering_programs', ['tenant_id'])
      op.create_index('idx_catering_programs_active', 'catering_programs', ['tenant_id', 'is_active'])

      # 8. Catering Program Holidays
      op.create_table(
          'catering_program_holidays',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id', ondelete='CASCADE'), nullable=False),
          sa.Column('holiday_date', sa.Date(), nullable=False),
          sa.Column('description', sa.String(), nullable=True),
      )
      op.create_unique_constraint('uq_program_holiday', 'catering_program_holidays', ['program_id', 'holiday_date'])
      op.create_index('idx_program_holidays_program', 'catering_program_holidays', ['program_id'])

      # 9. Catering Monthly Menus
      op.create_table(
          'catering_monthly_menus',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id'), nullable=False),
          sa.Column('month', sa.Integer(), nullable=False),
          sa.Column('year', sa.Integer(), nullable=False),
          sa.Column('status', sa.String(), nullable=False, server_default='draft'),
          sa.Column('finalized_at', sa.DateTime(), nullable=True),
          sa.Column('sent_at', sa.DateTime(), nullable=True),
          sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
          sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
          sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
      )
      op.create_unique_constraint('uq_monthly_menu', 'catering_monthly_menus', ['program_id', 'month', 'year'])
      op.create_index('idx_monthly_menus_tenant', 'catering_monthly_menus', ['tenant_id'])
      op.create_index('idx_monthly_menus_program', 'catering_monthly_menus', ['program_id', 'year', 'month'])

      # 10. Catering Menu Days
      op.create_table(
          'catering_menu_days',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('monthly_menu_id', sa.String(), sa.ForeignKey('catering_monthly_menus.id', ondelete='CASCADE'), nullable=False),
          sa.Column('service_date', sa.Date(), nullable=False),
          sa.Column('breakfast_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('breakfast_vegan_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('lunch_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('lunch_vegan_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('snack_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('snack_vegan_item_id', sa.String(), sa.ForeignKey('catering_meal_items.id'), nullable=True),
          sa.Column('notes', sa.Text(), nullable=True),
      )
      op.create_unique_constraint('uq_menu_day', 'catering_menu_days', ['monthly_menu_id', 'service_date'])
      op.create_index('idx_menu_days_monthly', 'catering_menu_days', ['monthly_menu_id'])
      op.create_index('idx_menu_days_date', 'catering_menu_days', ['service_date'])

      # 11. Catering Invoices
      op.create_table(
          'catering_invoices',
          sa.Column('id', sa.String(), primary_key=True),
          sa.Column('invoice_number', sa.String(), nullable=False),
          sa.Column('program_id', sa.String(), sa.ForeignKey('catering_programs.id'), nullable=False),
          sa.Column('monthly_menu_id', sa.String(), sa.ForeignKey('catering_monthly_menus.id'), nullable=True),
          sa.Column('menu_day_id', sa.String(), sa.ForeignKey('catering_menu_days.id'), nullable=True),
          sa.Column('service_date', sa.Date(), nullable=False),
          sa.Column('regular_meal_count', sa.Integer(), nullable=False),
          sa.Column('vegan_meal_count', sa.Integer(), nullable=False, server_default='0'),
          sa.Column('status', sa.String(), nullable=False, server_default='draft'),
          sa.Column('pdf_filename', sa.String(), nullable=True),
          sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
          sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
          sa.Column('sent_at', sa.DateTime(), nullable=True),
      )
      op.create_unique_constraint('uq_invoice_number', 'catering_invoices', ['tenant_id', 'invoice_number'])
      op.create_index('idx_invoices_tenant', 'catering_invoices', ['tenant_id'])
      op.create_index('idx_invoices_program', 'catering_invoices', ['program_id'])
      op.create_index('idx_invoices_service_date', 'catering_invoices', ['service_date'])


def downgrade():
      # Drop in reverse order
      op.drop_table('catering_invoices')
      op.drop_table('catering_menu_days')
      op.drop_table('catering_monthly_menus')
      op.drop_table('catering_program_holidays')
      op.drop_table('catering_programs')
      op.drop_table('catering_meal_components')
      op.drop_table('catering_meal_items')
      op.drop_table('food_components')
      op.drop_table('cacfp_portion_rules')
      op.drop_table('cacfp_component_types')
      op.drop_table('cacfp_age_groups')