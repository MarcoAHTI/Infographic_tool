# Branded Infographic Orchestrator

A **multi-agent Python application** that automates the transformation of a raw
PDF document into a fully branded, high-fidelity infographic using a LangGraph
orchestration pipeline, the **Google Gemini API**, and the **Canva Connect API**.

---

## Architecture

```
PDF / Report
     │
     ▼
┌─────────────────────────────────────┐
│  Agent 1 – Content Architect        │  Uses Gemini to extract:
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
     │  Agent 3 – Brand Critic        │  Uses Gemini Vision to check:
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
│   │   ├── content_architect.py # Agent 1 – Gemini text extraction
│   │   ├── design_liaison.py    # Agent 2 – Canva API integration
│   │   └── brand_critic.py      # Agent 3 – Gemini Vision QA
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gemini_service.py    # Async Gemini API wrapper
│   │   └── canva_service.py     # Async Canva Connect API wrapper
│   └── ui/
│       ├── __init__.py
│       └── streamlit_app.py     # Streamlit dashboard
├── .env.example                 # API key placeholders
├── requirements.txt
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

### 1. Clone & install dependencies

```bash
git clone https://github.com/MarcoAHTI/Infographic_tool.git
cd Infographic_tool
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

Required variables:

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `CANVA_CLIENT_ID` | Canva Connect OAuth2 client ID |
| `CANVA_CLIENT_SECRET` | Canva Connect OAuth2 client secret |
| `CANVA_BRAND_TEMPLATE_ID` | ID of the Canva brand template to autofill |

### 3. Run the Streamlit dashboard

```bash
streamlit run app/ui/streamlit_app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Agent Details

### Agent 1 – Content Architect

- **Input:** Raw document text (extracted from PDF)
- **Model:** Gemini 2.0 Flash (text generation)
- **Output:** `InfographicContent` with `headline`, `data_points` (5 × ≤20 words),
  and `visual_metaphor`

### Agent 2 – Design Liaison

- **Input:** `InfographicContent`
- **Actions:**
  1. Authenticates with Canva via OAuth2 client-credentials
  2. Submits an autofill job using the brand template
  3. Polls until the job completes
  4. Exports the design as a PNG
- **Output:** Raw PNG image bytes

### Agent 3 – Brand Critic

- **Input:** PNG image bytes
- **Model:** Gemini 2.0 Flash (vision)
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