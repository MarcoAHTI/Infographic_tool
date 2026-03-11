# Branded Infographic Orchestrator

A **multi-agent Python application** that automates the transformation of a raw
PDF document into a fully branded, high-fidelity infographic using a LangGraph
orchestration pipeline, the **Mistral AI API**, and the **Canva Connect API**.

---

## Architecture

```
PDF / Report
     │
     ▼
┌─────────────────────────────────────┐
│  Agent 1 – Content Architect        │  Uses Mistral to extract:
│  app/agents/content_architect.py    │  • headline
│                                     │  • data_points (5 insights)
│                                     │  • visual_metaphor
└────────────────┬────────────────────┘
                 │  InfographicContent (Pydantic)
                 │
         ┌───────▼───────┐
         │ Manual Override│  Streamlit UI lets the user edit
         │  (optional)   │  the JSON before it reaches Canva
         └───────┬───────┘
                 │
     ┌───────────▼────────────────────┐
     │  Agent 2 – Design Liaison      │  Calls Canva Connect API:
     │  app/agents/design_liaison.py  │  • Autofill brand template
     │                                │  • Enforce brand colours & fonts
     │                                │  • Export PNG
     └───────────┬────────────────────┘
                 │  image bytes
                 │
     ┌───────────▼────────────────────┐
     │  Agent 3 – Brand Critic        │  Uses Mistral Vision to check:
     │  app/agents/brand_critic.py    │  • Logo visible?
     │                                │  • Colours correct?
     │                                │  • Text overlap?
     └───────────┬────────────────────┘
                 │  QAResult
                 │
         ┌───────▼───────┐
         │  QA passed?   │──── YES ──► Final infographic PNG
         └───────┬───────┘
                 │ NO (retry up to MAX_DESIGN_RETRIES)
                 └──────────► Agent 2 again
```

---

## Repository Structure

```
Infographic_tool/
├── app/
│   ├── __init__.py
│   ├── brand_config.py          # Brand colours, fonts, logo placement
│   ├── models.py                # Pydantic schemas (InfographicContent, QAResult)
│   ├── orchestrator.py          # LangGraph pipeline definition
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── content_architect.py # Agent 1 – Mistral text extraction
│   │   ├── design_liaison.py    # Agent 2 – Canva API integration
│   │   └── brand_critic.py      # Agent 3 – Mistral Vision QA
│   ├── services/
│   │   ├── __init__.py
│   │   ├── mistral_service.py   # Async Mistral API wrapper
│   │   └── canva_service.py     # Async Canva Connect API wrapper
│   └── ui/
│       ├── __init__.py
│       └── streamlit_app.py     # Streamlit dashboard
├── .env.example                 # API key placeholders
├── pyproject.toml               # uv project configuration
├── requirements.txt             # (legacy, use uv instead)
└── README.md
```

---

## Brand Settings (`app/brand_config.py`)

| Setting | Value |
|---------|-------|
| Primary colour | `#336A88` |
| Secondary colour | `#009DDC` |
| Accent colour | `#EE3124` |
| Heading font | Ahti Sans |
| Body font | Ahti Sans |
| Logo placement | bottom-right |
| Max QA retries | 3 |

---

## Quick Start

### 1. Install dependencies with uv

First, [install uv](https://docs.astral.sh/uv/getting-started/installation/) if you haven't already.

```bash
git clone https://github.com/MarcoAHTI/Infographic_tool.git
cd Infographic_tool
uv sync
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

Required variables:

| Variable | Description |
|----------|-------------|
| `MISTRAL_API_KEY` | Mistral AI API key (get free at [console.mistral.ai](https://console.mistral.ai)) |
| `CANVA_CLIENT_ID` | Canva Connect OAuth2 client ID |
| `CANVA_CLIENT_SECRET` | Canva Connect OAuth2 client secret |
| `CANVA_REDIRECT_URI` | Redirect URL configured in Canva Developer Portal |
| `CANVA_SCOPES` | Space-separated Canva scopes your integration needs |
| `CANVA_REFRESH_TOKEN` | Refresh token from one-time OAuth authorization |
| `CANVA_BRAND_TEMPLATE_ID` | ID of the Canva brand template to autofill |

OAuth note:
When the app starts, use "Step 0 – Connect Canva (OAuth)" to generate the authorization URL and complete login once.
After successful callback, save `CANVA_REFRESH_TOKEN` to `.env` so future requests can refresh access tokens automatically.

Hosted redirect note:
If Canva requires a real hosted redirect URI, deploy [deploy/canva_auth/index.html](deploy/canva_auth/index.html) to your website as `/canva_auth/`.
That page forwards Canva's `code` and `state` query params to your local Streamlit app at `http://127.0.0.1:8501/`, and also provides a copy/paste fallback.

### 3. Run the Streamlit dashboard

**Option A: Using `uv run` (recommended for uv-managed projects)**

```bash
# Add uv to your PATH (if not already in PATH)
$env:Path = "$env:Path;" + [System.IO.Path]::Combine($env:HOME, ".local", "bin")

# Run with uv (handles the virtualenv automatically)
uv run streamlit run app/ui/streamlit_app.py
```

**Option B: Activate the venv first, then run directly**

```powershell
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
streamlit run app/ui/streamlit_app.py

# macOS / Linux
source .venv/bin/activate
streamlit run app/ui/streamlit_app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### 4. Deploy the hosted Canva callback page

If your Canva integration uses a hosted redirect URI like `https://healthinsights.ahti.nl/canva_auth`, deploy the file at [deploy/canva_auth/index.html](deploy/canva_auth/index.html) to that route on your website.

For a static site deployment, the target route should resolve to:

```text
https://healthinsights.ahti.nl/canva_auth/
```

The page will:
- receive Canva's redirect on your domain
- automatically forward the callback to your local Streamlit app
- offer a copy button if automatic forwarding fails

This repo also includes a dedicated GitHub Actions workflow at [.github/workflows/deploy-canva-callback.yml](.github/workflows/deploy-canva-callback.yml).
It deploys only the callback page via SFTP when `deploy/canva_auth/**` changes or when triggered manually.

Required GitHub configuration:
- Secret `FTP_USERNAME`
- Secret `FTP_SERVER`
- Secret `FTP_PASSWORD`

The workflow deploys to `/apps/canva_auth/` on `main` and `/apps/canva_auth_dev/` on `main_dev`.

---

## Agent Details

### Agent 1 – Content Architect

- **Input:** Raw document text (extracted from PDF)
- **Model:** Mistral Large (text generation)
- **Output:** `InfographicContent` with `headline`, `data_points` (5 × ≤20 words),
  and `visual_metaphor`

### Agent 2 – Design Liaison

- **Input:** `InfographicContent`
- **Actions:**
        1. Authenticates with Canva via OAuth2 (Authorization Code + PKCE tokens)
  2. Submits an autofill job using the brand template
  3. Polls until the job completes
  4. Exports the design as a PNG
- **Output:** Raw PNG image bytes

### Agent 3 – Brand Critic

- **Input:** PNG image bytes
- **Model:** Mistral Pixtral (vision)
- **Checks:** logo visible, colours correct, no text overlap
- **Output:** `QAResult` with `passed` flag and `feedback` text

---

## Streamlit UI Features

1. **Upload** a PDF or plain-text report.
2. **Extract** structured content via the Content Architect agent.
3. **Manual Override** – edit the JSON before it reaches Canva.
4. **Generate** – watch the agent thought-process log in real time, then see
   the QA result and the final infographic.
5. **Download** the branded PNG.

---

## Development

```bash
# Lint (if ruff is installed)
ruff check app/

# Format (if black is installed)
black app/
```

---

## Licence

MIT