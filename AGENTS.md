# Repository Guidelines

## Agent Rules

1. Think before acting. Read existing files before writing code.
2. Be concise in output but thorough in reasoning.
3. Prefer editing over rewriting whole files.
4. Do not re-read files you have already read unless the file may have changed.
5. Test your code before declaring done.
6. No sycophantic openers or closing fluff.
7. Keep solutions simple and direct.
8. User instructions always override this file.
9. Follow the code patterns of the project.

---

## Project Overview

**GQM API** is an enterprise-grade Flask REST API for **construction and property management**. It manages jobs, clients, workforce, finances, procurement, and commissions — with deep integrations into Podio (workflow platform), QuickBooks Online (accounting), and Cloudinary (file storage).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.x |
| Web Framework | Flask 3.1.2 with Blueprints |
| ORM | SQLModel (Pydantic + SQLAlchemy hybrid) |
| Database | PostgreSQL (Neon cloud or local) |
| Migrations | Alembic |
| Auth | JWT (access 60 min / refresh 7 days) + Argon2 password hashing |
| Deployment | Vercel (serverless) |
| External APIs | Podio, QuickBooks Online, Cloudinary |

---

## Project Structure

```
gqm-api/
├── main.py                     # App factory, blueprint registration
├── requirements.txt
├── alembic.ini
├── vercel.json                 # Serverless deployment config
├── src/
│   ├── config.py               # Centralized env var loading (python-decouple)
│   ├── database/
│   │   └── db_sqlmodel.py      # Engine & session factory (get_session)
│   ├── models/                 # ~46 SQLModel files
│   │   └── link_models/        # Many-to-many junction tables
│   ├── routes/                 # ~38 Blueprint files (one per resource)
│   │   ├── Links/              # Relationship management endpoints
│   │   ├── Dashboard/          # Metrics/reporting endpoints
│   │   ├── financial_routes/   # Financial reports & documents
│   │   ├── podio_routes/       # Podio sync triggers
│   │   └── qbo_routes/         # QuickBooks endpoints
│   ├── services/               # Business logic (commissions, reports, Excel/PDF gen)
│   ├── utils/
│   │   ├── middleware/
│   │   │   ├── auth/           # jwt_handler.py, password_hashing.py
│   │   │   └── logs/           # Request logging middleware
│   │   ├── mappers/            # Bidirectional data mappers (DB <-> Podio format)
│   │   ├── validators/         # Input validation helpers
│   │   ├── pagination.py       # @paginate() decorator
│   │   └── policy_evaluator.py # IAM-style permission evaluation
│   ├── podio/                  # Podio OAuth, CRUD, sync, webhook
│   ├── quickbooks/             # QuickBooks OAuth, sync, webhook
│   ├── cloudinary/             # Image/file upload wrapper
│   └── tests/                  # Integration tests (~10 files)
└── migrations/                 # Alembic migration scripts
```

---

## Key Conventions

### Models (`src/models/`)
- Use **SQLModel** with separate schema classes: `Base`, table model, `Create`, `Update`.
- ID fields are named `ID_<EntityName>` (e.g., `ID_Client`, `ID_Job`).
- Podio item references stored as `podio_item_id`.
- Foreign keys follow `ID_<RelatedEntity>` (e.g., `ID_Community_Tracking`).
- Many-to-many relationships use explicit link models in `models/link_models/`.

### Routes (`src/routes/`)
- One **Blueprint per resource**, registered in `main.py`.
- Use the `@handle_exceptions()` decorator on all route handlers.
- Use `@paginate()` for list endpoints.
- Use `@require_permission("resource:action")` or `@require_role("member")` to protect endpoints.
- Return plain JSON responses with appropriate HTTP status codes.

### Database Sessions
- Always use context managers: `with get_session() as session:`.
- Use `joinedload()` explicitly for related data to avoid N+1 queries.
- Use `load_only()` for lightweight/table-view endpoints.
- Wrap writes in `save_with_retry()` and deletes in `delete_with_retry()`.

### Authentication & Permissions
- JWT tokens issued at `/auth/login`, refreshed at `/auth/refresh`.
- Permissions are IAM-style JSON policies stored in the DB and evaluated by `PolicyEvaluator`.
- Members and Technicians can have direct permission assignments or role-based policies.

### Integrations
- **Podio:** Two-phase sync, revision checking, webhook-driven updates. Mappers in `utils/mappers/`.
- **QuickBooks:** OAuth callback at `/callback`, tokens stored in DB, periodic sync.
- **Cloudinary:** Attachment upload via the `cloudinary/` wrapper.

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env  # Fill in required vars (see below)

# Run migrations
alembic upgrade head

# Start the server (debug mode, port 80)
python main.py
```

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | General app secret |
| `LOGIN_SECRET_KEY` | JWT access token signing key |
| `REFRESH_SECRET_KEY` | JWT refresh token signing key |
| `PODIO_CLIENT_ID` / `PODIO_CLIENT_SECRET` | Podio OAuth app credentials |
| `PUBLIC_URL` | Base URL for webhook registration |
| Cloudinary vars | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` |

> Podio requires 40+ additional app-specific vars for different job types and years (QID, PTL, PAR for 2023–2026). See `src/config.py` for the full list.

---

## Testing

Tests live in `src/tests/` and run as **integration tests against real services** (Podio, PostgreSQL). There is no mock layer. Run individual test files directly:

```bash
python -m pytest src/tests/test_<name>.py
```

---

## Domain Glossary

| Term | Meaning |
|---|---|
| Job | A construction/service project (types: QID, PTL, PAR) |
| Client | Property owner or customer |
| Member | Internal GQM staff (has login access) |
| Technician | Field technician (has login access) |
| Subcontractor | External contractor linked to jobs |
| Supplier | Vendor for materials/purchases |
| Financial Document | Invoice, receipt, or payment record |
| Purchase Order | Procurement document for a job |
| Podio | External platform used as the primary data-entry source |
| QBO | QuickBooks Online — financial accounting integration |
| Community Tracking | Parent management company for a group of clients |
