# 🤖 FRD AI Agent

An intelligent Python microservice that **automatically generates professional Functional Requirements Documents (FRDs)** by listening to Azure DevOps webhooks. When a Work Item is tagged as `presales`, the agent fetches all attached documents (SOW, MOM, Transcripts), processes them through a **HuggingFace LLM**, and uploads the generated FRD `.docx` back to the Work Item.

---

## 📐 Architecture

```
Azure DevOps Work Item
        │
        │  (tagged: presales)
        ▼
  Webhook Event ──► POST /api/v1/webhook/azure-devops
        │
        ▼
  WorkItemService
  ├── Detect 'presales' tag
  ├── Fetch all attachments (SOW, MOM, Transcripts)
  └── Extract text content
        │
        ▼
  FRDGeneratorService
  ├── Build document context
  ├── Call HuggingFace LLM per section
  └── Render professional .docx
        │
        ▼
  Upload FRD.docx back to Work Item
```

---

## 🚀 Quick Start

### 1. Clone & Configure

```bash
git clone <your-repo>
cd frd_agent
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run with Docker

```bash
docker-compose up --build
```

---

## ⚙️ Configuration

Edit your `.env` file:

| Variable | Description | Required |
|---|---|---|
| `ADO_ORG_URL` | Azure DevOps org URL, e.g. `https://dev.azure.com/mycompany` | ✅ |
| `ADO_PROJECT` | ADO project name | ✅ |
| `ADO_PAT` | Personal Access Token (Work Items + Attachments R/W) | ✅ |
| `HF_API_TOKEN` | HuggingFace API token (free) | ✅ |
| `HF_MODEL` | HuggingFace model ID | Optional |
| `WEBHOOK_SECRET` | Secret for validating webhook signatures | Optional |
| `LOG_LEVEL` | Logging verbosity (`INFO`, `DEBUG`) | Optional |

---

## 🔗 Setting Up the Azure DevOps Webhook

1. Go to your ADO Project → **Project Settings → Service Hooks**
2. Click **+ Create subscription** → Select **Web Hooks**
3. Choose trigger: **Work item updated**
4. Add filter: **Tags** → contains → `presales`
5. Set URL: `http://your-server:8000/api/v1/webhook/azure-devops`
6. (Optional) Set the secret to match your `WEBHOOK_SECRET` env var
7. Click **Test** then **Finish**

> 💡 For local development, use [ngrok](https://ngrok.com/) to expose your local server:
> ```bash
> ngrok http 8000
> ```

---

## 🤗 HuggingFace Free LLM Setup

1. Create a free account at [huggingface.co](https://huggingface.co)
2. Go to **Settings → Access Tokens**
3. Create a token with **Read** permissions
4. Set `HF_API_TOKEN=hf_your_token` in `.env`

### Recommended Free Models

| Model | Notes |
|---|---|
| `mistralai/Mistral-7B-Instruct-v0.3` | ✅ Default. Best quality on free tier |
| `HuggingFaceH4/zephyr-7b-beta` | Good alternative, instruction-tuned |
| `meta-llama/Llama-3.2-3B-Instruct` | Lighter, faster |

> **Note:** Free HuggingFace Inference API has rate limits and cold-start delays (~30s on first call). For production, consider [HuggingFace Inference Endpoints](https://huggingface.co/inference-endpoints) or [Together AI](https://www.together.ai/).

---

## 📄 Generated FRD Structure

The auto-generated FRD `.docx` includes:

| Section | Description |
|---|---|
| **Cover Page** | Title, Work Item ID, date, source documents |
| **Table of Contents** | Auto-updatable TOC |
| **1. Project Overview** | Background, purpose, high-level description |
| **2. Business Objectives** | Measurable goals aligned with client needs |
| **3. Scope** | In-scope and out-of-scope items |
| **4. Stakeholders** | Roles, organizations, responsibilities |
| **5. Functional Requirements** | Numbered FR-001, FR-002... with priority |
| **6. Non-Functional Requirements** | Performance, security, scalability, etc. |
| **7. Assumptions & Constraints** | Project assumptions and known constraints |
| **8. Risks & Dependencies** | Risk register with likelihood/impact/mitigation |
| **9. Glossary** | Technical terms and abbreviations |
| **10. Source Documents** | List of input documents used |

---

## 🗂️ Project Structure

```
frd_agent/
├── app/
│   ├── main.py                    # FastAPI application
│   ├── config.py                  # Settings from .env
│   ├── routes/
│   │   ├── webhook.py             # POST /api/v1/webhook/azure-devops
│   │   └── health.py              # GET /health
│   ├── services/
│   │   ├── work_item_service.py   # ADO REST API integration
│   │   └── frd_generator.py       # HuggingFace LLM + docx rendering
│   ├── models/
│   │   └── webhook_payload.py     # Pydantic models
│   └── utils/
│       ├── document_extractor.py  # .docx / .pdf / .txt extraction
│       ├── logger.py              # Logging setup
│       └── signature_validator.py # Webhook HMAC validation
├── tests/
│   └── test_frd_agent.py          # Unit tests
├── outputs/                       # Generated FRD files (auto-created)
├── .env.example                   # Environment variable template
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🧪 Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Service info |
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/webhook/azure-devops` | ADO webhook receiver |

### Interactive Docs
Visit `http://localhost:8000/docs` for Swagger UI.

---

## 🔒 Security Notes

- Always set `WEBHOOK_SECRET` in production to validate webhook signatures
- Use a restricted ADO PAT with minimum required permissions:
  - **Work Items**: Read & Write
  - **Attachments**: Read & Write
- Run behind a reverse proxy (nginx/Caddy) with TLS in production

---

## 🧩 Supported Document Types

| Extension | Parser |
|---|---|
| `.docx` | `python-docx` |
| `.pdf` | `pdfplumber` (fallback: `PyPDF2`) |
| `.txt` / `.md` | Plain text decode |

---

## 📝 License

MIT License — Free to use and modify.
