# 📊 FinSight: Personal Financial Intelligence (RAG)

FinSight is a high-performance financial intelligence platform that transforms messy bank statements into actionable behavioral insights. Built with a **Retrieval-Augmented Generation (RAG)** architecture using **Supabase pgvector**, it provides a "Chat GPT" interface for your personal finances.

![FinSight Dashboard](https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&q=80&w=1000)

## 🚀 Key Features

*   **🧠 RAG Architecture**: Native semantic search powered by **Supabase pgvector**. The AI agent semantically retrieves relevant transaction context to answer complex natural language queries with high precision.
*   **⚡ Smart Ingestion**: Upload bank statement PDFs. The system automatically extracts merchant details, amounts, and dates using **Gemini 1.5 Flash** for intelligent pattern refinement.
*   **🤖 AI Finance Assistant**: Ask anything: *"How much did I spend on food in March?"*, *"Compare my weekend vs weekday spending patterns"*, or *"Analyze my impulse purchases."*
*   **📈 Executive Reports**: Generates deep-dive financial health reports, identifying behavioral trends, spending signals, and personalized recommendations.
*   **🔒 Secure & Private**: Integrated with **Supabase Auth** and Row-Level Security (RLS) to ensure your data stays private and isolated.

## 🛠 Tech Stack

*   **Frontend**: React, Vite, Custom Modern CSS (Glassmorphism), Recharts.
*   **Backend**: FastAPI (Python), Google Gemini AI (Flash 2.5), Celery, Redis.
*   **Database**: Supabase (PostgreSQL + **pgvector**).
*   **DevOps**: Docker, Docker Compose, Render (Production).

---

## 🚦 Local Setup

### **1. Clone & Install**
```bash
git clone https://github.com/asmitk991/FinSight.git
cd FinSight
```

### **2. Environment Configuration**
Create a `.env` file in the `backend/` directory:
```env
GEMINI_API_KEY=your_gemini_key
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
REDIS_URL=redis://localhost:6379/0
```

### **3. Database Setup (Supabase)**
Run the following SQL in your Supabase SQL Editor to enable vector search:
```sql
create extension if not exists vector;
alter table transactions add column embedding vector(768);

-- Create the RAG search function
create or replace function match_transactions (
  query_embedding vector(768),
  match_threshold float,
  match_count int,
  p_user_id uuid
)
returns setof transactions
language sql
as $$
  select * from transactions
  where user_id = p_user_id and embedding <=> query_embedding < 1 - match_threshold
  order by embedding <=> query_embedding limit match_count;
$$;
```

### **4. Launch Services**
You can run via Docker Compose or manually:

**Docker Compose:**
```bash
docker-compose up --build
```

**Manual (FastAPI + Worker + Frontend):**
1. **Backend:** `cd backend && uvicorn app.main:app --reload`
2. **Worker:** `cd backend && celery -A app.celery_app worker --loglevel=info`
3. **Frontend:** `cd frontend && npm install && npm run dev`

---

## 📂 Project Structure

```text
├── backend/
│   ├── app/              # FastAPI Application Logic & RAG Services
│   ├── tests/            # Test scripts for RAG and API
│   ├── Dockerfile        # Production API image
│   └── requirements.txt  # Python Dependencies
├── frontend/
│   ├── src/              # React components & Modern Dashboard
│   └── Dockerfile        # Production Frontend image
└── docker-compose.yml    # Full-stack orchestration
```

## 🔒 Privacy & Security

*   **User Isolation**: Every user has a unique UUID; RLS policies prevent unauthorized data access.
*   **Secret Management**: Sensitive keys are handled via environment variables and are never committed to version control.
*   **RAG Precision**: Only relevant transaction snippets are shared with the LLM via semantic retrieval.

Made with ❤️ by [Asmit Kumar](https://github.com/asmitk991)
