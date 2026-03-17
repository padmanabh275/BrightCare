## IdeaGen Pro – AI Business Idea Generator

IdeaGen Pro is a small SaaS-style demo that uses a **Next.js** frontend, **Clerk** for auth and subscriptions, and a **FastAPI** backend that streams AI‑generated business ideas for the AI‑agent economy.

The `/product` page is gated behind a premium subscription and renders ideas as rich Markdown using server‑sent events.

---

### Tech stack

- **Frontend**: Next.js (Pages Router), Tailwind‑style utility classes
- **Auth & billing**: Clerk (`SignInButton`, `UserButton`, `Protect`, `PricingTable`)
- **Backend API**: FastAPI (`api/index.py`) secured with Clerk JWTs
- **AI provider**: `openai` Python SDK with streaming chat completions

---

### Key flows

- **Landing page (`/`)**
  - Marketing hero for **IdeaGen Pro**
  - Preview of the premium subscription pricing
  - Sign‑in with Clerk and CTA to open the app at `/product`

- **App page (`/product`)**
  - Wrapped in `Protect` with `plan="premium_subscription"` so only subscribed users can access the generator
  - Non‑subscribed users see a `PricingTable` to upgrade
  - Subscribed users see the live **Business Idea Generator** that renders AI output as formatted Markdown

- **Backend (`/api`)**
  - Implemented in `api/index.py` using FastAPI
  - Secured with Clerk via `fastapi-clerk-auth`
  - Streams AI content over **Server‑Sent Events** which the frontend consumes with `@microsoft/fetch-event-source`

---

### Prerequisites

- Node.js and npm (or yarn/pnpm/bun) for the Next.js app
- Python 3.9+ for the FastAPI backend
- A **Clerk** project (publishable key, secret key, JWKS URL)
- An **OpenAI API key** (compatible with the `openai` Python SDK)

---

### Environment variables

Create a `.env.local` (not committed to version control) and define at least:

- **`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`** – your Clerk publishable key
- **`CLERK_SECRET_KEY`** – your Clerk secret key
- **`CLERK_JWKS_URL`** – Clerk JWKS URL for the FastAPI auth guard
- **`OPENAI_API_KEY`** – OpenAI API key used by the backend

Do not commit real secrets; use local dev keys or environment‑specific values in your deployment platform.

---

### Install dependencies

From the `saas` directory:

```bash
# JavaScript dependencies for Next.js
npm install

# Python dependencies for FastAPI backend
pip install -r requirements.txt
```

If you use a virtual environment or Conda, activate it before installing Python dependencies.

---

### Running locally

In one terminal, start the Next.js dev server:

```bash
npm run dev
```

By default this serves the frontend at `http://localhost:3000`.

In another terminal, run the FastAPI backend (adjust the command/port to your setup or process manager):

```bash
uvicorn api.index:app --reload --port 8000
```

Make sure your deployment or local reverse proxy routes the frontend `/api` calls to the FastAPI app.

Then open:

- `http://localhost:3000` for the marketing page
- `http://localhost:3000/product` to use the generator after signing in and subscribing

---

### Deployment notes

- Frontend can be deployed on platforms that support Next.js (e.g. Vercel).
- Backend FastAPI app can be hosted separately (e.g. on a container service) and exposed behind HTTPS.
- Configure your production environment variables (Clerk, OpenAI, API base URLs) in your hosting provider.
