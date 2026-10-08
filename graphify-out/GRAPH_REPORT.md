# Graph Report - TecomsaLeadFinder  (2026-10-01)

## Corpus Check
- 207 files · ~115,103 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 7, .ini 2, .example 1)

## Summary
- 2163 nodes · 7371 edges · 102 communities (83 shown, 19 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 488 edges (avg confidence: 0.94)
- Token cost: 79,083 input · 8,000 output

## Community Hubs (Navigation)
- Campaign & User Forms
- Admin Console UI
- Companies List UI
- Activity & Settings UI
- Config & Lusha Client
- ORM Base & Models
- Discovery Upload UI
- Auth Roles & Test Fixtures
- Import Mapping & Errors
- API Router & DB Deps
- Activity Timeline & Enums
- Auth & Password Hashing
- Discovery Tests
- Audit Log & Admin Scripts
- Discovery Run Service
- Discovery & Odoo Schemas
- Alembic Migrations
- Candidate Quality Assessment
- Company Normalization & Merge
- Relationship Decisions
- Research Tests
- Common Schema Validators
- Frontend Dependencies
- Company Intelligence Panel
- App Shell & Login
- Odoo Records Listing
- Industry Taxonomy
- Campaign Routes
- Test DB Fixtures
- Discovery Evidence & Cities
- Research HTTP Fetch
- Company Profile Page
- Research Run State
- Permissions & Activity Queries
- Import Field Conversion
- Company Routes
- OSM Discovery Provider
- Discovery Run Page
- Phase 0/1 Hardening Tests
- Import Routes
- AI Review Providers
- TypeScript Config
- Website Classification
- Overture Provider
- Branch Consolidation
- Research Routes
- Odoo Contact Matching
- Website Evidence Extraction
- Discovery Quality Tests
- Toast Notifications
- Research Executor & Settings
- Discovery Confidence & CRM Leads
- Discovery Provider Base
- Geography & Cities
- Website Crawler
- Discovery Architecture Docs
- Sample Odoo Data & Ownership
- Architecture & API Docs
- Campaign Service
- HTTP Fetcher Client
- Claude Provider
- Qualification Rubric
- Rate Limiter
- Discovery Sources Docs
- Production Ops & Backups
- AI Research Docs
- Contact Routes
- System & Dashboard Routes
- Backend Requirements
- Research Test Fakes
- Research Qualification Access
- Root Layout & Fonts
- Company Update Schema
- Dashboard Schemas
- Dev Docker Compose
- Odoo Import Docs
- Campaign Tests
- Activity Routes
- Discovery Provider Protocol
- Salesperson Resolver
- Research Payload
- Overture Extract Test
- App Icon & Brand
- Next Middleware
- Next Config
- Integrations Package
- Food Manufacturing Test
- Overture Taxonomy Test
- Next.js Env Types
- MCP Config
- Backup Script
- Backup Loop Script
- Restore Script

## God Nodes (most connected - your core abstractions)
1. `UserRole` - 140 edges
2. `Section()` - 58 edges
3. `FakeProvider` - 56 edges
4. `get_settings()` - 53 edges
5. `providers()` - 52 edges
6. `api()` - 52 edges
7. `useApi()` - 48 edges
8. `start()` - 46 edges
9. `Button()` - 44 edges
10. `Alert()` - 43 edges

## Surprising Connections (you probably didn't know these)
- `Odoo Import Center` --semantically_similar_to--> `Import Workflow (upload, detect, preview, confirm, delete)`  [INFERRED] [semantically similar]
  README.md → docs/ARCHITECTURE.md
- `Find Companies (Automatic Discovery, Phase 1)` --semantically_similar_to--> `Company Discovery Pipeline`  [INFERRED] [semantically similar]
  README.md → docs/ARCHITECTURE.md
- `Production Docker Compose stack` --semantically_similar_to--> `Development Docker Compose stack`  [INFERRED] [semantically similar]
  docker-compose.prod.yml → docker-compose.yml
- `TECOMSA Relationship Status` --semantically_similar_to--> `Relationship Status Precedence`  [INFERRED] [semantically similar]
  README.md → docs/ARCHITECTURE.md
- `discovery volume (cached source extracts)` --shares_data_with--> `Find Companies (Automatic Discovery, Phase 1)`  [INFERRED]
  docker-compose.prod.yml → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Discovery candidate dedup and Odoo protection flow** — docs_architecture_discovery_providers, docs_architecture_quality_consolidate, docs_architecture_company_index, docs_architecture_odoo_index, docs_architecture_discovery_results_table [EXTRACTED 1.00]
- **Research and qualification pipeline** — docs_architecture_ssrf_fetch, docs_architecture_rubric, docs_architecture_ai_review_provider, backend_requirements_crawl4ai, readme_ai_provider [EXTRACTED 1.00]
- **Odoo import to relationship protection** — docs_architecture_import_workflow, docs_architecture_crm_leads_table, docs_architecture_odoo_contacts_table, docs_architecture_relationship_status_precedence, docs_architecture_odoo_matches_table [INFERRED 0.85]

## Communities (102 total, 19 thin omitted)

### Community 0 - "Campaign & User Forms"
Cohesion: 0.05
Nodes (75): toggleActive(), NewUserPage(), AddCompanyPanel(), add(), changeStatus(), onSubmit(), add(), run() (+67 more)

### Community 1 - "Admin Console UI"
Cohesion: 0.09
Nodes (62): ActionTag(), AdminPage(), AdminView(), AREA_TONE, AuditDetails(), AuditTab(), STATE, TabKey (+54 more)

### Community 2 - "Companies List UI"
Cohesion: 0.04
Nodes (64): CompaniesPage(), exportCompanies(), FilterKey, filterTokens(), KEYS, Values, campaignTone, confidence (+56 more)

### Community 3 - "Activity & Settings UI"
Cohesion: 0.09
Nodes (53): ActivityPage(), IntegrationsTab(), SettingsTab(), useStatus(), EditUser(), EditUserPage(), EditCampaignPage(), NewCampaignPage() (+45 more)

### Community 4 - "Config & Lusha Client"
Cohesion: 0.07
Nodes (36): model_validator, Settings, IntegrationNotConfigured, Exception, Raised when code tries to use a provider that is not connected. In Phase 0 this…, LushaClient, LushaClientConfig, Low-level Lusha HTTP transport. NOT implemented in Phase 0. LUSHA_API_KEY is… (+28 more)

### Community 5 - "ORM Base & Models"
Cohesion: 0.13
Nodes (39): Base, CreatedAtMixin, TimestampMixin, AuditLog, Security/compliance trail. Never store passwords, tokens or secrets in…, Campaign, Company, One master record per real-world organisation. Name is deliberately NOT unique.… (+31 more)

### Community 6 - "Discovery Upload UI"
Cohesion: 0.07
Nodes (47): UploadPanel(), CountPicker(), FindCompanies(), FindCompaniesPage(), History(), Industry, IndustryPicker(), ResultMix() (+39 more)

### Community 7 - "Auth Roles & Test Fixtures"
Cohesion: 0.10
Nodes (53): require_roles(), UserRole, csv_bytes(), xlsx_bytes(), test_agent_cannot_edit_company_created_by_someone_else(), test_company_creation_normalizes_and_records_events(), test_company_name_is_not_unique(), test_company_note_creates_activity() (+45 more)

### Community 8 - "Import Mapping & Errors"
Cohesion: 0.10
Nodes (52): BusinessRuleError, ImportStatus, ImportType, auto_map(), missing_essentials(), Map target fields to source columns by alias (first alias match wins, one…, A readable description of what is missing, or None when the file can be…, _build() (+44 more)

### Community 9 - "API Router & DB Deps"
Cohesion: 0.08
Nodes (35): get_db(), Session, list_audit_logs(), AdminUser, DbSession, get, max_length, Pagination (+27 more)

### Community 10 - "Activity Timeline & Enums"
Cohesion: 0.09
Nodes (47): LeadActivity, Business event timeline (sales-facing). Structured for later ML use., ActivityType, CompanySource, ContactSource, CrmLeadType, DiscoveryStatus, LeadPriority (+39 more)

### Community 11 - "Auth & Password Hashing"
Cohesion: 0.07
Nodes (46): argon2, argon2_exceptions, can_import(), client_ip(), get_current_user(), CurrentUser, DbSession, Request (+38 more)

### Community 12 - "Discovery Tests"
Cohesion: 0.13
Nodes (47): all_rows(), Find Companies shows one row per company: a chain's other locations are stored…, _restaurant(), rows_named(), test_1_2_each_chain_is_one_company_row_with_all_locations(), test_3_4_branches_with_own_phones_and_domain_variants_consolidate(), test_5_child_records_are_stored_but_not_returned_by_default(), test_6_opening_the_company_shows_all_locations() (+39 more)

### Community 13 - "Audit Log & Admin Scripts"
Cohesion: 0.10
Nodes (39): argparse, AuditLog, AdminUser, patch, update_salesperson(), AppError, ConflictError, NotFoundError (+31 more)

### Community 14 - "Discovery Run Service"
Cohesion: 0.08
Nodes (42): delete_run(), get_options(), get_run(), list_results(), list_runs(), AdminUser, CurrentUser, DbSession (+34 more)

### Community 15 - "Discovery & Odoo Schemas"
Cohesion: 0.12
Nodes (36): OdooMatchStatus, A company's relationship with TECOMSA according to Odoo data. NOT_CHECKED means…, ActivityOut, AuditLogOut, ContactRef, CampaignCompanyCompany, EntityRef, OutModel (+28 more)

### Community 16 - "Alembic Migrations"
Cohesion: 0.07
Nodes (16): alembic, _in(), _timestamps(), upgrade(), downgrade(), _in(), Odoo import foundation Adds salespeople, import_runs, odoo_contacts and…, _remap_match_status() (+8 more)

### Community 17 - "Candidate Quality Assessment"
Cohesion: 0.10
Nodes (31): Candidate, assess(), Assessment, _cut_to(), _distinctive(), _domain_label(), Group, _keys() (+23 more)

### Community 18 - "Company Normalization & Merge"
Cohesion: 0.12
Nodes (28): Unsaved company carrying one record's matching keys (for Odoo evidence)., Add what the source knows without overwriting anything already on the company., _transient(), Enrich from Odoo without overwriting anything a user already entered., Deterministic company matching (duplicate protection foundation). Signals,…, company_domain(), email_domain(), normalize_company_name() (+20 more)

### Community 19 - "Relationship Decisions"
Cohesion: 0.10
Nodes (29): core_name(), national food company' and 'national foods' -> 'national food' (similar, not…, _apply(), apply_decision(), decide(), Decision, Evidence, evidence_for() (+21 more)

### Community 20 - "Research Tests"
Cohesion: 0.17
Nodes (33): Phase 2: website research and TECOMSA qualification., acme_run(), company(), _crawl(), detail(), _fact(), facts_of(), page() (+25 more)

### Community 21 - "Common Schema Validators"
Cohesion: 0.10
Nodes (25): InModel, Any, model_validator, Base for request bodies: rejects unknown fields, trims strings, maps "" to null., require_value(), validate_http_url(), validate_phone(), ContactCreate (+17 more)

### Community 22 - "Frontend Dependencies"
Cohesion: 0.06
Nodes (31): dependencies, clsx, lucide-react, next, react, react-dom, devDependencies, autoprefixer (+23 more)

### Community 23 - "Company Intelligence Panel"
Cohesion: 0.11
Nodes (30): ACTIVE, CompanyIntelligence(), FitCard(), Reasons(), scoreBar(), ScoreRing(), scoreTone(), Signal (+22 more)

### Community 24 - "App Shell & Login"
Cohesion: 0.11
Nodes (25): AuthenticatedLayout(), LoginPage(), NotFound(), AppShell(), logout(), navGroups(), NavItem, NavLink() (+17 more)

### Community 25 - "Odoo Records Listing"
Cohesion: 0.10
Nodes (27): page_params(), ge, le, list_crm_leads(), list_odoo_contacts(), list_salespeople(), list_stages(), DbSession (+19 more)

### Community 26 - "Industry Taxonomy"
Cohesion: 0.09
Nodes (17): _category_industries(), CustomProfile, IndustryProfile, _label(), Match, profile_for(), LeadFinder industries -> source categories and keywords. Sources do not label…, Product keyword, and a production keyword that is a different word ("roastery"… (+9 more)

### Community 27 - "Campaign Routes"
Cohesion: 0.15
Nodes (25): add_company_to_campaign(), create_campaign(), get_campaign(), list_campaigns(), CurrentUser, DbSession, get, max_length (+17 more)

### Community 28 - "Test DB Fixtures"
Cohesion: 0.11
Nodes (25): alembic_config, anon_client(), clean_tables(), client_for(), _client(), db(), login(), make_user() (+17 more)

### Community 29 - "Discovery Evidence & Cities"
Cohesion: 0.16
Nodes (13): _cities(), _evidence(), Assessment, Company, The company's best record (completed from its other records) with `state`; its…, The whole group is a company already in this search's results: all its records…, The stored source records (and their companies) of these candidates, as…, Attach every record of the group to the company: its locations first, then the… (+5 more)

### Community 30 - "Research HTTP Fetch"
Cohesion: 0.11
Nodes (22): check_url(), FetchError, is_public(), public_addresses(), _PublicOnlyBackend, _PublicOnlyTransport, Exception, SSRF-safe HTTP fetching for website research. Company websites come from public… (+14 more)

### Community 31 - "Company Profile Page"
Cohesion: 0.14
Nodes (26): CandidateOwnership(), CompanyProfile(), CompanyProfilePage(), CONTACT_SOURCE_LABEL, ContactsTab(), ContactValue(), EMPTY_CONTACT, InfoCard() (+18 more)

### Community 32 - "Research Run State"
Cohesion: 0.21
Nodes (26): Pipeline state of one research run., ResearchStatus, CompanyResearchRun, QualificationOut, _build(), _carry_earlier_evidence(), execute(), _fail() (+18 more)

### Community 33 - "Permissions & Activity Queries"
Cohesion: 0.13
Nodes (26): list_activities(), Session, User, get_summary(), Any, Session, User, Only real, stored figures. No projected or fictional sales metrics. (+18 more)

### Community 34 - "Import Field Conversion"
Cohesion: 0.12
Nodes (21): _as_text(), convert(), FieldSpec, _norm_header(), odoo_external_id(), odoo_int_id(), Any, Target fields for Odoo imports, header auto-detection and value conversion.… (+13 more)

### Community 35 - "Company Routes"
Cohesion: 0.20
Nodes (23): add_note(), check_duplicates(), claim_company(), create_company(), get_company(), list_companies(), CurrentUser, DbSession (+15 more)

### Community 36 - "OSM Discovery Provider"
Cohesion: 0.13
Nodes (19): SearchQuery, Country, _closed(), _facility(), OsmProvider, Path, Progress, Tags that mean "a place where things are made" (also the generic manufacturer… (+11 more)

### Community 37 - "Discovery Run Page"
Cohesion: 0.13
Nodes (19): ACTIVE, branchLabel(), DiscoveryRunPage(), FunnelStep(), Locations(), Progress(), RunView(), SHOW_REASON (+11 more)

### Community 38 - "Phase 0/1 Hardening Tests"
Cohesion: 0.14
Nodes (18): _claim(), fn(), _company_id(), _decide_new(), no_osm_backoff(), odoo_fixture(), fixture, _race() (+10 more)

### Community 39 - "Import Routes"
Cohesion: 0.20
Nodes (18): cancel(), confirm(), delete_import(), get_import(), get_preview(), list_imports(), DbSession, delete (+10 more)

### Community 40 - "AI Review Providers"
Cohesion: 0.16
Nodes (15): get_provider(), parse_review(), ProviderError, ProviderReview, BaseModel, Exception, Protocol, QualificationProvider (+7 more)

### Community 41 - "TypeScript Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 42 - "Website Classification"
Cohesion: 0.20
Nodes (15): What LeadFinder found at a company's website. A dead website is evidence, never…, WebsiteStatus, Page, classify(), _host(), _matches(), Website validation: does the company's website work, and is it a real company…, _same_site() (+7 more)

### Community 43 - "Overture Provider"
Cohesion: 0.20
Nodes (10): ProviderError, Exception, A source could not be queried. The message is shown to the user., _get_json(), _intersects(), OvertureProvider, Path, Progress (+2 more)

### Community 44 - "Branch Consolidation"
Cohesion: 0.22
Nodes (16): Automatic company discovery (Phase 1): providers -> normalise -> dedupe ->…, consolidate(), Group records of the same company (input best first, so each group's first…, names(), place(), Branch / location consolidation: one company with many locations, never one…, run_restaurants(), test_branches_with_different_phones_still_consolidate() (+8 more)

### Community 45 - "Research Routes"
Cohesion: 0.18
Nodes (17): get_run(), list_leads(), list_runs(), CurrentUser, DbSession, ge, get, le (+9 more)

### Community 46 - "Odoo Contact Matching"
Cohesion: 0.14
Nodes (12): analyse(), _analyse_contact(), Split an Odoo contact row into its company and its person. Company = Company…, CompanyIndex, CompanyMatch, find_matches(), add(), MatchSignals (+4 more)

### Community 47 - "Website Evidence Extraction"
Cohesion: 0.20
Nodes (16): CrawledPage, as_dicts(), _count(), extract(), add(), Fact, infer(), add() (+8 more)

### Community 48 - "Discovery Quality Tests"
Cohesion: 0.24
Nodes (13): cand(), _import_contacts(), one(), Phase 1 quality hardening: closed businesses, industry relevance, branch…, test_02_unknown_operating_status_is_not_rejected(), test_06_website_adds_confidence(), test_07_phone_adds_confidence(), test_08_industrial_category_adds_confidence() (+5 more)

### Community 49 - "Toast Notifications"
Cohesion: 0.16
Nodes (16): BAR, dismissToast(), DURATION, emit(), empty, ICON, ICON_TONE, items (+8 more)

### Community 50 - "Research Executor & Settings"
Cohesion: 0.17
Nodes (15): get_settings(), _ai(), default_fetcher(), _executor(), Any, Session, _schedule(), start() (+7 more)

### Community 51 - "Discovery Confidence & CRM Leads"
Cohesion: 0.14
Nodes (12): DiscoveryConfidence, How strongly the sources support a discovered company being a real, relevant…, CrmLead, An Odoo crm.lead record (lead or opportunity)., DiscoveryAction, Exception, Discovery runs: search sources, check quality, consolidate, check LeadFinder +…, Another search saved the same place at the same moment. (+4 more)

### Community 52 - "Discovery Provider Base"
Cohesion: 0.23
Nodes (13): closed_reason(), The shape every discovery source returns, and the small provider interface. A…, SearchResult, OpenStreetMap (from the Geofabrik country extract) as a second discovery…, Overture Maps Places as a discovery source. How the data is reached (see…, _sql_str(), json, logging (+5 more)

### Community 53 - "Geography & Cities"
Cohesion: 0.22
Nodes (13): Area, canonical_city(), _distance_km(), _fold(), in_area(), _names_match(), Countries and searchable areas (cities / governorates) for discovery. A place…, English city name for display/matching: the known city at these coordinates,… (+5 more)

### Community 54 - "Website Crawler"
Cohesion: 0.22
Nodes (13): crawl(), add(), CrawlResult, _kind(), normalize(), _parse(), Conservative website crawl: the home page plus the few internal pages that…, Crawl from the already-fetched home page (website validation visited it once). (+5 more)

### Community 55 - "Discovery Architecture Docs"
Cohesion: 0.19
Nodes (15): Company Discovery Pipeline, CompanyIndex, crm_leads table, Database Schema, discovery_results table, discovery_runs table, Duplicate Matching (deterministic signals), import_runs table (+7 more)

### Community 56 - "Sample Odoo Data & Ownership"
Cohesion: 0.15
Nodes (10): main(), Generate FICTIONAL Odoo export files for testing the import workflow. python -m…, crm_file(), names_in(), fixture, Private discovery ownership: a salesperson's discovered candidates are theirs…, team(), io (+2 more)

### Community 57 - "Architecture & API Docs"
Cohesion: 0.19
Nodes (13): LeadFinder Architecture (Phase 2), REST API endpoints, App Shell Navigation, Candidate Ownership (owner_id claim/release), companies table, Frontend Design System (CSS tokens), Integrations (odoo/, lusha/) disconnected, Routes -> Services -> Models layering (+5 more)

### Community 58 - "Campaign Service"
Cohesion: 0.36
Nodes (12): _attach_company_counts(), create_campaign(), get_campaign(), get_campaign_detail(), list_campaigns(), Any, Campaign, Session (+4 more)

### Community 59 - "HTTP Fetcher Client"
Cohesion: 0.18
Nodes (6): Fetcher, One HTTP client per research run. `transport` is replaced in tests…, Request, Response, Mock websites: URL -> body (200), (status, headers, body), or an exception to…, Web

### Community 60 - "Claude Provider"
Cohesion: 0.21
Nodes (9): ClaudeProvider, _claude_reply(), FakeClient, parametrize, test_claude_structured_response_is_parsed_and_requested_with_a_schema(), test_claude_timeout_and_api_errors_are_provider_errors(), test_claude_without_credentials_is_a_clear_provider_error(), test_malformed_claude_responses_are_rejected() (+1 more)

### Community 61 - "Qualification Rubric"
Cohesion: 0.27
Nodes (10): assess(), Assessment, _confidence(), _fit(), _int(), _quote(), Deterministic qualification rubric (versioned). Scores come from fixed weights…, Signals stated on the website: inferences and map data do not corroborate the… (+2 more)

### Community 62 - "Rate Limiter"
Cohesion: 0.20
Nodes (4): Small in-memory sliding-window rate limiter for the login endpoint. State is…, SlidingWindowRateLimiter, deque, time

### Community 63 - "Discovery Sources Docs"
Cohesion: 0.24
Nodes (11): duckdb, company_sources table, Discovery Providers (search -> SearchResult), quality.consolidate (places to companies), Troubleshooting, Branch Consolidation (one company, several locations), Discovery Confidence (High/Medium/Low), Environment Variables (.env) (+3 more)

### Community 64 - "Production Ops & Backups"
Cohesion: 0.24
Nodes (10): Production Docker Compose stack, backup service (scheduled pg_dump), discovery volume (cached source extracts), LeadFinder Operations Guide, Backups and Restore, Database Access (SSH tunnel), Git Workflow (main/develop/feature), Ownership Checklist (+2 more)

### Community 65 - "AI Research Docs"
Cohesion: 0.31
Nodes (9): anthropic SDK, crawl4ai, AI Review Provider (get_provider), Research Pipeline (website, crawl, evidence, rubric, providers), Qualification Rubric (Odoo/Frinzo fit), fetch.py SSRF protection, AI_PROVIDER (claude / rules / tecomsa), Company Research and Qualification (Phase 2) (+1 more)

### Community 66 - "Contact Routes"
Cohesion: 0.29
Nodes (8): create_contact(), list_contacts(), CurrentUser, DbSession, get, max_length, Pagination, post

### Community 67 - "System & Dashboard Routes"
Cohesion: 0.32
Nodes (8): dashboard(), health(), AdminUser, CurrentUser, DbSession, get, Read-only application status. Integration states reflect reality: nothing…, system_status()

### Community 68 - "Backend Requirements"
Cohesion: 0.29
Nodes (8): Backend requirements.txt, argon2-cffi, Backend requirements-dev.txt, pytest, FastAPI, PyJWT, SQLAlchemy 2, Authentication (Argon2id + JWT session cookie)

### Community 69 - "Research Test Fakes"
Cohesion: 0.25
Nodes (5): ai(), discovery_providers(), FakeAI, fixture, team()

### Community 70 - "Research Qualification Access"
Cohesion: 0.33
Nodes (7): get_run(), ColumnElement, User, Qualify a run whose qualification failed again, from its stored evidence (no…, Agents see the research they started; managers and admins see all., retry_qualification(), _run_visibility()

### Community 71 - "Root Layout & Fonts"
Cohesion: 0.29
Nodes (5): frontend_app_globals, display, metadata, mono, sans

### Community 72 - "Company Update Schema"
Cohesion: 0.47
Nodes (3): _CompanyFields, CompanyUpdate, field_validator

### Community 73 - "Dashboard Schemas"
Cohesion: 0.47
Nodes (5): DashboardSummary, ImportSummary, IntegrationStatus, BaseModel, SystemStatus

### Community 74 - "Dev Docker Compose"
Cohesion: 0.47
Nodes (6): Alembic, Development Docker Compose stack, backend service (FastAPI + alembic upgrade), PostgreSQL 16 db service, frontend service (Next.js), Next.js /api proxy

### Community 75 - "Odoo Import Docs"
Cohesion: 0.33
Nodes (6): openpyxl, imports volume (uploaded Odoo files), create_admin script, Odoo Import Center, seed_dev script (fictional demo data), TECOMSA LeadFinder AI

### Community 76 - "Campaign Tests"
Cohesion: 0.33
Nodes (5): test_agents_only_see_and_edit_their_own_campaigns(), test_campaign_creation_is_draft_and_audited(), test_campaign_validation(), test_company_can_be_linked_to_campaign(), test_only_draft_campaigns_are_editable()

### Community 77 - "Activity Routes"
Cohesion: 0.40
Nodes (5): list_activities(), CurrentUser, DbSession, get, Pagination

### Community 78 - "Discovery Provider Protocol"
Cohesion: 0.40
Nodes (4): DiscoveryProvider, Progress, Protocol, default_providers()

### Community 79 - "Salesperson Resolver"
Cohesion: 0.40
Nodes (4): name_key(), Case/whitespace-insensitive key for people and team names., Finds or creates salespeople by name during an import (cached per import)., SalespersonResolver

### Community 80 - "Research Payload"
Cohesion: 0.50
Nodes (4): _payload(), Assessment, Company, Everything the provider sees: compact, structured, no raw HTML.

### Community 81 - "Overture Extract Test"
Cohesion: 0.67
Nodes (3): Path, test_overture_provider_parses_filters_country_industry_and_city(), _write_overture_extract()

### Community 82 - "App Icon & Brand"
Cohesion: 0.67
Nodes (3): App Icon (icon.svg), Brand Red #DC1E26, Tecomsa 'T.' Monogram

## Knowledge Gaps
- **155 isolated node(s):** `21st`, `DiscoveryAction`, `TabKey`, `AREA_TONE`, `STATE` (+150 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 624 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UserRole` connect `Auth Roles & Test Fixtures` to `Config & Lusha Client`, `ORM Base & Models`, `Phase 0/1 Hardening Tests`, `Research Test Fakes`, `API Router & DB Deps`, `Activity Timeline & Enums`, `Auth & Password Hashing`, `Campaign Tests`, `Audit Log & Admin Scripts`, `Discovery Tests`, `Branch Consolidation`, `Discovery Quality Tests`, `Research Tests`, `Common Schema Validators`, `Sample Odoo Data & Ownership`, `Test DB Fixtures`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `Research Executor & Settings` to `Research Run State`, `System & Dashboard Routes`, `Config & Lusha Client`, `Import Routes`, `Import Mapping & Errors`, `API Router & DB Deps`, `AI Review Providers`, `Auth & Password Hashing`, `Activity Timeline & Enums`, `Discovery Tests`, `Discovery Provider Protocol`, `Discovery Run Service`, `Auth Roles & Test Fixtures`, `Discovery Confidence & CRM Leads`, `Research Tests`, `Qualification Rubric`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `page_response()` connect `API Router & DB Deps` to `Contact Routes`, `Company Routes`, `Import Routes`, `Activity Routes`, `Discovery Run Service`, `Discovery & Odoo Schemas`, `Research Routes`, `Odoo Records Listing`, `Campaign Routes`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Are the 115 inferred relationships involving `UserRole` (e.g. with `can_import()` and `require_roles()`) actually correct?**
  _`UserRole` has 115 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `FakeProvider` (e.g. with `Candidate` and `ProviderError`) actually correct?**
  _`FakeProvider` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `21st`, `DiscoveryAction`, `TabKey` to the rest of the system?**
  _155 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Campaign & User Forms` be split into smaller, more focused modules?**
  _Cohesion score 0.052659716653301256 - nodes in this community are weakly interconnected._