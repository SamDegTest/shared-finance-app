# shared-finance-app Server (FastAPI)

Backend REST API per l'applicazione di finanza condivisa **shared-finance-app**.

## Requisiti
- Python >= 3.12
- Virtual environment (`venv`)

## Setup Locale

```bash
# Crea e attiva il virtual environment
python -m venv .venv
source .venv/bin/activate  # Su Linux/macOS
# oppure
.venv\Scripts\activate    # Su Windows PowerShell

# Installa le dipendenze
pip install -r requirements-dev.txt

# Avvia il server di sviluppo
uvicorn app.main:app --reload --port 8000
```

## Linting, Typing e Test

```bash
# Linting con Ruff
ruff check .

# Formattazione con Ruff
ruff format --check .  # Check
ruff format .          # Formatta automaticamente

# Type Checking statico con Mypy
mypy app/

# Esecuzione Test con Pytest
pytest
```
