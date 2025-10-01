# Deployment Architecture

## Multi-User Production Setup

### 🗄️ **Database Layer**
```
┌─────────────────────────┐    ┌─────────────────┐
│      Supabase           │    │   Redis Cloud   │
│    (PostgreSQL)         │    │   (Caching)     │
│                         │    │                 │
│ • User data             │    │ • Query cache   │
│ • Metadata              │    │ • Sessions      │
│ • Projects              │    │ • Rate limits   │
│ • Vector embeddings     │    │                 │
│ • Similarity search     │    │                 │
│   (pgvector extension)  │    │                 │
└─────────────────────────┘    └─────────────────┘
```

### 🚀 **Application Layer**
```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │   Memory    │ │   Search    │ │      Analytics          ││
│  │  Service    │ │  Service    │ │      Service            ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```