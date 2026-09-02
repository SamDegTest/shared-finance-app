# Guida al Cloud Deployment, Secret Management & Hardening

Questa guida descrive i passaggi operativi per il rilascio in produzione di **shared-finance-app** su un server cloud (AWS EC2, Hetzner, DigitalOcean, Linode o VPS generica) con certificato **SSL/TLS attivo**, container Docker multi-stage e reverse proxy Nginx blindato.

---

## 1. Architettura di Produzione

```text
[ Utente Web / Mobile ]
        │  HTTPS (Porta 443 / TLS 1.3)
        ▼
[ Nginx Reverse Proxy ]
   ├── /_next/static/ & /* ──> [ Frontend Container: Next.js 15 (Porta 3000) ]
   └── /api/* ───────────────> [ Backend Container: FastAPI Uvicorn (Porta 8000) ]
                                    │
                       ┌────────────┴────────────┐
                       ▼                         ▼
              [ PostgreSQL 16 ]            [ Redis 7 ]
             (shared_finance_prod)      (Queue & Caching)
```

---

## 2. Prerequisiti sul Server Cloud

1. Server Linux con **Ubuntu 22.04 o 24.04 LTS** (minimo 2 vCPU, 2GB RAM).
2. Record DNS di tipo **A** configurato sul tuo dominio:
   - `app.tuodominio.com` $\rightarrow$ `IP_PUBBLICO_SERVER`
3. Docker e Docker Compose installati sul server:
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

---

## 3. Configurazione dei Segreti (`.env.production`)

Clona il repository sul server e crea il file `.env.production` partendo dal template:

```bash
git clone https://github.com/SamDegTest/shared-finance-app.git
cd shared-finance-app

cp .env.production.example .env.production
```

Genera chiavi e password crittografiche robuste:

```bash
# Esegui questo comando per generare chiavi casuali a 256 bit:
openssl rand -hex 32
```

Modifica `.env.production` inserendo:
- `POSTGRES_PASSWORD`: password complessa per il DB.
- `REDIS_PASSWORD`: password complessa per Redis.
- `STORAGE_SIGNING_SECRET`: segreto a 32 caratteri per la firma HMAC delle ricevute.
- `OPENAI_API_KEY`: chiave API OpenAI per l'OCR Vision.
- `BACKEND_CORS_ORIGINS`: `["https://app.tuodominio.com"]`.

---

## 4. Generazione Certificato SSL Gratuito (Let's Encrypt / Certbot)

Prima di avviare il proxy Nginx definitivo, genera il certificato SSL tramite Certbot:

```bash
# 1. Installa certbot
sudo apt update && sudo apt install -y certbot

# 2. Genera il certificato per il tuo dominio (es. app.tuodominio.com)
sudo certbot certonly --standalone -d app.tuodominio.com -d tuodominio.com

# 3. I certificati saranno salvati in:
# /etc/letsencrypt/live/app.tuodominio.com/fullchain.pem
# /etc/letsencrypt/live/app.tuodominio.com/privkey.pem
```

Collega i certificati al volume Nginx o copiali nella directory SSL:
```bash
sudo mkdir -p /etc/nginx/ssl
sudo cp /etc/letsencrypt/live/app.tuodominio.com/fullchain.pem /etc/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/app.tuodominio.com/privkey.pem /etc/nginx/ssl/key.pem
```

---

## 5. Avvio dei Container di Produzione

Avvia l'intero stack con Docker Compose:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Esecuzione delle Migrazioni del Database:
```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### Popolamento Dati Iniziali (Opzionale):
```bash
docker compose -f docker-compose.prod.yml exec backend python -m app.db.seed
```

---

## 6. Verifica & Test di Carico (Load Testing)

Verifica che l'applicazione risponda correttamente e supporti traffico concorrente:

```bash
# Verifica Healthcheck pubblico
curl -i https://app.tuodominio.com/api/v1/health

# Esegui il Load Test con 50 connessioni simultanee:
python scripts/load_test.py --url https://app.tuodominio.com --concurrency 50 --requests 200
```

---

## 7. Hardening di Sicurezza & Best Practices

1. **Firewall UFW:** Abilita solo le porte necessarie:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```
2. **Container Non-Root:** Tutti i container applicativi (`nextjs` UID 1001 e `appuser` UID 1001) vengono eseguiti senza privilegi di root.
3. **Isolamento di Rete:** Il database PostgreSQL e Redis si trovano sulla rete interna `backend-net` e **non sono esposti su Internet**.
4. **Security Headers:** Nginx inietta automaticamente `Strict-Transport-Security` (HSTS), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` e `Permissions-Policy`.
