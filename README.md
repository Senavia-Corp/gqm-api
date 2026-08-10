# GQM Panel API

REST API backend for the GQM property restoration and maintenance management platform. Built with **Flask 3**, **SQLModel**, and **PostgreSQL**, it integrates in real-time with **Podio** (operational workflow), **QuickBooks Online** (accounting), and **Cloudinary** (file storage).

---

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Prerequisites & Setup](#prerequisites--setup)
3. [Environment Variables](#environment-variables)
4. [Project Structure](#project-structure)
5. [Database](#database)
6. [All API Endpoints](#all-api-endpoints)
7. [Authentication & Authorization](#authentication--authorization)
8. [Podio Integration](#podio-integration)
9. [QuickBooks Online Integration](#quickbooks-online-integration)
10. [Cloudinary Integration](#cloudinary-integration)
11. [Webhook System](#webhook-system)
12. [Metrics & Reporting](#metrics--reporting)
13. [Database Migrations](#database-migrations)
14. [Deployment](#deployment)

---

## Tech Stack

| Category | Package | Version |
|---|---|---|
| Web Framework | Flask | 3.1.2 |
| ORM / Validation | SQLModel (SQLAlchemy + Pydantic) | 0.0.27 |
| SQLAlchemy | SQLAlchemy | 2.0.43 |
| Database Driver | psycopg2-binary | 2.9.11 |
| Migrations | alembic | 1.18.1 |
| Authentication | PyJWT | 2.10.1 |
| Password Hashing | argon2-cffi | 25.1.0 |
| Configuration | python-decouple + python-dotenv | 3.8 / 1.1.1 |
| HTTP Client | requests | 2.32.5 |
| CORS | flask-cors | 6.0.1 |
| File Storage | cloudinary | >=1.36.0 |
| Excel Export | openpyxl | latest |
| PDF Generation | reportlab | 4.4.10 |
| Charts (PDF) | matplotlib + numpy | 3.10.8 / 2.4.2 |

---

## Prerequisites & Setup

**Python 3.10+** and **PostgreSQL** are required.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env with your values

# 4. Run database migrations
alembic upgrade head

# 5. Start the development server (port 80)
python main.py
```

The API will be available at `http://localhost:80`.

> **Note on port 80:** The app runs on port 80 by default (`app.run(port=80)`). On Linux/macOS, running on ports < 1024 requires `sudo` or you can change the port in `main.py`.

---

## Docker Setup (Recommended)

To run the project easily using Docker:

1. **Build and start the container:**
   ```bash
   docker compose up --build
   ```

2. **Access the API:**
   The API will be available at `http://localhost:8080`.

3. **Running in background:**
   ```bash
   docker compose up -d
   ```

4. **View logs:**
   ```bash
   docker compose logs -f
   ```

> **Environment Variables:** Docker is configured to read your existing `.env` file from `src/.env`. Ensure all required variables are set there.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values. The app will fail to start if `PUBLIC_URL` is missing or malformed.

### Core

| Variable | Description | Required |
|---|---|---|
| `SECRET_KEY` | General Flask secret key | Yes |
| `LOGIN_SECRET_KEY` | JWT access token signing key | Yes |
| `REFRESH_SECRET_KEY` | JWT refresh token signing key | Yes |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql://user:pass@host:port/db`) | Yes |
| `PUBLIC_URL` | Publicly accessible base URL of this API (used to register Podio webhooks, e.g., `https://api.example.com`) | Yes |

### Cloudinary

| Variable | Description |
|---|---|
| `CLOUDINARY_CLOUD_NAME` | Cloudinary account cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary public API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |

### QuickBooks Online

| Variable | Description |
|---|---|
| `QBO_CLIENT_ID` | Intuit developer app client ID |
| `QBO_CLIENT_SECRET` | Intuit developer app client secret |
| `QBO_REDIRECT_URI` | OAuth callback URL (must match Intuit app settings, e.g., `https://api.example.com/callback`) |

### Podio — OAuth Client

| Variable | Description |
|---|---|
| `PODIO_CLIENT_ID` | Podio app client ID |
| `PODIO_CLIENT_SECRET` | Podio app client secret |

### Podio — Static Apps (one credential pair each)

These apps have fixed IDs regardless of year:

| App | Variables |
|---|---|
| Clients (CLI) | `PODIO_CLIENTS_APP_ID`, `PODIO_CLIENTS_APP_TOKEN` |
| Parent Mgmt Co (PMC) | `PODIO_PAMGMTCO_APP_ID`, `PODIO_PAMGMTCO_APP_TOKEN` |
| Subcontractors (SUBC) | `PODIO_SUBCONTRACTOR_APP_ID`, `PODIO_SUBCONTRACTOR_APP_TOKEN` |
| Building Dept (BDEP) | `PODIO_BLDGDEPT_APP_ID`, `PODIO_BLDGDEPT_APP_TOKEN` |

### Podio — Dynamic Job Apps (per year × per type)

Each job type (QID, PTL, PAR) has its own Podio app per year (2023–2026), totaling 12 credential pairs:

| Variable pattern | Example |
|---|---|
| `PODIO_{TYPE}{YEAR}_APP_ID` | `PODIO_QID2026_APP_ID` |
| `PODIO_{TYPE}{YEAR}_APP_TOKEN` | `PODIO_QID2026_APP_TOKEN` |

Types: `QID`, `PTL`, `PAR` — Years: `2023`, `2024`, `2025`, `2026`

### Podio — Test/Admin Apps

Used for hook management and admin operations:

| App | Variables |
|---|---|
| QID Test | `QID_TAP_APP_ID`, `QID_TAP_APP_TOKEN` |
| PTL Test | `PTL_TAP_APP_ID`, `PTL_TAP_APP_TOKEN` |
| PAR Test | `PAR_TAP_APP_ID`, `PAR_TAP_APP_TOKEN` |
| Clients Test | `CLI_TAP_APP_ID`, `CLI_TAP_APP_TOKEN` |

> Total: ~50 environment variables. See `.env.example` for the full template.

---

## Project Structure

```
gqm-api/
├── main.py                          # App factory + blueprint registration (~50 blueprints)
├── requirements.txt                 # Python dependencies
├── alembic.ini                      # Alembic migration configuration
├── vercel.json                      # Vercel serverless deployment config
├── .env                             # Local environment variables (git-ignored)
├── .env.example                     # Environment variable template
│
├── migrations/                      # Alembic migration history
│   └── versions/                    # Auto-generated migration scripts
│
├── reports/                         # Output folder for generated PDF/Excel reports
│
└── src/
    ├── config.py                    # All env var loading (50+ variables)
    │
    ├── database/
    │   └── db_sqlmodel.py           # SQLAlchemy engine + get_session() context manager
    │
    ├── models/                      # 37 SQLModel table definitions
    │   ├── JobModel.py              # Core job entity (30+ financial fields)
    │   ├── ClientModel.py
    │   ├── MemberModel.py           # Internal staff (login-capable)
    │   ├── TechnicianModel.py       # Field technician (login-capable)
    │   ├── SubcontractorModel.py
    │   ├── SupplierModel.py
    │   ├── OrderModel.py
    │   ├── ChangeOrderModel.py
    │   ├── TasksModel.py
    │   ├── AttachmentsModel.py      # File references (Cloudinary URLs)
    │   ├── FinancialDocModel.py     # Invoice / Bill records
    │   ├── FinancialDocItemModel.py # Financial doc line items
    │   ├── FinancialTransModel.py   # Financial transactions
    │   ├── PurchaseModel.py
    │   ├── PurchaseOrderModel.py
    │   ├── PurchaseOrderItemModel.py
    │   ├── CommissionModel.py
    │   ├── CommissionDetailModel.py
    │   ├── CommissionGroupModel.py
    │   ├── MultiplierRModel.py
    │   ├── PaymentUnitModel.py
    │   ├── RoleModel.py
    │   ├── PermissionModel.py       # IAM policy documents (JSON)
    │   ├── TLActivityModel.py       # Audit timeline log
    │   ├── ChatModel.py
    │   ├── EstimateCostModel.py
    │   ├── BldgDeptModel.py
    │   ├── ParentMgmtCoModel.py     # Property management company (hierarchy root)
    │   ├── ManagerModel.py
    │   ├── SkillsModel.py
    │   ├── CertificateModel.py
    │   ├── GQMInventoryModel.py
    │   ├── ReimbursementModel.py
    │   ├── StandardPSModel.py
    │   ├── QBOTokensModel.py        # QuickBooks OAuth token storage
    │   └── link_models/             # Many-to-many junction tables
    │       ├── JobMember.py         # Jobs ↔ Members (with rol field)
    │       ├── JobMultiplierR.py
    │       ├── JobSubcontractor.py
    │       ├── JobPaymentU.py
    │       ├── ClientLinks.py       # Clients ↔ Members + Clients ↔ Managers
    │       ├── SkillSubcLink.py
    │       ├── FinancialLink.py
    │       ├── OpportunitiesLinks.py
    │       └── PermissionLinks.py   # Permissions ↔ Roles/Members/Technicians
    │
    ├── routes/                      # Flask Blueprint route files
    │   ├── Login_auth.py            # POST /auth/login, POST /auth/refresh, GET /auth/can
    │   ├── Job.py                   # Jobs CRUD + Excel export (1,077 lines)
    │   ├── Client.py                # Clients CRUD
    │   ├── Member.py                # Members CRUD
    │   ├── Technician.py            # Technicians CRUD
    │   ├── Subcontractor.py         # Subcontractors CRUD
    │   ├── Supplier.py              # Suppliers CRUD
    │   ├── Order.py                 # Orders CRUD
    │   ├── ChangeOrder.py           # Change orders CRUD
    │   ├── Tasks.py                 # Tasks CRUD
    │   ├── Attachments.py           # File upload/download/delete (Cloudinary proxy)
    │   ├── ChatMessage.py           # Job chat messages
    │   ├── FinancialDocument.py     # Financial documents CRUD
    │   ├── FinancialDocItem.py      # Financial doc line items CRUD
    │   ├── FinancialTransaction.py  # Transactions CRUD
    │   ├── Purchase.py              # Purchases CRUD
    │   ├── PurchaseOrder.py         # Purchase orders CRUD
    │   ├── PurchaseOrderItem.py     # PO items CRUD
    │   ├── Commission.py            # Commissions CRUD
    │   ├── CommissionDetail.py      # Commission details CRUD
    │   ├── CommissionGroup.py       # Commission groups CRUD
    │   ├── MultiplierR.py           # Multipliers CRUD
    │   ├── PaymentUnit.py           # Payment units CRUD
    │   ├── Skills.py                # Skills CRUD
    │   ├── Opportunities.py         # Opportunities CRUD
    │   ├── TLActivity.py            # Timeline activity CRUD
    │   ├── BuildingDepartment.py    # Building departments CRUD
    │   ├── Manager.py               # Managers CRUD
    │   ├── ParentMgmtCo.py          # Parent management companies CRUD
    │   ├── Certificate.py           # Certificates CRUD
    │   ├── GQMInventory.py          # Inventory CRUD
    │   ├── Reimbursement.py         # Reimbursements CRUD
    │   ├── StandardPS.py            # Standard pricing structures CRUD
    │   ├── Role.py                  # Roles CRUD
    │   ├── Permission.py            # Permissions CRUD
    │   ├── Webhook_bp.py            # Podio + QBO webhook handlers (455 lines)
    │   ├── timeline_metrics_bp.py   # Timeline metrics endpoint
    │   ├── Links/                   # Many-to-many relationship management
    │   │   ├── JobLinks.py          # Job ↔ Member/Multiplier/Subcontractor/PaymentUnit
    │   │   ├── ClientLinks.py       # Client ↔ Manager/Member
    │   │   ├── SkillSubcLink.py     # Skill ↔ Subcontractor
    │   │   ├── OpportunitiesLinks.py
    │   │   ├── FinancialLinks.py
    │   │   └── PermissionLinks.py
    │   ├── Dashboard/               # Aggregated metrics endpoints
    │   │   ├── JobsM.py
    │   │   ├── MembersM.py
    │   │   ├── CommunitiesM.py
    │   │   └── SubcontractorsM.py
    │   ├── financial_routes/        # Financial reporting
    │   │   ├── financial_metrics_bp.py
    │   │   └── FinancialJobReports.py
    │   ├── podio_routes/            # Podio admin & sync
    │   │   ├── sync_routes.py       # Phase 1 & 2 sync
    │   │   ├── revision_route.py    # Post-sync integrity check
    │   │   └── AdminHooks.py        # Register/delete Podio webhooks
    │   └── qbo_routes/
    │       └── app_urls.py          # QBO OAuth + data fetch + sync
    │
    ├── utils/
    │   ├── audit.py                 # log_activity() → writes to TLActivity
    │   ├── pagination.py            # @paginate() decorator
    │   ├── job_calculator.py        # recalculate_and_apply() — job financial recalc
    │   ├── commission_calculator.py # Commission computation engine
    │   ├── policy_evaluator.py      # IAM policy evaluation (wildcard support)
    │   ├── relationships.py         # add_relationships() helper
    │   ├── id_generator.py          # Custom ID generation (e.g., "CLI-001")
    │   ├── get_podio_items.py       # Fetch single Podio item by ID
    │   ├── podio_webhook_core.py    # Core webhook event handlers (create/update/delete/file)
    │   ├── middleware/
    │   │   ├── auth/
    │   │   │   ├── jwt_handler.py          # create_access_token(), decode_*()
    │   │   │   ├── password_hashing.py     # hash_password(), verify_password() via Argon2
    │   │   │   └── routes_protection.py    # @require_permission() decorator
    │   │   ├── logs/
    │   │   │   ├── request_logger.py       # HTTP request/response logging middleware
    │   │   │   └── logs.py                 # Logger instance
    │   │   ├── exceptions_handler.py       # @handle_exceptions() decorator
    │   │   └── retries/
    │   │       └── db_route_retries/
    │   │           ├── add_session.py      # save_with_retry()
    │   │           └── delete_session.py   # delete_with_retry()
    │   ├── mappers/
    │   │   ├── from_podio/                 # Podio JSON → Python model dicts
    │   │   │   ├── job_mapper.py
    │   │   │   ├── client_mapper.py
    │   │   │   ├── subcontractor_mapper.py
    │   │   │   ├── bldg_dept_mapper.py
    │   │   │   ├── parent_mgmt_co_mapper.py
    │   │   │   ├── podio_value_extractor.py
    │   │   │   ├── podio_relationships.py
    │   │   │   ├── clean_podio_fields.py
    │   │   │   └── convert_value_podio.py
    │   │   ├── to_podio/                   # Python model dicts → Podio JSON
    │   │   │   ├── qid_mapper.py
    │   │   │   ├── ptl_mapper.py
    │   │   │   ├── par_mapper.py
    │   │   │   ├── client_mapper.py
    │   │   │   └── order_mapper.py
    │   │   ├── from_qbo/                   # QuickBooks JSON → Python model dicts
    │   │   │   ├── invoice_mapper.py
    │   │   │   ├── bill_mapper.py
    │   │   │   ├── payment_mapper.py
    │   │   │   └── vendor_mapper.py
    │   │   ├── mapper_aux_functions.py
    │   │   └── qbo_aux_functions.py
    │   └── validators/
    │
    ├── services/
    │   ├── commission_service.py           # process_job_to_commissions()
    │   ├── excel_report/
    │   │   ├── export_schema.py            # JobExportRequest Pydantic schema
    │   │   └── export_service.py           # generate_jobs_excel()
    │   └── metrics/
    │       └── aux_func_metrics.py         # PDF metrics generation helpers
    │
    ├── podio/                              # Podio integration layer
    │   ├── podio_auth.py                   # OAuth token generation & caching
    │   ├── get_user_id.py                  # GET /podio/users endpoint
    │   ├── services/                       # Entity-specific Podio API wrappers
    │   │   ├── podio_base_services.py
    │   │   ├── sync_podio_to_db.py         # Batch item fetching
    │   │   ├── client_services.py
    │   │   ├── job_services.py
    │   │   ├── subcontractor_services.py
    │   │   ├── pa_mgmt_co_services.py
    │   │   ├── bldg_dept_services.py
    │   │   ├── tasks_services.py
    │   │   └── order_services.py
    │   ├── sync/                           # Phase 1 & 2 sync scripts
    │   │   ├── sync_clients.py
    │   │   ├── sync_jobs.py
    │   │   ├── sync_subcontractors.py
    │   │   ├── sync_attachments.py
    │   │   ├── sync_orders.py
    │   │   ├── sync_pa_mgmt_co.py
    │   │   ├── sync_bldg_dept.py
    │   │   ├── sync_tasks.py
    │   │   └── sync_revision.py            # Data integrity validator
    │   └── webhook/                        # Real-time event processors
    │       ├── func_hooks.py
    │       ├── client_hook_sync.py         # process_clients_podio()
    │       ├── jobs_hook_sync.py           # process_jobs_podio()
    │       └── subc_hook_sync.py           # process_subcs_podio()
    │
    ├── quickbooks/                         # QuickBooks Online integration
    │   ├── qbo_auth.py                     # OAuth flow + token refresh + DB storage
    │   ├── services/
    │   │   ├── qbo_base_services.py
    │   │   ├── invoices_services.py
    │   │   ├── bills_services.py
    │   │   ├── payments_services.py
    │   │   └── vendors_services.py
    │   ├── sync/
    │   │   ├── sync_invoices_with_payments.py
    │   │   ├── sync_bills_with_payments.py
    │   │   ├── sync_job_financials.py
    │   │   └── sync_functions.py
    │   ├── webhook/
    │   │   ├── events.py                   # event_delete_qbo(), event_void_qbo()
    │   │   └── functions.py                # validate_qbo_signature(), routing
    │   └── responses/                      # QBO response schemas
    │
    ├── cloudinary/
    │   └── service.py                      # upload_to_cloudinary(), delete_from_cloudinary()
    │
    └── tests/
        ├── test_podio_auth.py
        ├── test_get_podio_items.py
        ├── test_podio_webhook.py
        ├── test_get_item_podio.py
        ├── debug_podio.py
        └── test_sandbox.py                 # QBO sandbox test
```

---

## Database

**Engine:** PostgreSQL  
**ORM:** SQLModel 0.0.27 — combines SQLAlchemy (query engine) with Pydantic (validation).  
**Migrations:** Alembic (`alembic upgrade head` to apply all pending migrations).

### Session Management

All routes use a per-request context manager:

```python
from src.database.db_sqlmodel import get_session

with get_session() as session:
    result = session.exec(select(Job)).all()
    session.add(new_record)
    session.commit()
```

### Data Models

The schema has **37 models** and **46 tables total** (including junction tables).

#### Core Entities

| Model | Table | Primary Key | Description |
|---|---|---|---|
| `Job` | `jobs` | `ID_Jobs` | Central entity — 30+ financial fields, linked to clients, members, subcontractors, orders |
| `Client` | `client` | `ID_Client` | Property owner; belongs to `ParentMgmtCo` |
| `ParentMgmtCo` | `parent_mgmt_co` | `ID_Community_Tracking` | Root of the client hierarchy (property management company) |
| `Member` | `member` | `ID_Member` | Internal GQM staff; login-capable; has optional `Role` |
| `Technician` | `technician` | `ID_Technician` | Field technician; login-capable; direct permission assignment |
| `Role` | `role` | `ID_Role` | Role group for members; holds `Permission` sets |
| `Permission` | `permission` | `ID_Permission` | IAM policy document (JSON); linked to roles, members, technicians |
| `Subcontractor` | `subcontractor` | `ID_Subcontractor` | External contractor; many-to-many with jobs and skills |
| `Supplier` | `supplier` | `ID_Supplier` | Material vendor for purchase orders |

#### Financial Entities

| Model | Table | Description |
|---|---|---|
| `Order` | `order` | Vendor order linked to a job |
| `ChangeOrder` | `change_order` | Job scope change request |
| `Purchase` | `purchase` | Procurement record |
| `PurchaseOrder` | `purchase_order` | Formal PO to a supplier |
| `PurchaseOrderItem` | `purchase_order_item` | PO line items |
| `FinancialDocument` | `financial_doc` | Invoice or Bill (from QBO) |
| `FinancialDocItem` | `financial_doc_item` | Financial doc line items |
| `FinancialTransaction` | `financial_trans` | Individual payment/receipt transaction |
| `Commission` | `commission` | Member commission record |
| `CommissionDetail` | `commission_detail` | Commission calculation breakdown |
| `CommissionGroup` | `commission_group` | Commission grouping |

#### Operational Entities

| Model | Table | Description |
|---|---|---|
| `Task` | `tasks` | Subtask within a job |
| `Attachments` | `attachments` | Cloudinary file references (`Link` = secure URL, `podio_file_id`) |
| `ChatMessage` | `chat` | Job-scoped internal messages |
| `TLActivity` | `tl_activity` | Audit log; auto-populated by webhooks and route decorators |
| `Opportunity` | `opportunities` | Business opportunity / lead |
| `Certificate` | `certificate` | Subcontractor certifications with expiration tracking |
| `BuildingDept` | `bldg_dept` | Building department tracking |
| `Manager` | `manager` | Manager / supervisor entity |
| `Skills` | `skills` | Job specialties and trade competencies |
| `Multiplier` | `multiplier_r` | Financial multipliers applied to jobs |
| `PaymentUnit` | `payment_unit` | Payment unit types |
| `GQMInventory` | `gqm_inventory` | Internal inventory tracking |
| `Reimbursement` | `reimbursement` | Reimbursement records |
| `StandardPS` | `standard_ps` | Standard pricing structures |
| `QBOTokens` | `qbo_tokens` | QuickBooks OAuth token storage (keyed by `realm_id`) |

#### Junction Tables (Many-to-Many)

| Junction | Entities | Extra fields |
|---|---|---|
| `job_member_link` | Jobs ↔ Members | `rol` (role of member in this job) |
| `job_multiplier_r_link` | Jobs ↔ Multipliers | — |
| `job_subcontractor_link` | Jobs ↔ Subcontractors | — |
| `job_payment_u_link` | Jobs ↔ Payment Units | — |
| `client_member_link` | Clients ↔ Members | — |
| `client_manager_link` | Clients ↔ Managers | — |
| `skill_subcontractor_link` | Skills ↔ Subcontractors | — |
| `opportunities_skills_link` | Opportunities ↔ Skills | — |
| `opportunities_subcontractors_link` | Opportunities ↔ Subcontractors | — |
| `financial_link` | FinancialDocs ↔ Transactions | — |
| `permission_role_link` | Permissions ↔ Roles | — |
| `permission_member_link` | Permissions ↔ Members | — |
| `permission_technician_link` | Permissions ↔ Technicians | — |
| `purchase_supplier_link` | Purchases ↔ Suppliers | — |

#### Podio Fields

Every model that originates from Podio has:
- `podio_item_id` — Indexed; used as the external reference for webhook updates.
- `podio_profile_id` — Optional profile reference.
- `Attachments` also tracks `podio_file_id` for file event handling.

---

## All API Endpoints

All routes are registered as Flask Blueprints in `main.py`.

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Login with `{ Email_Address, Password }`. Returns JWT tokens + user data + policies. |
| POST | `/auth/refresh` | Refresh access token using `{ refresh_token }` in body or `Authorization` header. |
| GET | `/auth/can?actions=job:read,client:update` | Check multiple permissions at once. Returns `{ results: { "job:read": true, ... } }`. |

### Jobs

| Method | Path | Description |
|---|---|---|
| GET | `/jobs/` | List all jobs (paginated). |
| GET | `/jobs/jobs_table` | Lightweight paginated table view. Query params: `page`, `limit`, `type`, `status`, `year`, `search`, `client_id`, `member_id`, `parent_mgmt_co_id`, `date_from`, `date_to`, `subcontractor_id`. |
| GET | `/jobs/oldest` | Get oldest unresolved job. Query param: `parent_mgmt_co_id`. |
| GET | `/jobs/<id_job>` | Full job detail with nested client, members, multipliers, subcontractors, orders, etc. |
| POST | `/jobs/` | Create job. |
| PUT | `/jobs/<id_job>` | Update job. Triggers `recalculate_and_apply()` for financial fields. |
| DELETE | `/jobs/<id_job>` | Delete job. |
| POST | `/jobs/excel/export` | Export filtered jobs to `.xlsx`. Body: `JobExportRequest` schema. |

### Clients

| Method | Path | Description |
|---|---|---|
| GET | `/clients/` | List clients (paginated). |
| GET | `/clients/table` | Lightweight table. Query params: `page`, `limit`, `q` (search). |
| GET | `/clients/<id_client>` | Client detail. |
| POST | `/clients/` | Create client. |
| PUT | `/clients/<id_client>` | Update client. |
| DELETE | `/clients/<id_client>` | Delete client. |

### Members

| Method | Path | Description |
|---|---|---|
| GET | `/members/` | List members. |
| GET | `/members/<id_member>` | Member detail with role and permissions. |
| POST | `/members/` | Create member. Password is hashed with Argon2. |
| PUT | `/members/<id_member>` | Update member. |
| DELETE | `/members/<id_member>` | Delete member. |

### Technicians

| Method | Path | Description |
|---|---|---|
| GET | `/technicians/` | List technicians. |
| GET | `/technicians/<id_tech>` | Technician detail. |
| POST | `/technicians/` | Create technician. |
| PUT | `/technicians/<id_tech>` | Update technician. |
| DELETE | `/technicians/<id_tech>` | Delete technician. |

### Subcontractors

| Method | Path | Description |
|---|---|---|
| GET | `/subcontractors/` | List subcontractors. |
| GET | `/subcontractors/<id_subc>` | Subcontractor detail with skills and certificates. |
| POST | `/subcontractors/` | Create subcontractor. |
| PUT | `/subcontractors/<id_subc>` | Update subcontractor. |
| DELETE | `/subcontractors/<id_subc>` | Delete subcontractor. |

### Suppliers

Standard CRUD at `/suppliers/` and `/suppliers/<id>`.

### Orders & Change Orders

| Method | Path | Description |
|---|---|---|
| GET/POST | `/orders/` | List / create orders. |
| GET/PUT/DELETE | `/orders/<id_order>` | Order by ID. |
| GET/POST | `/change_orders/` | List / create change orders. |
| GET/PUT/DELETE | `/change_orders/<id_change_order>` | Change order by ID. |

### Tasks

| Method | Path | Description |
|---|---|---|
| GET | `/tasks/` | List tasks. Query param: `job_id` to filter by job. |
| GET | `/tasks/<id_task>` | Task detail. |
| POST | `/tasks/` | Create task. |
| PUT | `/tasks/<id_task>` | Update task. |
| DELETE | `/tasks/<id_task>` | Delete task. |

### Attachments

| Method | Path | Description |
|---|---|---|
| GET | `/attachments/` | List attachments. |
| GET | `/attachments/<id_attachment>` | Attachment detail (includes Cloudinary URL). |
| POST | `/attachments/upload` | Upload file (`multipart/form-data`). Uploads to Cloudinary, stores record in DB. Fields: `file`, `entity_id`, `year?`, `description?`, `tag?`. Query: `sync_podio=true|false`. |
| DELETE | `/attachments/<id_attachment>` | Delete from Cloudinary and DB. |

### Financial Documents & Transactions

Standard CRUD at `/financial_documents/`, `/financial_doc_items/`, `/financial_transactions/`.

### Purchases & Purchase Orders

| Method | Path | Description |
|---|---|---|
| GET/POST | `/purchases/` | List / create purchases. |
| GET/PUT/DELETE | `/purchases/<id>` | Purchase by ID. |
| GET/POST | `/purchase_orders/` | List / create POs. |
| GET/PUT/DELETE | `/purchase_orders/<id>` | PO by ID. |
| GET/POST | `/purchase_order_items/` | List / create PO line items. |
| GET/PUT/DELETE | `/purchase_order_items/<id>` | PO item by ID. |

### Commissions

| Method | Path | Description |
|---|---|---|
| GET/POST | `/commissions/` | List / create commissions. |
| GET/PUT/DELETE | `/commissions/<id>` | Commission by ID. |
| GET/POST | `/commission_details/` | Commission detail records. |
| GET/POST | `/commission_groups/` | Commission groups. |

### Multipliers & Payment Units

Standard CRUD at `/multipliers/` and `/payment_units/`.

### Chat Messages

| Method | Path | Description |
|---|---|---|
| GET | `/chat/` | List chat messages. |
| GET | `/chat/<id_message>` | Message detail. |
| POST | `/chat/` | Create message. Supports optional file attachment (uploads to Cloudinary). |
| DELETE | `/chat/<id_message>` | Delete message. |

### Opportunities & Skills

| Method | Path | Description |
|---|---|---|
| GET/POST | `/opportunities/` | List / create opportunities. |
| GET/PUT/DELETE | `/opportunities/<id>` | Opportunity by ID. |
| GET/POST | `/skills/` | List / create skills. |
| GET/PUT/DELETE | `/skills/<id>` | Skill by ID. |

### Timeline Activity

| Method | Path | Description |
|---|---|---|
| GET | `/timeline/` | Paginated activity log. |
| GET | `/timeline/<id_activity>` | Single activity entry. |
| POST | `/timeline/` | Manual activity entry. |

> Most entries are created automatically by webhook handlers via `log_activity()`.

### Master Data: Communities, Managers, Building Departments

Standard CRUD at `/parent_mgmt_co/`, `/managers/`, `/bldg_dept/`.

### Roles & Permissions

| Method | Path | Description |
|---|---|---|
| GET/POST | `/roles/` | List / create roles. |
| GET/PUT/DELETE | `/roles/<id>` | Role by ID. |
| GET/POST | `/permissions/` | List / create permission policies. |
| GET/PUT/DELETE | `/permissions/<id>` | Permission policy by ID. |

### Other Resources

Standard CRUD at `/certificates/`, `/inventory/`, `/reimbursements/`, `/standard_ps/`.

### Relationship Management (Links)

These endpoints manage many-to-many associations between entities.

| Method | Path | Description |
|---|---|---|
| GET/POST | `/job_members/` | List / assign members to jobs (with `rol` field). |
| DELETE | `/job_members/<job_id>/<member_id>` | Remove member from job. |
| GET/POST | `/job_subcontractors/` | Assign subcontractors to jobs. |
| GET/POST | `/job_multipliers/` | Assign multipliers to jobs. |
| GET/POST | `/client_managers/` | Assign managers to clients. |
| GET/POST | `/client_members/` | Assign members to clients. |
| GET/POST | `/skills_subcontractors/` | Link skills to subcontractors. |
| GET/POST | `/opportunities_skills/` | Link skills to opportunities. |
| GET/POST | `/permission_roles/` | Assign permissions to roles. |
| GET/POST | `/permission_members/` | Assign permissions directly to members. |
| GET/POST | `/permission_technicians/` | Assign permissions to technicians. |
| GET/POST | `/purchase_supplier/` | Link purchases to suppliers. |
| GET/POST | `/fdocument_ftransaction/` | Link financial documents to transactions. |

### Dashboard / Metrics

| Method | Path | Description |
|---|---|---|
| GET | `/dashboard/jobs/...` | Job metrics grouped by status, type, date. |
| GET | `/dashboard/members/...` | Member performance metrics. |
| GET | `/dashboard/communities/...` | Parent company metrics. |
| GET | `/dashboard/subcontractors/...` | Subcontractor performance. |
| GET | `/timeline/metrics` | Timeline activity metrics. |
| POST | `/metrics/jobs/pdf` | Generate job metrics PDF report. |
| POST | `/financial/metrics/pdf` | Generate financial metrics PDF (uses QBO data). |
| GET | `/financial/job_reports/<job_id>` | Financial summary for a specific job. |

### Podio Admin & Sync

| Method | Path | Description |
|---|---|---|
| POST | `/podio/sync/phase1` | Fetch all items from a Podio app into the DB. |
| POST | `/podio/sync/phase2` | Link relationships after phase 1. |
| GET | `/podio/sync/revision/<app_type>` | Verify data integrity after sync. |
| POST | `/podio/admin/create-hook/<app_type>` | Register webhook on a Podio app. |
| DELETE | `/podio/admin/delete-hook/<hook_id>` | Unregister webhook from Podio. |
| GET | `/podio/users` | Fetch Podio user IDs. |

### QuickBooks Online

| Method | Path | Description |
|---|---|---|
| GET | `/qbo/connect` | Initiate QuickBooks OAuth flow (redirects to Intuit). |
| GET | `/callback` | OAuth callback — exchanges code for tokens, stores in DB. |
| GET | `/qbo/disconnect/<realm_id>` | Revoke QBO connection and delete token. |
| GET | `/qbo/invoices/<realm_id>` | Fetch invoices from QBO. Query: `start`, `limit`. |
| GET | `/qbo/invoices/<realm_id>/job/<job_code>` | Invoices filtered by job code. |
| GET | `/qbo/money_received/<realm_id>` | Fetch customer payments. |
| GET | `/qbo/bills/<realm_id>` | Fetch vendor bills. |
| GET | `/qbo/bills/<realm_id>/job/<job_code>` | Bills filtered by job code. |
| GET | `/qbo/vendors/<realm_id>` | Fetch vendor list. |
| POST | `/qbo/invoices_payments/<realm_id>/job/<job_code>/sync` | Sync invoices + payments for job into GQM DB. |
| POST | `/qbo/bills_payments/<realm_id>/job/<job_code>/sync` | Sync bills + payments for job into GQM DB. |
| POST | `/qbo/job_financials/<realm_id>/job/<job_code>/sync` | Full financial sync for a job. |

### Webhooks

| Method | Path | Description |
|---|---|---|
| POST | `/webhook/podio/others/no_relations/<app_type>` | Podio events for PMC and BDEP apps. |
| POST | `/webhook/podio/others/relations/<app_type>` | Podio events for CLI (Clients) and SUBC (Subcontractors). |
| POST | `/webhook/podio/jobs/<app_type>/<year>` | Podio job events. `app_type`: QID/PTL/PAR. `year`: 2023–2026. |
| POST | `/webhook/qbo` | QuickBooks Online entity change events. |

---

## Authentication & Authorization

### Login Flow

```
POST /auth/login
Body: { "Email_Address": "user@gqm.com", "Password": "secret" }
```

1. The API searches the `Member` table by email. If not found, searches `Technician`.
2. Password is verified using Argon2 (`verify_password()`).
3. Two JWTs are issued: access token (60 min) and refresh token (7 days).
4. The response includes the user object, role details, and all applicable policies.

**Response:**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "bearer",
  "user_type": "member",
  "user_id": "MEM-001",
  "user_data": { "ID_Member": "...", "Member_Name": "...", ... },
  "role_detail": { "ID_Role": "...", "Name": "..." },
  "policies": ["job:read", "client:update", ...]
}
```

### Token Details

| Token | Signing Key | Expiry | Payload |
|---|---|---|---|
| Access | `LOGIN_SECRET_KEY` | 60 min | `{ sub: user_id, role: "member|technician" }` |
| Refresh | `REFRESH_SECRET_KEY` | 7 days | `{ sub: user_id, role: "member|technician" }` |

### Token Refresh

```
POST /auth/refresh
Body: { "refresh_token": "..." }
# OR Header: Authorization: Bearer <refresh_token>
```

Returns a new `access_token` (60 min). The refresh token itself is not rotated.

### Password Hashing

All passwords are hashed with **Argon2** via `argon2-cffi`. Functions in `src/utils/middleware/auth/password_hashing.py`:
- `hash_password(plain)` → Argon2 hash string
- `verify_password(plain, hashed)` → bool

### IAM-Style Authorization

Permissions are stored as **policy documents** (JSON) in the `Permission` table. Each document is an array of action-effect pairs:

```json
[
  { "action": "job:read",    "effect": "allow" },
  { "action": "client:*",   "effect": "allow" },
  { "action": "admin:delete","effect": "deny"  }
]
```

**Evaluation** (`src/utils/policy_evaluator.py`):
- Supports wildcards: `"client:*"` matches `"client:read"`, `"client:update"`, etc.
- **Deny takes precedence** over Allow for the same action.
- Policies are collected from three sources: the user's direct permissions + their role's permissions.

**Route Protection:**

```python
from src.utils.middleware.auth.routes_protection import require_permission

@jobs_bp.route("/", methods=["GET"])
@require_permission("job:read")
def list_jobs():
    ...

# Accept any of multiple permissions (OR logic)
@require_permission(["job:read", "job:read_basics"])
def list_jobs_limited():
    ...
```

### User Types

| Type | Model | Login | Permissions |
|---|---|---|---|
| `member` | `Member` | Yes | Via Role (group) + direct assignment |
| `technician` | `Technician` | Yes | Direct assignment only |

---

## Podio Integration

Podio is the **primary source of truth for operational data** (jobs, clients, subcontractors, communities, building departments). The GQM API maintains a synced local PostgreSQL copy and receives real-time updates via webhooks.

### Podio App Topology

Each Podio app corresponds to a specific GQM entity. Job apps are year-scoped:

| App Key | Entity | Type | Notes |
|---|---|---|---|
| `CLI` | Clients | Static | Single app, all years |
| `PMC` | Parent Mgmt Companies | Static | Single app |
| `SUBC` | Subcontractors | Static | Single app |
| `BDEP` | Building Departments | Static | Single app |
| `QID_{year}` | Jobs — QID type | Dynamic | One app per year (2023–2026) |
| `PTL_{year}` | Jobs — PTL type | Dynamic | One app per year |
| `PAR_{year}` | Jobs — PAR type | Dynamic | One app per year |

### OAuth Token Flow

`src/podio/podio_auth.py` manages app-level OAuth tokens:

```python
headers = get_podio_headers(app_type="QID", year=2026)
# Returns: { "Authorization": "OAuth2 <token>", "Content-Type": "application/json" }
```

- Tokens are cached in a global `_token_cache` dict keyed by `"QID_2026"` or `"CLI"`.
- Cached tokens are reused until expired (typically 8 hours), then refreshed automatically.
- Each app has its own `app_id` + `app_token` pair — no user credentials are needed.

### Two-Phase Initial Sync

Used for the initial data migration from Podio to the GQM database:

```
POST /podio/sync/phase1
```
1. Fetches all items from each configured Podio app.
2. Maps Podio field values to local model fields via `src/utils/mappers/from_podio/`.
3. Creates or updates DB records; stores `podio_item_id` on each record.

```
POST /podio/sync/phase2
```
1. Reads relationship fields (linked item references) from already-synced records.
2. Creates many-to-many links in junction tables (e.g., job members, client managers).

```
GET /podio/sync/revision/<app_type>
```
Validates that local counts match Podio counts and flags missing records.

### Real-Time Webhooks

Podio sends HTTP POST events to the GQM API whenever an item is created, updated, deleted, or has a file change.

#### Registering Webhooks

```
POST /podio/admin/create-hook/<app_type>
```
Calls Podio's hook registration API with `PUBLIC_URL + /webhook/podio/...` as the target. `PUBLIC_URL` must be a publicly accessible HTTPS URL.

Podio sends a `hook.verify` event immediately after registration — the handler in `parse_and_validate_webhook()` calls `activate_podio_webhook()` to confirm it.

#### Webhook Endpoints & Events

**Endpoint 1 — Non-relational apps (PMC, BDEP):**
```
POST /webhook/podio/others/no_relations/<app_type>
```

**Endpoint 2 — Relational apps (CLI, SUBC):**
```
POST /webhook/podio/others/relations/<app_type>
```
These call dedicated processors (`process_clients_podio()`, `process_subcs_podio()`) for entities that have complex relationship logic.

**Endpoint 3 — Job apps (QID, PTL, PAR):**
```
POST /webhook/podio/jobs/<app_type>/<year>
```
Additional logic beyond basic CRUD:
- Captures the Podio user who triggered the event (`current_revision.created_by.name`).
- On `item.update`: detects status changes; if the new status is `"PAID"`, triggers `process_job_to_commissions()`.
- Calls `recalculate_and_apply()` after every update to keep financial fields consistent.
- On `item.delete`: cascades the deletion to linked `Order` and `ChangeOrder` records.

#### Event Handlers (`src/utils/podio_webhook_core.py`)

| Handler | Trigger | Action |
|---|---|---|
| `event_create()` | `item.create` | Insert new DB record if `podio_item_id` not found |
| `event_update()` | `item.update` | Update existing record; creates it if missing |
| `event_delete()` | `item.delete` | Delete DB record by `podio_item_id` |
| `process_file_change_event()` | `file.change` | See file flow below |

#### File Attachment Flow

When Podio fires a `file.change` event:

```
Podio file event
  ↓
GQM API receives webhook
  ↓
GET /file/<podio_file_id>/raw  (download from Podio)
  ↓
upload_to_cloudinary(file_bytes, filename, mimetype, folder)
  ↓
INSERT into attachments  (Link = Cloudinary secure_url, podio_file_id stored)
```

File event subtypes handled:
- `file_created` — Download + upload + create `Attachments` record.
- `file_deleted` — Delete from Cloudinary (`delete_from_cloudinary()`) + delete from DB.
- `file_replaced` — Delete old + create new.

### Bidirectional Mappers

| Direction | Location | Purpose |
|---|---|---|
| Podio → DB | `src/utils/mappers/from_podio/` | Parse Podio's nested JSON field values into flat Python dicts |
| DB → Podio | `src/utils/mappers/to_podio/` | Serialize local model changes back to Podio update format |

The `podio_value_extractor.py` module handles Podio's unusual field format where each field value is wrapped in a `values` array with type-specific keys (`text`, `date`, `app_ref`, `embed`, etc.).

---

## QuickBooks Online Integration

QBO is used for **financial reconciliation** — pulling invoices, bills, and payments from the accounting system into the GQM database.

### OAuth 2.0 Flow

`src/quickbooks/qbo_auth.py` manages the full OAuth lifecycle:

```
1. GET /qbo/connect
   → Builds Intuit authorization URL (scope: accounting)
   → Redirects user to Intuit login

2. User authorizes app on Intuit

3. GET /callback?code=<auth_code>&realmId=<realm_id>
   → exchange_code_for_tokens(code)
   → Stores { access_token, refresh_token, expires_in, realm_id }
     in qbo_tokens table

4. All subsequent API calls use get_valid_access_token(realm_id)
   → Checks expiry (with 5-minute buffer)
   → Auto-refreshes if expired via refresh_access_token()
   → Returns valid access_token
```

`realm_id` is the QuickBooks company ID, used as the primary key for token storage. A single GQM instance can be connected to multiple QBO companies.

### Data Synchronization

Financial data is synced per-job using the job code (e.g., `QID51894`) as the linking key:

```
POST /qbo/invoices_payments/<realm_id>/job/<job_code>/sync
```
1. Fetches invoices from QBO where the description matches `job_code`.
2. Fetches corresponding payments.
3. Creates/updates `FinancialDocument` (type="Invoice") and `FinancialTransaction` records.
4. Links them via the `financial_link` junction table.

```
POST /qbo/bills_payments/<realm_id>/job/<job_code>/sync
```
Same flow for vendor bills.

```
POST /qbo/job_financials/<realm_id>/job/<job_code>/sync
```
Runs both invoice and bill syncs in sequence.

### QBO Webhook

Intuit sends entity change events to `POST /webhook/qbo`. Before processing, the handler:
1. Validates the `intuit-signature-hash` header against `QBO_CLIENT_SECRET`.
2. Parses the event type: `"com.intuit.quickbooks.accounting.<entity>.<action>"` (e.g., `...invoice.update`).
3. Routes to the appropriate handler.

| Event action | Handler | Effect |
|---|---|---|
| `create` / `update` | `process_single_entity_qbo()` | Sync entity into GQM DB |
| `delete` | `event_delete_qbo()` | Remove entity from GQM DB |
| `void` | `event_void_qbo()` | Mark record as voided |
| `email` | `event_email_qbo()` | Log notification (no data change) |

### QBO ↔ GQM Model Mapping

| QBO Entity | GQM Table | Link Field |
|---|---|---|
| Invoice | `financial_doc` | `qbo_id` = QBO Invoice.Id |
| Bill | `financial_doc` | `qbo_id` = QBO Bill.Id |
| Payment | `financial_trans` | `qbo_id` = QBO Payment.Id |
| Vendor | `supplier` | QBO Vendor.Id |

---

## Cloudinary Integration

All file storage is delegated to Cloudinary. The integration layer is in `src/cloudinary/service.py`.

### Configuration

```python
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True
)
```

### Folder Structure

Files are organized in Cloudinary by entity type and ID:

| Entity | Cloudinary Folder | Example |
|---|---|---|
| Jobs | `Jobs/{APP_TYPE}/{JOB_ID}` | `Jobs/QID/QID51894` |
| Clients | `CLI/{CLIENT_ID}` | `CLI/CLI-001` |
| Subcontractors | `SUBC/{SUBC_ID}` | `SUBC/SUBC-042` |
| Other entities | `{APP_TYPE}/{ENTITY_ID}` | `PMC/PMC-007` |

### Supported File Types

| Category | MIME types | Cloudinary resource_type |
|---|---|---|
| Images | jpeg, png, gif, webp, tiff, bmp, heic | `image` |
| Videos | mp4, mov, avi, wmv, webm, mkv, quicktime | `video` (uses `upload_large` in 6MB chunks) |
| PDF | application/pdf | `raw` |
| Office | Word, Excel, PowerPoint | `raw` |
| Archives | zip, rar, 7z | `raw` |
| Text | plain, csv | `raw` |

### Core Functions

```python
# Upload
result = upload_to_cloudinary(
    file_bytes,     # bytes
    filename,       # str — cleaned (no spaces/special chars)
    mimetype,       # str — determines resource_type
    folder,         # str — e.g., "Jobs/QID/QID51894"
    tags=""         # optional Cloudinary tags
)
# Returns: { "secure_url", "public_id", "resource_type", "format", "original_name" }

# Delete
success = delete_from_cloudinary(public_id, resource_type="image")
# Returns: bool
```

### Integration Points

| Trigger | Handler | Result |
|---|---|---|
| `POST /attachments/upload` | `upload_to_cloudinary()` | File stored in Cloudinary; `Attachments` record created |
| `DELETE /attachments/<id>` | `delete_from_cloudinary()` | File deleted from Cloudinary; record deleted from DB |
| Podio `file.change` webhook | `process_file_change_event()` | Podio file mirrored to Cloudinary |
| `POST /chat/` with file | `upload_to_cloudinary()` | Chat attachment stored |

---

## Webhook System

The app exposes four public webhook endpoints for external events:

### Podio Webhook Lifecycle

```
1. Admin calls: POST /podio/admin/create-hook/<app_type>
   → GQM registers webhook URL with Podio

2. Podio sends: POST /webhook/podio/... { "type": "hook.verify" }
   → GQM calls Podio hook activation endpoint to confirm

3. User updates item in Podio
   → Podio sends: POST /webhook/podio/... { "type": "item.update", "item_id": 12345, ... }

4. GQM processes event:
   a. parse_and_validate_webhook() — anti-loop check (rejects stale events)
   b. Fetch full item from Podio GET /item/<item_id>
   c. Map Podio fields → local model
   d. DB create/update/delete
   e. log_activity() → TLActivity record
   f. Return 200 OK to Podio
```

### Anti-Loop Protection

`mapper_aux_functions.is_recent_event()` checks the event timestamp and rejects events that are older than a threshold, preventing reprocessing loops when the GQM API itself updates Podio items (which would trigger another webhook).

### QuickBooks Webhook Lifecycle

```
1. Intuit sends change events to: POST /webhook/qbo
2. validate_qbo_signature() verifies HMAC-SHA256 signature
3. Event parsed: entity type + action extracted from type string
4. Routed to correct handler (delete, void, email, sync)
5. Return 200 OK
```

---

## Metrics & Reporting

### PDF Reports

Generated in-process using `reportlab` and `matplotlib`:

- **`POST /metrics/jobs/pdf`** — Job metrics PDF (status distribution, trends).
- **`POST /financial/metrics/pdf`** — Financial report PDF from QBO data (revenue, costs, margins).

Reports are generated synchronously per request. For large datasets this can be slow — consider caching or async generation for production scaling.

### Excel Export

- **`POST /jobs/excel/export`** — Exports filtered jobs to `.xlsx` via `openpyxl`. The request body follows the `JobExportRequest` Pydantic schema (filters: date range, status, type, etc.).

### Dashboard Endpoints

All `GET /dashboard/...` endpoints return aggregated metrics for the frontend charts. They use direct SQL aggregations via SQLAlchemy rather than loading all records.

---

## Database Migrations

Migrations are managed with **Alembic**:

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration (auto-detect model changes)
alembic revision --autogenerate -m "description"

# Check current migration status
alembic current

# Downgrade one step
alembic downgrade -1
```

Migration files live in `migrations/versions/`. The connection string is read from `DATABASE_URL` in `alembic.ini` via the env var.

---

## Deployment

### Local Development

```bash
python main.py
# Runs on http://localhost:80 in debug mode
```

### Vercel Serverless

The project includes a `vercel.json` for serverless deployment on Vercel. Each request spins up a fresh function instance, so:

- **No persistent in-memory state** between requests (except Podio token cache, which is rebuilt on cold start).
- **No background workers** — all processing is synchronous and must complete within Vercel's function timeout (~30 seconds for Hobby, 300s for Pro).
- **Long-running syncs** (Phase 1 Podio sync) may timeout; consider running them from a local machine or a dedicated worker.

### Startup Validation

On startup, `main.py` calls `validate_public_url()`, which checks that `PUBLIC_URL`:
- Is set in the environment.
- Contains `"http"`.

If validation fails, the process exits immediately. This ensures Podio webhook registration always has a valid target URL.

### Health Check

No dedicated `/health` endpoint is configured. Use `GET /auth/can?actions=job:read` with a valid token as a functional health check.
