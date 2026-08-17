# 🏛️ Oracle Primavera Unifier RAG Dashboard & Conversational AI Chatbot

An enterprise-grade FastAPI portal and Conversational AI RAG Chatbot for Oracle Primavera Unifier REST APIs v1, containerized and ready for **Dokploy** deployment.

---

## 🌟 Key Features

- **🔑 Unifier REST API Authentication**: Secure Bearer Token authentication supporting Test, Production, or custom environments.
- **📁 Active Projects & Shells**: Query, search, filter, and export active project shells (`/admin/projectshell?Status=Active`).
- **🏢 Company Business Processes**: Query company-level processes like `Vendor` records (`/bp/records/`).
- **🏗️ Project Business Processes**: Query project-specific processes like `Contract`, `Submittal`, `RFI`, and `Change Orders` (`/bp/records/{project_number}`).
- **📎 Attachment Downloader**: Download document attachments directly from records (`/bp/record/file`).
- **👥 User Administration**: Query Unifier system users (`/admin/user/get`).
- **🤖 Agentic RAG AI Chatbot**:
  - Live agentic tools (`LangGraph` + `LangChain`) querying Unifier APIs on-demand with caching support.
  - Supports both **Groq** (`llama-3.3-70b-versatile`) for ultra-fast inference and **OpenAI** (`gpt-3.5-turbo` / `gpt-4o`).
  - Persistent SQLite chat history with multi-conversation management.
  - Modern web SPA frontend interface with conversational AI chat.

---

## 🚀 Dokploy Deployment Guide

This project is fully containerized and optimized for **Dokploy** deployment.

### Option 1: Dokploy Compose Deployment (Recommended)

1. Create a new **Compose Service** in Dokploy.
2. Connect your Git Repository (`https://github.com/hypertonny/conversational-rag-chatbot.git`).
3. Set the Environment Variables in Dokploy:
   ```env
   UNIFIER_BEARER_TOKEN=your_bearer_token_here
   UNIFIER_BASE_URL=https://us2.unifier.oraclecloud.com/consulting/test/ws/rest/service/v1
   GROQ_API_KEY=gsk_your_groq_key_here
   OPENAI_API_KEY=sk-your_openai_key_here
   LLM_PROVIDER=groq
   ```
4. Click **Deploy**. Dokploy will automatically build and launch your application on port `8501`.

### Option 2: Dokploy Dockerfile Deployment

1. Create a new **Application** in Dokploy.
2. Select **Dockerfile** as the build type.
3. Set Port to `8501`.
4. Deploy!

---

## 💻 Local Development Setup

```bash
# 1. Clone repository
git clone https://github.com/hypertonny/conversational-rag-chatbot.git
cd conversational-rag-chatbot

# 2. Create virtual environment using uv or venv
uv venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
uv pip install -r requirements.txt

# 4. Launch FastAPI server
uvicorn server:app --reload --port 8501
```

---

## 🐳 Run via Docker Locally

```bash
docker build -t unifier-dashboard .
docker run -p 8501:8501 --env-file .env unifier-dashboard
```

---

## 🛠️ Tech Stack

- **Backend**: FastAPI & Uvicorn
- **Frontend SPA**: HTML5, CSS3, Vanilla JS
- **API Client**: Python `requests`
- **Database / Cache**: SQLite (`chats.db`) & ChromaDB
- **LLM Orchestration**: LangChain & LangGraph
- **LLM Providers**: Groq (`ChatGroq`) & OpenAI (`ChatOpenAI`)
- **Containerization**: Docker, Docker Compose, Dokploy

