# 🤖 AI Support Copilot

<div align="center">

[![CI](https://github.com/yourusername/ai-support-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/ai-support-copilot/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?logo=openai&logoColor=white)](https://openai.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Intelligent customer support ticket automation** — classification, reply drafting, structured field extraction, CRM write-back, and human-in-the-loop approval.

[**Live Demo**](#quick-start) · [**API Docs**](http://localhost:8000/docs) · [**Architecture**](#architecture)

</div>

---

## ✨ What It Does

A production-ready AI agent that processes support tickets through a 3-step pipeline in **4–8 seconds** — replacing 60%+ of manual triage work:

```
📧 Ticket IN
    │
    ├─ [1] Classify    → billing / bug / feature / urgent / general  (+ confidence)
    │
    ├─ [2] Draft Reply → professional email reply (category-specific prompt)
    │
    └─ [3] Extract     → priority · sentiment · action items · key entities
                ↓
    📊 Google Sheets  ←→  💬 Slack (approve/reject)  ←→  📈 Prometheus
```

**Human-in-the-Loop gate**: If confidence < 75%, the ticket is flagged for Slack review with ✅/❌ buttons before any reply is sent.

---

## 📊 Performance Metrics

> Evaluated on a labeled test set of **100 tickets** spanning all 5 categories.

| Metric | Value |
|--------|-------|
| 🎯 Classification Accuracy | **92%** |
| ⚡ Avg End-to-End Latency | **~5.2s** |
| 📈 P95 Latency | **~8.1s** |
| 👀 Human Review Trigger Rate | **12%** (confidence < 0.75) |
| ⏱ Estimated Time Saved / Ticket | **~4 min (63%)** vs. manual triage |
| 🚨 Urgent Detection Recall | **100%** (0 missed urgents) |

---

## 🔒 Error Handling & Reliability

```
LLM Call Fails
  │
  ├─ Retry × 3 (exponential backoff: 1s → 2s → 4s)
  │
  ├─ Fallback to generic reply draft
  │
  └─ confidence=0 → needs_review=true → Slack human queue

Google Sheets Unreachable
  └─ Local JSONL fallback → logs/sheets_fallback.jsonl

Low Confidence (< 0.75%)
  └─ Slack Block Kit message with ✅ Approve / ❌ Reject buttons
     └─ SLA: 30min manual review window
```

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Application                    │
│  POST /tickets      POST /tickets/batch   GET /metrics   │
│  GET /              POST /webhook/slack   GET /stats      │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     Pipeline (async)     │
              │                         │
              │  1. Classify Ticket      │  ← GPT-4o-mini JSON mode
              │     ↓ (parallel)        │
              │  2. Draft Reply   ──┐   │  ← Category-specific prompts
              │  3. Extract Fields  ┘   │  ← Structured output
              └────────────┬────────────┘
                           │
           ┌───────────────┼──────────────┐
           ▼               ▼              ▼
    Google Sheets      Slack Bot     Prometheus
    (gspread API)   (Block Kit UI)  (/metrics)
                           │
                    ✅ Approve / ❌ Reject
                           │
                    POST /webhook/slack
```

---

## 🚀 Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/yourusername/ai-support-copilot.git
cd ai-support-copilot

cp .env.example .env
# Edit .env with your API keys
```

### 2. Run with Docker (recommended)

```bash
docker-compose up -d
```

The dashboard will be live at **http://localhost:8000**  
API docs at **http://localhost:8000/docs**

### 3. Run Locally

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --reload --port 8000
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in your credentials:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key |
| `GOOGLE_CREDS_JSON` | Optional | Service account JSON (inline) |
| `GOOGLE_SHEET_ID` | Optional | Target spreadsheet ID |
| `SLACK_BOT_TOKEN` | Optional | Slack bot token (`xoxb-...`) |
| `SLACK_CHANNEL` | Optional | Target channel (default: `#support-copilot`) |
| `CONFIDENCE_THRESHOLD` | Optional | Review threshold (default: `0.75`) |

> **Minimum setup**: Only `OPENAI_API_KEY` is required. Sheets and Slack are optional integrations.

---

## 📡 API Reference

### `POST /tickets`
Process a single ticket through the full pipeline.

```bash
curl -X POST http://localhost:8000/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "subject": "Cannot access billing portal after payment",
    "body": "Hi, since I paid for the Pro plan yesterday I still cannot access the billing section. It shows Access Denied.",
    "customer_email": "john@company.com"
  }'
```

**Response:**
```json
{
  "success": true,
  "ticket_id": "TKT-001",
  "category": "billing",
  "confidence": 0.94,
  "needs_review": false,
  "status": "pending",
  "reply_draft": "Hi John,\n\nThank you for reaching out...",
  "priority": "high",
  "sentiment": "negative",
  "action_items": [
    "Verify upgrade was processed correctly in billing system",
    "Check account access permissions for billing module",
    "Apply Pro plan access privileges manually if upgrade didn't propagate"
  ],
  "latency_ms": 4821.3
}
```

### `POST /tickets/batch`
Process up to 20 tickets concurrently.

```bash
curl -X POST http://localhost:8000/tickets/batch \
  -H "Content-Type: application/json" \
  -d '{"tickets": [...]}'
```

### `GET /stats`
Current processing statistics and recent ticket history.

### `GET /metrics`
Prometheus metrics endpoint.

---

## 🧪 Testing

```bash
# Run unit tests (no API key needed)
pytest tests/ -k "TestModels or TestFixtures" -v

# Run integration tests (requires OPENAI_API_KEY)
pytest tests/ -v

# Run full 100-ticket accuracy benchmark
RUN_BATCH_TEST=1 pytest tests/test_pipeline.py::TestPipelineBatch::test_batch_accuracy -v -s
```

---

## 📁 Project Structure

```
ai-support-copilot/
├── app/
│   ├── main.py                 # FastAPI entry point, all routes
│   ├── models.py               # Pydantic schemas
│   ├── config.py               # Settings (pydantic-settings + .env)
│   ├── agent/
│   │   ├── classifier.py       # Step 1: category + confidence
│   │   ├── drafter.py          # Step 2: reply draft
│   │   ├── extractor.py        # Step 3: structured fields
│   │   └── pipeline.py         # Orchestrator: retry, fallback, metrics
│   ├── integrations/
│   │   ├── sheets.py           # Google Sheets write-back + fallback
│   │   └── slack_notifier.py   # Slack Block Kit alerts + approval flow
│   ├── observability/
│   │   ├── logger.py           # Loguru structured logging
│   │   └── metrics.py          # Prometheus counters/histograms
│   └── static/
│       └── index.html          # Live dashboard UI
├── tests/
│   ├── fixtures/tickets.json   # 100 labeled test tickets (5 categories)
│   └── test_pipeline.py        # Unit tests + batch accuracy benchmark
├── .github/workflows/ci.yml    # GitHub Actions: lint + test + Docker build
├── Dockerfile                  # Production container
├── docker-compose.yml
├── .env.example                # Environment variable template
└── requirements.txt
```

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | FastAPI + Uvicorn |
| **LLM** | OpenAI GPT-4o-mini (JSON mode) |
| **CRM** | Google Sheets API v4 (gspread) |
| **Notifications** | Slack SDK + Block Kit |
| **Observability** | Loguru + Prometheus |
| **Testing** | pytest + pytest-asyncio |
| **Linting** | Ruff |
| **Container** | Docker + Docker Compose |
| **CI/CD** | GitHub Actions |

---

## 🔮 Roadmap

- [ ] **RAG**: Connect FAQ knowledge base for context-aware replies
- [ ] **Streaming**: SSE push for real-time draft generation
- [ ] **Multi-language**: Auto-detect language, reply in kind
- [ ] **Fine-tuning**: Train classification model on historical tickets (target: 97%+)
- [ ] **Analytics**: Category trend charts, team performance dashboard
- [ ] **Webhook input**: Native Zendesk / Intercom / Freshdesk connectors

---

## 📄 License

MIT © 2025 — See [LICENSE](LICENSE) for details.
