# Code Memory Backend

**An intelligent memory system for AI coding agents with semantic search and persistent storage.**

CodeMemory solves the "context amnesia" problem by providing AI clients (Claude, Cursor, ChatGPT, etc.) with persistent memory capabilities through MCP (Model Context Protocol) server implementation.

---

## Motivation

In the era of ubiquitous LLMs, a major challenge emerges: **how to store and retrieve information efficiently with semantic understanding**. CodeMemory addresses this by:

- **Eliminating Context Amnesia**: AI remembers conversations and solutions across sessions
- **Semantic Search**: Vector-based retrieval instead of rigid keyword matching
- **Analytics & Insights**: User behavior monitoring and optimization
- **Multi-client Support**: Works with various AI tools and IDEs

## High-Level Objectives

- **Persistent Memory**: Long-term structured storage (content + metadata)
- **Efficient Retrieval**: Vector search using FTS5, Faiss, Qdrant for speed and accuracy
- **Scalability**: Multi-project and multi-user support
- **Analytics & Monitoring**: User Q&A, search patterns, and system insights

---

## System Architecture

### Core Components
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   AI Clients    │───▶│   MCP Server     │───▶│   Data Layer    │
│ Cursor, Claude  │    │  (FastAPI/Go)    │    │PostgreSQL+Redis│
│ ChatGPT, etc.   │    │                  │    │   Vector Store  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   AI Services    │
                       │ Embedding + NLP  │
                       │ OpenAI/Local     │
                       └──────────────────┘
```

### Data Flows

**Save Memory Flow**
```
Client → save_memory() → MCP Server → Embedding Service → Vector Store
                                  → PostgreSQL (metadata + content)
```

**Search Memory Flow**
```
Client → search_memories() → Redis Cache → Vector Similarity Search
                                      → PostgreSQL (metadata merge)
                                      → Ranked Results
```

---

## Project Structure

```
code-memory-be/                          # Root project directory
├── .env                              # Environment variables & secrets
├── .gitignore                        # Git ignore patterns  
├── requirements.txt                  # Python dependencies
├── README.md                         # This documentation
│
├── app/                              # MAIN APPLICATION
│   ├── main.py                       # FastAPI app entry point
│   ├── api/                          # REST API endpoints & routing
│   ├── db/                           # Database session management & initialization
│   ├── models/                       # SQLAlchemy database models & tables
│   ├── services/                     # Business logic & external service integrations
│   └── vector_db/                    # Vector database operations & utilities
│
├── config/                           # Application configuration & settings
├── tests/                            # Unit & integration test suite
└── docs/                             # Project documentation & guides
```

---

## Technology Stack

| Component | Technology | Purpose | Deployment |
|-----------|------------|---------|------------|
| **Backend Framework** | FastAPI | High-performance async API | Railway/DigitalOcean |
| **Primary Database** | Supabase (PostgreSQL 15+) | User data, metadata, projects + Auth | Managed PostgreSQL service |
| **Caching** | Redis Cloud | Query caching & sessions | Managed Redis service |
| **Vector Database** | Supabase pgvector | Semantic similarity search | Built-in PostgreSQL extension |
| **Embeddings** | OpenAI API/Local | Text → Vector conversion | API service |
| **Authentication** | JWT + Supabase Auth | Secure API access | Built-in auth service |
| **Migrations** | Alembic | Database schema versioning | Self-managed |

### **Multi-User Architecture**
```
┌─────────────────┐    ┌─────────────────┐
│   Supabase      │    │   Redis Cloud   │
│  (PostgreSQL)   │    │   (Caching)     │
│                 │    │                 │
│ • User data     │    │ • Query cache   │
│ • Metadata      │    │ • Sessions      │
│ • Embeddings    │    │ • Rate limits   │
│ • Vector search │    │                 │
│ (pgvector ext)  │    │                 │
└─────────────────┘    └─────────────────┘
        │                       │
        └───────────────────────┘
                │
    ┌─────────────────────┐
    │   FastAPI Backend   │
    │   (Railway/DO)      │
    └─────────────────────┘
```