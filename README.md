# LegalKare – AI‑Powered Legal Practice Suite

A **full‑stack Flask application** that brings together secure document management, AI‑assisted legal research, lawyer‑client collaboration tools, and omni‑channel access (web + WhatsApp). This README covers **the entire code‑base**, not just the WhatsApp add‑on.

> **TL;DR** ▪️ Python | Flask | MongoDB | AWS (S3 + SES + Cognito) | FAISS | Sentence‑Transformers | OpenAI | Twilio (Video + WhatsApp) | Stripe

---

## 1  Core Features

| # | Domain | What it Does |
|---|--------|--------------|
| 1 | **Auth & Profiles** | AWS Cognito sign‑up / login, role‑based sessions, profile pictures on S3 |
| 2 | **Document Vault** | Upload PDF/TXT → store in S3 + Mongo ➜ extract text ➜ chunk ➜ embed ➜ FAISS per‑user index |
| 3 | **Semantic Search & Chat** | Retrieve relevant chunks → prompt OpenAI → streaming chat answers scoped to each user’s doc |
| 4 | **Summariser** | One‑shot PDF/TXT summarisation with custom prompt |
| 5 | **Appointments** | Clients book / lawyers accept | email notifications via AWS SES |
| 6 | **Video Consultations** | Twilio Access Tokens + Video Grant per room |
| 7 | **Teams & Notifications** | Private document‑sharing groups + invite / join / leave flows |
| 8 | **Prompt Library** | Add / edit / promote reusable AI prompts (admin‑guarded) |
| 9 | **Reviews & FAQs** | Simple CRUD endpoints for social proof & help‑desk |
|10 | **Lawyer Recommender** | Sentence‑Transformer embeddings of lawyer bios → global FAISS index |
|11 | **WhatsApp Assistant** | Twilio webhook + Stripe Checkout for pay‑per‑feature UX |

---

## 2  Folder Layout (minimal)

```text
├── flask_app.py          # Monolithic Flask entry‑point (includes blueprints)
├── source/               # Helper modules: extraction, embeddings, chat, …
├── requirements.txt      # Pinned Python deps
├── scripts/              # One‑off utilities (build_lawyer_index.py, etc.)
├── .env.example          # Copy → .env and fill secrets
└── README.md             # You’re here
```

---

## 3  Environment Variables (`.env`)

Below list is exhaustive; unset values disable the corresponding feature.

```ini
######################  Flask  ######################
SECRET_KEY_FLASK="super‑secret"
FLASK_ENV=development            # or production

######################  Mongo  ######################
MONGO_CLIENT="mongodb+srv://user:pass@cluster/legalaid"

######################  AWS  ######################
REGION="ap-south-1"
S3_ACCESS_KEY_ID="AKIA…"
S3_ACCESS_SECRET_TOKEN="…"
S3_BUCKET_NAME="legalkare‑bucket"
AWS_SES_REGION="ap-south-1"
AWS_SES_ACCESS_KEY_ID="…"
AWS_SES_SECRET_ACCESS_KEY="…"

# (Optionally) store path to local FAISS default index
EMBEDDING_MODEL_NAME="sentence-transformers/all-mpnet-base-v2"

######################  Cognito  ######################
CLIENT_ID="…"
CLIENT_SECRET="…"

######################  OpenAI  ######################
OPENAI_API_KEY="…"

######################  Twilio  ######################
TWILIO_ACCOUNT_SID="AC…"
TWILIO_API_KEY_SID="SK…"
TWILIO_API_KEY_SECRET="…"

######################  Stripe  ######################
STRIPE_SECRET_KEY="sk_live_…"
PAYMENT_SUCCESS_URL="https://your‑domain.com/whatsapp/payment_success"
PAYMENT_CANCEL_URL="https://your‑domain.com/payment_cancel"
```

> **Security**: never commit `.env`; use AWS Secrets Manager / HashiCorp Vault in prod.

---

## 4  Quick Start (Local)

```bash
# 1  Clone & cd
$ git clone git@github.com:yourorg/legalkare.git && cd legalkare

# 2  Python venv
$ python -m venv .venv && source .venv/bin/activate

# 3  Dependencies
$ pip install -r requirements.txt   # installs Flask, boto3, faiss‑cpu, sentence‑transformers, openai, twilio, stripe …

# 4  Configure
$ cp .env.example .env  # then edit

# 5  Run
$ python flask_app.py   # default http://localhost:5002
```

Need a public URL? `ngrok http 5002` ➜ copy HTTPS URL to Twilio **and** Stripe success page.

---

## 5  Developer Workflows

### Upload & Chat
1. `POST / upload` with JWT‑session cookie → S3 + embeddings.
2. UI hits `GET / my_documents` → lists docs.
3. Chat panel calls `POST / chat` with `query` + `document_name`.

### Booking Flow
1. Client calls `POST /profile/book_appointment`.
2. Lawyer accepts via dashboard or WhatsApp.
3. Status emails fire via AWS SES.

### Video Call
* `POST / initiate_video_call` returns Twilio token + room. Client & lawyer join via Twilio JS SDK.

### WhatsApp Pay‑Per‑Feature (high‑level)
* User: “Book appointment” → bot responds with Stripe link.
* After payment success webhook, server flips `pending_purchase → paid`, then prompts user to supply date/time.

---

## 6  Database Schema (Mongo Collections)

| Collection | Purpose |
|------------|---------|
| `users` | core profiles, role, AWS Cognito username mapping |
| `user_documents` | S3 key, privacy, folders, upload date |
| `annotations` | per‑user note + highlight positions |
| `legal_documents` | extracted metadata for public corpora |
| `summary` | cached LLM summaries |
| `appointments` | booking lifecycle |
| `consultations` | Twilio room mapping |
| `teams` | { team_id, members[] } |
| `notifications` | invites & system alerts |
| `prompts` | reusable AI prompt templates |
| `faqs` / `reviews` | support & social proof |

---

## 7  Building the Global Lawyer Index

```bash
$ python scripts/build_lawyer_index.py  # reads all lawyers from Mongo, encodes bios, writes lawyer_index.faiss + metadata
```
Run this whenever a lawyer updates profile fields that influence search.

---

## 8  Running Tests

```bash

```

CI suggestion: GitHub Actions → run `pytest`, `black --check`, `isort --check`.

---

## 9  Deployment Checklist

1. **Gunicorn** behind **NGINX** (HTTPS).
2. `SESSION_TYPE=redis` for multi‑instance consistency.
3. S3 Lifecycle rules → archive old uploads.
4. VPC private sub‑nets for Mongo Atlas peering.
5. Stripe + Twilio webhooks validated.

---

## 10  Troubleshooting

| Symptom | Fix |
|---------|-----|
| *FAISS index dimension mismatch* | Delete old `.faiss`, rebuild with new model version |
| *Cognito NotAuthorizedException* | Ensure `CLIENT_SECRET` matches the App Client’s secret; regenerate env var |
| *SES Email throttled* | Verify domain & move AWS SES out of sandbox |
| *Twilio 11200 HTTP Error* | Ngrok tunnel expired; update webhook URL |

---

## 11  License

MIT © 2025 LegalKare – Built with ❤️ in Hyderabad

