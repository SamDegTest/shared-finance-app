# shared-finance-app

> PWA di finanza condivisa per coppie con zero-friction receipt capture (OCR multimodale) e riconciliazione contabile trasparente.

---

## Architettura del Progetto

Il repository è strutturato come monorepo modulare:

- **[`client/`](file:///c:/Users/Samuele/Documents/Progetti/shared-finance-app/client)**: Frontend Next.js 15 (App Router, Server Components, TypeScript Strict, Tailwind CSS v4, PWA).
- **[`server/`](file:///c:/Users/Samuele/Documents/Progetti/shared-finance-app/server)**: Backend REST API FastAPI (Python 3.12+, Pydantic v2, Ruff, Mypy, Pytest).
- **[`.github/workflows/`](file:///c:/Users/Samuele/Documents/Progetti/shared-finance-app/.github/workflows)**: Pipeline CI/CD GitHub Actions con job paralleli per frontend e backend.

---

## Avvio Rapido in Locale

### 1. Frontend (`client`)
```bash
cd client
npm install
npm run dev
```
L'app sarà accessibile su `http://localhost:3000`.

**Comandi di verifica frontend:**
```bash
npm run lint          # ESLint
npm run typecheck     # TypeScript check (tsc --noEmit)
npm run format:check  # Prettier check
npm run build         # Next.js production build
```

---

### 2. Backend (`server`)
```bash
cd server
python -m venv .venv

# Attivazione Virtualenv
# Su Windows:
.venv\Scripts\activate
# Su Linux/macOS:
source .venv/bin/activate

# Installazione dipendenze
pip install -r requirements-dev.txt

# Avvio server di sviluppo
uvicorn app.main:app --reload --port 8000
```
La documentazione OpenAPI Swagger sarà accessibile su `http://localhost:8000/docs`.

**Comandi di verifica backend:**
```bash
ruff check .           # Linter
ruff format --check .  # Formattazione
mypy app/              # Type check statico
pytest                 # Unit & Integration tests
```

---

## Convenzioni di Sviluppo

- **Git Branching:** `feature/shared-finance-app-<ID>-<slug-task>` (es. `feature/shared-finance-app-1-repo-ci-setup`).
- **Commit Messages:** Convenzione [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`, `chore:`, `test:`).
- **CI/CD:** Ogni Pull Request verso `main` o `develop` deve superare entrambi i job paralleli della pipeline CI.
