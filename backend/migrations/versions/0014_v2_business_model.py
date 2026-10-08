"""LeadFinder V2 business model: drop the V1 business tables, create the V2 intelligence schema.

Business data starts from zero (no data migration). Kept untouched: users, user_sessions, audit_logs.
Back up first: ./scripts/backup_db.sh. This migration cannot be downgraded (the V1 data is gone);
to go back, restore the backup taken before upgrading.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every V1 business table (as of 0013). One DROP statement without CASCADE: references among these
# tables (including the research <-> decision-maker cycle) are dropped together, while a reference from
# a table we keep would make the statement fail instead of silently losing a constraint.
V1_BUSINESS_TABLES = (
    "lead_activities", "campaign_companies", "campaigns", "contacts", "odoo_matches", "odoo_contacts", "crm_leads",
    "salespeople", "import_runs", "lusha_usage", "discovery_results", "company_sources", "discovery_runs",
    "decision_maker_sources", "enrichment_requests", "decision_makers", "decision_maker_runs",
    "company_qualifications", "company_research_runs", "sales_leads", "companies",
)


def upgrade() -> None:
    op.execute(f"DROP TABLE {', '.join(V1_BUSINESS_TABLES)}")

    op.create_table('people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=300), nullable=False),
    sa.Column('first_name', sa.String(length=150), nullable=True),
    sa.Column('last_name', sa.String(length=150), nullable=True),
    sa.Column('normalized_name', sa.String(length=300), nullable=False),
    sa.Column('location_country', sa.String(length=100), nullable=True),
    sa.Column('location_city', sa.String(length=120), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_people'))
    )
    op.create_index(op.f('ix_people_normalized_name'), 'people', ['normalized_name'], unique=False)
    op.create_table('sources',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=True),
    sa.Column('url', sa.String(length=2000), nullable=True),
    sa.Column('external_reference', sa.String(length=300), nullable=True),
    sa.Column('publisher', sa.String(length=300), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_quality', sa.SmallInteger(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('source_quality IS NULL OR source_quality BETWEEN 0 AND 100', name=op.f('ck_sources_source_quality_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources'))
    )
    op.create_index(op.f('ix_sources_content_hash'), 'sources', ['content_hash'], unique=False)
    op.create_index(op.f('ix_sources_source_type'), 'sources', ['source_type'], unique=False)
    op.create_index(op.f('ix_sources_url'), 'sources', ['url'], unique=False)
    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('legal_name', sa.String(length=300), nullable=True),
    sa.Column('normalized_name', sa.String(length=300), nullable=False),
    sa.Column('domain', sa.String(length=253), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('industry', sa.String(length=120), nullable=True),
    sa.Column('sub_industry', sa.String(length=120), nullable=True),
    sa.Column('company_type', sa.String(length=60), nullable=True),
    sa.Column('employee_count_estimate', sa.Integer(), nullable=True),
    sa.Column('founded_year', sa.SmallInteger(), nullable=True),
    sa.Column('headquarters_country', sa.String(length=100), nullable=True),
    sa.Column('headquarters_region', sa.String(length=120), nullable=True),
    sa.Column('headquarters_city', sa.String(length=120), nullable=True),
    sa.Column('primary_phone', sa.String(length=50), nullable=True),
    sa.Column('primary_email', sa.String(length=320), nullable=True),
    sa.Column('linkedin_url', sa.String(length=500), nullable=True),
    sa.Column('instagram_url', sa.String(length=500), nullable=True),
    sa.Column('facebook_url', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=32), server_default='new', nullable=False),
    sa.Column('status_reason', sa.String(length=500), nullable=True),
    sa.Column('last_researched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('new', 'qualified', 'contacted', 'follow_up', 'meeting_scheduled', 'opportunity', 'working_odoo', 'working_frinzo', 'working_it', 'not_interested', 'do_not_contact', 'archived')", name=op.f('ck_companies_status_valid')),
    sa.CheckConstraint('employee_count_estimate IS NULL OR employee_count_estimate > 0', name=op.f('ck_companies_employees_positive')),
    sa.CheckConstraint('founded_year IS NULL OR founded_year BETWEEN 1700 AND 2100', name=op.f('ck_companies_founded_year_range')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_companies_created_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_companies')),
    sa.UniqueConstraint('domain', name=op.f('uq_companies_domain'))
    )
    op.create_index(op.f('ix_companies_headquarters_city'), 'companies', ['headquarters_city'], unique=False)
    op.create_index(op.f('ix_companies_headquarters_country'), 'companies', ['headquarters_country'], unique=False)
    op.create_index(op.f('ix_companies_industry'), 'companies', ['industry'], unique=False)
    op.create_index(op.f('ix_companies_normalized_name'), 'companies', ['normalized_name'], unique=False)
    op.create_index(op.f('ix_companies_status'), 'companies', ['status'], unique=False)
    op.create_table('integrations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('integration_type', sa.String(length=60), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='not_configured', nullable=False),
    sa.Column('configuration', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by_user_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('not_configured', 'configured', 'active', 'error', 'disabled')", name=op.f('ck_integrations_status_valid')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_integrations_created_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integrations'))
    )
    op.create_index(op.f('ix_integrations_integration_type'), 'integrations', ['integration_type'], unique=False)
    op.create_table('lead_searches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('region', sa.String(length=120), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('industry', sa.String(length=200), nullable=True),
    sa.Column('solution', sa.String(length=16), server_default='any', nullable=False),
    sa.Column('requested_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('companies_found', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("solution IN ('any', 'odoo', 'frinzo', 'it')", name=op.f('ck_lead_searches_solution_valid')),
    sa.CheckConstraint("status IN ('pending', 'researching', 'completed', 'partial', 'failed')", name=op.f('ck_lead_searches_status_valid')),
    sa.CheckConstraint('companies_found >= 0', name=op.f('ck_lead_searches_companies_found_positive')),
    sa.CheckConstraint('requested_count BETWEEN 1 AND 500', name=op.f('ck_lead_searches_requested_count_range')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_lead_searches_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lead_searches'))
    )
    op.create_index(op.f('ix_lead_searches_user_id'), 'lead_searches', ['user_id'], unique=False)
    op.create_table('company_locations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('location_type', sa.String(length=32), nullable=True),
    sa.Column('country', sa.String(length=100), nullable=False),
    sa.Column('region', sa.String(length=120), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('is_headquarters', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_company_locations_confidence_range')),
    sa.CheckConstraint('latitude IS NULL OR latitude BETWEEN -90 AND 90', name=op.f('ck_company_locations_latitude_range')),
    sa.CheckConstraint('longitude IS NULL OR longitude BETWEEN -180 AND 180', name=op.f('ck_company_locations_longitude_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_locations_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_company_locations_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_locations'))
    )
    op.create_index(op.f('ix_company_locations_city'), 'company_locations', ['city'], unique=False)
    op.create_index(op.f('ix_company_locations_company_id'), 'company_locations', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_locations_source_id'), 'company_locations', ['source_id'], unique=False)
    op.create_index('uq_company_locations_headquarters', 'company_locations', ['company_id'], unique=True, postgresql_where=sa.text('is_headquarters'))
    op.create_table('company_people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('job_title', sa.String(length=300), nullable=False),
    sa.Column('normalized_title', sa.String(length=300), nullable=True),
    sa.Column('department', sa.String(length=40), nullable=True),
    sa.Column('seniority', sa.String(length=40), nullable=True),
    sa.Column('is_current', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('started_at', sa.Date(), nullable=True),
    sa.Column('ended_at', sa.Date(), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('primary_source_id', sa.BigInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_company_people_confidence_range')),
    sa.CheckConstraint('ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at', name=op.f('ck_company_people_dates_ordered')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_people_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_company_people_person_id_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['primary_source_id'], ['sources.id'], name=op.f('fk_company_people_primary_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_people'))
    )
    op.create_index(op.f('ix_company_people_company_id'), 'company_people', ['company_id'], unique=False)
    op.create_index(op.f('ix_company_people_department'), 'company_people', ['department'], unique=False)
    op.create_index(op.f('ix_company_people_person_id'), 'company_people', ['person_id'], unique=False)
    op.create_index(op.f('ix_company_people_primary_source_id'), 'company_people', ['primary_source_id'], unique=False)
    op.create_index('uq_company_people_current_role', 'company_people', ['company_id', 'person_id', 'job_title'], unique=True, postgresql_where=sa.text('is_current'))
    op.create_table('company_status_history',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('old_status', sa.String(length=32), nullable=True),
    sa.Column('new_status', sa.String(length=32), nullable=False),
    sa.Column('changed_by_user_id', sa.Integer(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['changed_by_user_id'], ['users.id'], name=op.f('fk_company_status_history_changed_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_company_status_history_company_id_companies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_status_history'))
    )
    op.create_index(op.f('ix_company_status_history_company_id'), 'company_status_history', ['company_id'], unique=False)
    op.create_table('emails',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('email_type', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='unknown', nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_public', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'predicted' OR last_verified_at IS NULL", name=op.f('ck_emails_predicted_not_verified')),
    sa.CheckConstraint("status <> 'verified' OR last_verified_at IS NOT NULL", name=op.f('ck_emails_verified_has_date')),
    sa.CheckConstraint("status IN ('unknown', 'discovered', 'predicted', 'verified', 'invalid', 'catch_all', 'stale')", name=op.f('ck_emails_status_valid')),
    sa.CheckConstraint('company_id IS NOT NULL OR person_id IS NOT NULL', name=op.f('ck_emails_owner_present')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_emails_confidence_range')),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_emails_email_lowercase')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_emails_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_emails_person_id_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_emails_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_emails'))
    )
    op.create_index(op.f('ix_emails_company_id'), 'emails', ['company_id'], unique=False)
    op.create_index(op.f('ix_emails_email'), 'emails', ['email'], unique=False)
    op.create_index(op.f('ix_emails_person_id'), 'emails', ['person_id'], unique=False)
    op.create_index(op.f('ix_emails_source_id'), 'emails', ['source_id'], unique=False)
    op.create_index('uq_emails_company_email', 'emails', ['company_id', 'email'], unique=True, postgresql_where=sa.text('person_id IS NULL'))
    op.create_index('uq_emails_person_email', 'emails', ['person_id', 'email'], unique=True, postgresql_where=sa.text('person_id IS NOT NULL'))
    op.create_table('lead_search_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('search_id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('relevance_score', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_lead_search_results_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['search_id'], ['lead_searches.id'], name=op.f('fk_lead_search_results_search_id_lead_searches'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lead_search_results')),
    sa.UniqueConstraint('search_id', 'company_id', name='uq_lead_search_results_company')
    )
    op.create_index(op.f('ix_lead_search_results_company_id'), 'lead_search_results', ['company_id'], unique=False)
    op.create_table('opportunity_analysis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('solution', sa.String(length=16), nullable=False),
    sa.Column('fit_level', sa.String(length=16), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('reasoning', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recommended_modules_or_services', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recommended_person_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("fit_level IS NULL OR fit_level IN ('unknown', 'low', 'medium', 'high')", name=op.f('ck_opportunity_analysis_fit_level_valid')),
    sa.CheckConstraint("solution IN ('odoo', 'frinzo', 'it')", name=op.f('ck_opportunity_analysis_solution_valid')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_opportunity_analysis_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_opportunity_analysis_company_id_companies'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opportunity_analysis'))
    )
    op.create_index('ix_opportunity_analysis_latest', 'opportunity_analysis', ['company_id', 'solution', 'generated_at'], unique=False)
    op.create_table('phones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=False),
    sa.Column('normalized_phone', sa.String(length=20), nullable=True),
    sa.Column('phone_type', sa.String(length=20), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_public', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='unknown', nullable=False),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('source_id', sa.BigInteger(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'verified' OR last_verified_at IS NOT NULL", name=op.f('ck_phones_verified_has_date')),
    sa.CheckConstraint("status IN ('unknown', 'discovered', 'verified', 'invalid', 'stale')", name=op.f('ck_phones_status_valid')),
    sa.CheckConstraint('company_id IS NOT NULL OR person_id IS NOT NULL', name=op.f('ck_phones_owner_present')),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_phones_confidence_range')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_phones_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_phones_person_id_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_phones_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phones'))
    )
    op.create_index(op.f('ix_phones_company_id'), 'phones', ['company_id'], unique=False)
    op.create_index(op.f('ix_phones_normalized_phone'), 'phones', ['normalized_phone'], unique=False)
    op.create_index(op.f('ix_phones_person_id'), 'phones', ['person_id'], unique=False)
    op.create_index(op.f('ix_phones_source_id'), 'phones', ['source_id'], unique=False)
    op.create_index('uq_phones_company_phone', 'phones', ['company_id', 'normalized_phone'], unique=True, postgresql_where=sa.text('person_id IS NULL AND normalized_phone IS NOT NULL'))
    op.create_index('uq_phones_person_phone', 'phones', ['person_id', 'normalized_phone'], unique=True, postgresql_where=sa.text('person_id IS NOT NULL AND normalized_phone IS NOT NULL'))
    op.create_table('research_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('search_id', sa.Integer(), nullable=True),
    sa.Column('research_type', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('requested_by_user_id', sa.Integer(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')", name=op.f('ck_research_runs_status_valid')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_research_runs_company_id_companies'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], name=op.f('fk_research_runs_requested_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['search_id'], ['lead_searches.id'], name=op.f('fk_research_runs_search_id_lead_searches'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_research_runs'))
    )
    op.create_index(op.f('ix_research_runs_company_id'), 'research_runs', ['company_id'], unique=False)
    op.create_index(op.f('ix_research_runs_requested_by_user_id'), 'research_runs', ['requested_by_user_id'], unique=False)
    op.create_index(op.f('ix_research_runs_search_id'), 'research_runs', ['search_id'], unique=False)
    op.create_table('evidence',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source_id', sa.BigInteger(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('company_person_id', sa.Integer(), nullable=True),
    sa.Column('evidence_type', sa.String(length=40), nullable=False),
    sa.Column('field_name', sa.String(length=100), nullable=True),
    sa.Column('extracted_value', sa.Text(), nullable=True),
    sa.Column('excerpt', sa.Text(), nullable=True),
    sa.Column('structured_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('confidence', sa.SmallInteger(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence IS NULL OR confidence BETWEEN 0 AND 100', name=op.f('ck_evidence_confidence_range')),
    sa.CheckConstraint('num_nonnulls(company_id, person_id, company_person_id) >= 1', name=op.f('ck_evidence_subject_present')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_evidence_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_person_id'], ['company_people.id'], name=op.f('fk_evidence_company_person_id_company_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_evidence_person_id_people'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_evidence_source_id_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence'))
    )
    op.create_index(op.f('ix_evidence_company_id'), 'evidence', ['company_id'], unique=False)
    op.create_index(op.f('ix_evidence_company_person_id'), 'evidence', ['company_person_id'], unique=False)
    op.create_index(op.f('ix_evidence_person_id'), 'evidence', ['person_id'], unique=False)
    op.create_index(op.f('ix_evidence_source_id'), 'evidence', ['source_id'], unique=False)


def downgrade() -> None:
    raise RuntimeError("0014 is irreversible: the V1 business data was dropped. Restore the database backup "
                       "taken before upgrading (./scripts/restore_db.sh) instead of downgrading.")
