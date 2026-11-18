# Personal Finance & Budget Advisor Agent

A full-stack personal finance assistant that analyzes spending, converts currencies, categorizes expenses, provides budgeting guidance, and supports a conversational workflow.

## What this project includes

- FastAPI backend with PostgreSQL persistence when `DATABASE_URL` is configured, and SQLite for local development otherwise
- Exchange-rate and geolocation integrations for budgeting context
- LangChain + Gemini-ready AI integration
- Langfuse-ready observability hooks
- Auth0 login with JWT validation and per-user finance-data isolation
- Auth0 Management API-backed admin console for user status, passwords, and historical-data permissions
- React + Vite frontend with goals tracker, CSV import, and live budget analytics

## Project structure

- `backend/app/main.py` — FastAPI app entry point and protected routes
- `backend/app/database.py` — PostgreSQL/SQLite connections and schema
- `backend/app/services/storage.py` — profile, goals, and transactions persistence
- `backend/app/services/finance_agent.py` — financial reasoning and session memory
- `backend/app/services/api_clients.py` — exchange-rate and geolocation API functions
- `backend/app/services/auth.py` — optional Auth0 JWT validation
- `src/App.jsx` — React finance dashboard and advisor interface
- `src/styles.css` — styling for the dashboard
- `.env.example` — environment variable reference

## Quick start

1. Create a virtual environment
   ```bash
   python -m venv .venv
   ```
   Activate it in PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   Or in Command Prompt:
   ```cmd
   .venv\Scripts\activate.bat
   ```
   On macOS/Linux, use `source .venv/bin/activate`.

2. Install Python dependencies
   ```bash
   pip install -r requirements.txt
   ```

3. Install frontend dependencies
   ```bash
   npm install
   ```

4. Configure environment variables
   ```bash
   cp .env.example .env
   ```
   Fill the values as needed. Gemini and Langfuse are optional; the app still works without them. For the Google Gemini API, set `GEMINI_API_KEY` and leave `GEMINI_BASE_URL` empty. A custom base URL must implement the native Gemini API (the OpenAI-compatible endpoint is not supported by this client).

   Set `DATABASE_URL` to use PostgreSQL locally or in deployed environments (for
   example, `postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require`). Leave it
   unset to use SQLite for local development. Keep credentials in environment
   settings and URL-encode special characters in the username or password. The app
   creates PostgreSQL tables automatically, but does not copy existing SQLite
   records into PostgreSQL.

   For admin user management, configure `AUTH0_MANAGEMENT_CLIENT_ID` and
   `AUTH0_MANAGEMENT_CLIENT_SECRET` for a dedicated Auth0 machine-to-machine
   application authorized for the Auth0 Management API with `read:users`,
   `update:users`, `create:users`, and `delete:users` scopes. Keep these credentials
   on the backend only. Admin access
   requires an `admin` value in the authenticated user's `roles` claim; namespaced
   claims ending in `/roles` are also supported.

   In Auth0, authorize the M2M application under **Applications → APIs → Auth0
   Management API** and grant all four scopes. Ensure the client ID, secret, and
   `AUTH0_DOMAIN` all belong to the same tenant, then restart the backend after
   changing `.env`. An `access_denied` response usually means the M2M app is not
   authorized for the Management API; `invalid_client` points to a credential or
   tenant mismatch.

5. Start the backend API
   ```bash
   python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. Start the React UI
   ```bash
   npm run dev -- --host 0.0.0.0
   ```

7. Open the UI
   Visit http://localhost:5173/

The React app proxies `/api` requests to the backend at `http://localhost:8000`.

## Tests and coverage

Install the Python development dependencies with `pip install -r requirements-dev.txt`.

Run the frontend tests and JavaScript coverage report:

```bash
npm test
npm run test:coverage
```

Run the backend tests and Python coverage report:

```bash
python -m coverage run -m pytest
python -m coverage report
python -m coverage html
python -c "import pathlib, webbrowser; webbrowser.open(pathlib.Path('htmlcov/index.html').resolve().as_uri())"
```

The HTML Python report is written to `htmlcov/index.html` and opened in your default external browser. It includes fully covered files, functions, and classes.

## Example API calls

### Health check
```bash
curl http://localhost:8000/api/health
```

### Currency conversion
```bash
curl -X POST http://localhost:8000/api/currency/convert \
  -H "Content-Type: application/json" \
  -d '{"amount": 100, "from_currency": "USD", "to_currency": "INR"}'
```

The dashboard also provides a live currency converter and accepts foreign-currency manual expenses. Manual expenses are kept in their original currency and display a budget-currency equivalent. If an exchange rate cannot be fetched, the dashboard reports the error instead of adding a misleading converted amount.

### Budget analysis
Finance endpoints require an Auth0 access token for the configured API audience.
```bash
curl -X POST http://localhost:8000/api/finance/analyze \
  -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "income": 5000,
    "currency": "USD",
    "location": "New York",
    "session_id": "demo-session",
    "transactions": [
      {"description": "Rent", "amount": 1500, "currency": "USD"},
      {"description": "Groceries", "amount": 420, "currency": "USD"},
      {"description": "Dining out", "amount": 250, "currency": "USD"}
    ],
    "goal_name": "Emergency Fund",
    "goal_amount": 10000,
    "goal_saved": 5200
  }'
```

### Chat assistant
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer <access-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Can you suggest a better monthly budget for my spending?",
    "session_id": "demo-session",
    "income": 5000,
    "transactions": [
      {"description": "Rent", "amount": 1500, "currency": "USD"},
      {"description": "Groceries", "amount": 420, "currency": "USD"}
    ]
  }'
```

## Architecture diagram

```mermaid
flowchart LR
    Browser[React + Vite Dashboard] -->|REST API| Backend[FastAPI Backend]
    Backend --> Agent[Finance Agent]
    Agent --> Rules[Transaction Categorization + Budget Logic]
    Agent --> APIs[Exchange Rate / Geolocation APIs]
    Agent --> DB[(PostgreSQL or local SQLite)]
    Agent --> Langfuse[Langfuse Observability]
    Agent --> Gemini[Gemini / LLM]
```

## Database schema diagram

```mermaid
erDiagram
    PROFILES ||--o{ TRANSACTIONS : stores
    PROFILES ||--o{ GOALS : tracks

    PROFILES {
        INTEGER id PK
        TEXT session_id UK
        REAL income
        TEXT currency
        TEXT location
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    TRANSACTIONS {
        INTEGER id PK
        TEXT session_id FK
        TEXT description
        REAL amount
        TEXT currency
        TEXT category
        TIMESTAMP created_at
    }

    GOALS {
        INTEGER id PK
        TEXT session_id FK
        TEXT name
        REAL target_amount
        REAL saved_amount
        TIMESTAMP created_at
    }
```

## Notes on integrations

- ExchangeRate-API: when `EXCHANGE_RATE_API_KEY` is configured, fetches rates from `https://v6.exchangerate-api.com/v6/{API_KEY}/latest/{BASE}` and reads its `conversion_rates` response. Without a key, uses the provider's free no-key endpoint at `https://open.er-api.com/v6/latest/{BASE}`.
- `POST /api/currency/convert` provides the dashboard converter with the source amount, target amount, and applied rate. It does not require authentication because it handles only a currency pair and amount; failed provider requests return an error instead of a same-value fallback.
- Open-Meteo geocoding: searches manually entered place names for regional context. Its public geocoding endpoint does not reverse-geocode device coordinates, so the dashboard uses browser GPS (with permission) and OpenStreetMap Nominatim to resolve the current city/region.
- OpenStreetMap Nominatim: reverse-geocodes device GPS coordinates through the backend. The dashboard's date/time clock uses the browser's local timezone.
- Gemini: if configured, the agent uses LangChain with Gemini for enriched budget advice.
- Langfuse: traces agent events when `LANGFUSE_*` keys are configured.
- Auth0: set `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, and `AUTH0_AUDIENCE` in your environment. Protected finance endpoints fail closed if Auth0 is not configured. The frontend uses Authorization Code Flow with PKCE and keeps the access token in memory.

To use the API-key endpoint, add `EXCHANGE_RATE_API_KEY` to `.env`. Do not commit the key to source control.

## Auth0 setup

1. Create an Auth0 **Single Page Application** and an Auth0 API. Configure the API to sign access tokens with RS256.
2. Set the values in `.env`:
   ```bash
   AUTH0_DOMAIN=your-tenant.us.auth0.com
   AUTH0_CLIENT_ID=your-client-id
   AUTH0_AUDIENCE=https://api.your-finance-app.com
   ```
3. In the SPA settings, add the origin you use to **Allowed Callback URLs**, **Allowed Logout URLs**, and **Allowed Web Origins**. For local Vite development use `http://localhost:5173`; if opening the backend-served page, use `http://localhost:8000`.
4. In the API settings, use the same identifier as `AUTH0_AUDIENCE`.
5. Start the frontend and backend. The dashboard stays hidden until Auth0 sign-in succeeds and the backend validates the access token.

The backend uses the verified Auth0 `sub` claim as the owner key for finance records. It ignores client-supplied session IDs for writes and only allows a user to read their own session. Auth0 roles are separate from this ownership boundary; add role checks only for actions that should differ by role. Do not use a client-supplied user ID, email, or role as the record owner.

## Features included

- Conversational finance assistant
- Monthly income and transaction analysis
- Category spending breakdowns
- Budget recommendations and overspending alerts
- Savings goal tracking and progress bars
- CSV expense import
- Dashboard reminders for uploaded transactions dated within the next seven days
- INR-based demo budget set to ₹50,000 with India flag branding
- Ten selectable dashboard themes, saved in the browser
- Device-GPS location lookup (browser permission required), per-user city override, and live local date/time clock
- Location queries use the [Open-Meteo Geocoding API](https://geocoding-api.open-meteo.com/v1/search) without an API key to resolve city and regional context; it does not provide cost-of-living prices
- Manual expense entry by description, amount, and category
- Local session persistence across refreshes
- Auth0-ready security model

## Architecture summary

The app follows a layered architecture:

Client UI -> FastAPI routes -> Finance agent -> Transaction analysis + external APIs + PostgreSQL or local SQLite persistence -> Insights and recommendations

This keeps the local implementation simple while still modeling the production flow of a real finance advisor platform.
