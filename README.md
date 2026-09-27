# Enterprise GenAI Document Parsing & Ingestion Platform

An enterprise-grade, asynchronous document ingestion and parsing engine engineered for production **Retrieval-Augmented Generation (RAG)** systems. Built with **Clean Architecture**, **SOLID principles**, robust **Design Patterns**, and rigorous **Data Structures & Algorithms (DSA)**.

---

## 🏛️ System Architecture

The platform follows Robert C. Martin's Clean Architecture with strict inward dependency flows, decoupling the core domain from external frameworks, databases, and third-party parsing tools.

```mermaid
graph TD
    Client["Client / LLM Pipeline / Frontend"]

    subgraph Presentation ["1. Presentation Layer (FastAPI)"]
        Middleware["RequestLoggingMiddleware\n(Correlation ID, Latency Timers, ANSI Logs)"]
        Auth["HTTP Basic Auth Guard\n(/docs, /redoc, /openapi.json)"]
        Router["Document Controller\n(app/routes/v1/document.py)"]
        ErrHandler["RFC-Compliant Exception Handlers\n(AppException -> Uniform JSON Error Envelope)"]
    end

    subgraph ServiceLayer ["2. Application / Service Layer"]
        DocService["DocumentService\n(Workflow Orchestrator & State Machine)"]
    end

    subgraph Ingestion ["3. Ingestion & Storage Subsystem"]
        Validator["6-Stage Validation Pipeline\n(Empty, Size, Ext, MIME, Magic Bytes, Structural)"]
        Storage["LocalStorage (BaseStorage)\n(uploads/{doc_id}/original.{ext})"]
    end

    subgraph Persistence ["4. Repository & Database Subsystem"]
        Repo["DocumentRepository (BaseRepository)\n(Exception Translation: SQLAlchemy -> DatabaseError)"]
        DB[(PostgreSQL Database\n'documents' Table with JSONB)]
    end

    subgraph ParsingEngine ["5. Document Parsing Engine"]
        Factory["ParserFactory (Registry Pattern)\n(O(1) Two-Tier Fallback: MIME -> Extension)"]
        Docx["DocxParser (BaseParser)\n(XML Body Interleaving, Breadcrumb Stack)"]
        PDF["PDFParser (BaseParser)\n(Table-First Masking, Font-Size Mode Profiling)"]
        Worker["asyncio.to_thread\n(Non-Blocking CPU Offloading)"]
    end

    subgraph DomainAST ["6. Domain Model & Canonical AST"]
        AST["ParsedDocument AST\n(DocumentElement Tagged Union: Title, Heading, Table, Paragraph)"]
    end

    %% Connections
    Client -->|HTTP Request| Middleware
    Middleware --> Auth
    Auth --> Router
    Router --> DocService
    Router -.-> ErrHandler

    DocService -->|Validate| Validator
    DocService -->|Stream Save| Storage
    DocService -->|Persist Metadata & AST| Repo
    Repo --> DB

    DocService -->|Get Strategy| Factory
    Factory --> Docx
    Factory --> PDF
    Docx --> Worker
    PDF --> Worker
    Worker --> AST
    AST -->|Serialize JSONB| Repo
```

---

## 🔄 Document Lifecycle State Machine (FSM)

Documents transition through a deterministic Finite State Machine persisted in PostgreSQL:

```mermaid
stateDiagram-v2
    [*] --> UPLOADED : POST /api/v1/documents (Validated & Persisted)
    
    UPLOADED --> PROCESSING : POST /api/v1/documents/{id}/parse
    FAILED --> PROCESSING : POST /api/v1/documents/{id}/parse (Retry)
    PARSED --> PROCESSING : POST /api/v1/documents/{id}/parse?force=true (Force Re-parse)
    
    state PROCESSING {
        [*] --> PathResolution
        PathResolution --> StrategyDispatch
        StrategyDispatch --> WorkerExecution
        WorkerExecution --> ASTSerialization
    }
    
    PROCESSING --> PARSED : Success (AST saved to PostgreSQL JSONB)
    PROCESSING --> FAILED : Error (Sanitized message recorded)
    
    PARSED --> PARSED : POST /parse?force=false (Idempotent: Cached AST returned)
    PARSED --> [*] : GET /api/v1/documents/{id}/parsed
```

---

## 🧩 Architectural Design Patterns Applied

| Design Pattern | Implementation | Purpose & Value |
| :--- | :--- | :--- |
| **Strategy Pattern** | `BaseParser` (`DocxParser`, `PDFParser`)<br>`BaseStorage` (`LocalStorage`) | Decouples parsing and storage logic, allowing interchangeable strategies without altering consumers. |
| **Factory & Registry** | `ParserFactory` | Manages singleton strategy instances with $\mathcal{O}(1)$ two-tier fallback lookups (MIME $\to$ Extension). |
| **Repository Pattern** | `DocumentRepository` (`BaseRepository[T]`) | Encapsulates SQLAlchemy database queries and transaction boundaries away from business logic. |
| **Chain of Responsibility** | `DocumentValidator` | 6 sequential validation gates (empty, size, extension, MIME, magic bytes, structure). |
| **Exception Translation** | Throughout Repository & Parsers | Translates low-level driver errors (`SQLAlchemyError`, `PdfminerException`) into clean domain exceptions. |
| **Monotonic Stack** | In `DocxParser` and `PDFParser` | Computes dynamic hierarchical parent breadcrumbs (`section_path`) in $\mathcal{O}(1)$ amortized time. |
| **Dual-Persistence Rollback**| `DocumentService.upload_document` | Deletes physical files on disk if PostgreSQL transaction fails, preventing orphan storage leaks. |

---

## ⚡ Data Structures & Algorithmic Complexity (DSA)

| Component | Algorithm / Data Structure | Time Complexity | Space Complexity |
| :--- | :--- | :--- | :--- |
| **Upload Validation** | Chunked Stream Buffer + Magic Byte Header | $\mathcal{O}(B)$ linear in bytes ($B \le 20\text{MB}$) | $\mathcal{O}(1)$ constant (64KB buffer) |
| **Strategy Resolution** | Two-Tier Hash Map Registry | $\mathcal{O}(1)$ lookup time | $\mathcal{O}(K)$ references ($< 2\text{KB}$) |
| **Heading Breadcrumbs** | Monotonic Decreasing Stack | $\mathcal{O}(1)$ amortized per heading | $\mathcal{O}(1)$ constant (depth $\le 6$) |
| **PDF Line Clustering** | 1D Sweep-Line on sorted coordinates | $\mathcal{O}(W \log W)$ per page | $\mathcal{O}(W)$ words per page |
| **Table-First Masking** | Axis-Aligned Point-in-Rectangle Collision | $\mathcal{O}(W \cdot T) \approx \mathcal{O}(W)$ ($T \le 5$) | $\mathcal{O}(T)$ bounding boxes |
| **Font-Size Profiling** | Frequency Hash Map (`Counter[float, int]`) | $\mathcal{O}(U)$ where $U$ is unique sizes ($U < 20$) | $\mathcal{O}(U)$ constant memory |
| **AST JSONB Storage** | PostgreSQL Binary JSON Document Store | $\mathcal{O}(1)$ primary key access | $\mathcal{O}(E)$ elements in document |

---

## 📂 Project Structure

```
├── app/
│   ├── core/                      # Core configuration, exceptions, security, and logging
│   │   ├── config.py              # Pydantic BaseSettings (.env loading, pool sizing, strict toggle)
│   │   ├── exceptions.py          # Unified domain exception hierarchy (AppException)
│   │   ├── logging.py             # Structured logging with ANSI color formatting
│   │   ├── middleware.py         # RequestLoggingMiddleware with correlation IDs
│   │   └── security.py            # HTTP Basic Auth security for documentation endpoints
│   ├── db/                        # Database connectivity & session management
│   │   ├── base.py                # SQLAlchemy 2.0 DeclarativeBase with TimestampMixin
│   │   └── session.py             # AsyncEngine with connection pooling & get_db() dependency
│   ├── models/                    # SQLAlchemy ORM Entities
│   │   └── document.py            # DocumentModel mapping to PostgreSQL 'documents' table
│   ├── parsers/                   # Document Parsing Engine
│   │   ├── base.py                # Abstract BaseParser interface (Strategy Pattern)
│   │   ├── factory.py             # ParserFactory Strategy Registry (O(1) two-tier dispatch)
│   │   └── strategies/            # Concrete parsing implementations
│   │       ├── docx.py            # DocxParser: Interleaved XML reading order & table extraction
│   │       └── pdf.py             # PDFParser: Table masking, font profiling, fault isolation
│   ├── repositories/              # Data Access Layer (Repository Pattern)
│   │   ├── base.py                # Generic BaseRepository[T] interface
│   │   └── document_repository.py # DocumentRepository with Exception Translation
│   ├── routes/                    # Presentation / HTTP Controller Layer
│   │   └── v1/
│   │       └── document.py        # Thin controllers for upload, parse, and retrieval
│   ├── schemas/                   # Pydantic v2 DTOs and Canonical AST Models
│   │   ├── document.py            # DocumentResponse & DocumentStatus enum
│   │   └── parsing.py             # Canonical AST (DocumentElement Discriminated Union, ParsedDocument)
│   ├── services/                  # Application Service Layer (Business Orchestration)
│   │   └── document_service.py    # DocumentService: Dual-persistence, FSM, and parsing pipeline
│   ├── storage/                   # File Storage Abstraction
│   │   ├── base.py                # BaseStorage abstract contract
│   │   └── local.py               # LocalStorage: Chunked stream writing & portable paths
│   ├── validators/                # 6-Stage Validation Pipeline
│   │   └── document_validator.py  # Empty, size, extension, MIME, magic bytes, structure checks
│   └── main.py                    # FastAPI application initialization & exception handlers
├── migrations/                    # Alembic Database Migrations
│   ├── env.py                     # Async migration configuration with safe URL interpolation
│   └── versions/                  # Revision versions (documents table & JSONB AST schema)
├── requirements.txt               # Pinned production dependencies
└── alembic.ini                    # Alembic configuration
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python**: 3.12 or higher
- **PostgreSQL**: 14 or higher

### 2. Environment Configuration
Create a `.env` file in the root directory:

```env
# Application Settings
ENVIRONMENT=development
PROJECT_NAME="Enterprise GenAI Document Parsing Platform"
LOG_LEVEL=INFO

# PostgreSQL Database Configuration
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/document_parsing_db
DB_ECHO=false
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Storage Settings
UPLOAD_DIR=uploads
MAX_FILE_SIZE_BYTES=20971520   # 20MB limit

# Parser Engine Configuration
PARSER_STRICT_MODE=false       # false = fault-tolerant isolation; true = abort on corrupt page

# Protected Documentation Credentials (HTTP Basic Auth)
DOCS_USERNAME=admin
DOCS_PASSWORD=adminpassword
```

### 3. Installation
```bash
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 4. Database Migrations
Alembic migrations run automatically on application startup. To apply them manually:
```bash
alembic upgrade head
```

### 5. Running the Application
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs) *(Protected: `admin` / `adminpassword`)*
- **ReDoc UI**: [http://localhost:8000/redoc](http://localhost:8000/redoc) *(Protected)*
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 📡 REST API Reference

### 1. Upload Document
```http
POST /api/v1/documents
Content-Type: multipart/form-data
```
**Description**: Runs the 6-stage validation pipeline, stores the file on disk, and records initial metadata in PostgreSQL with status `uploaded`.

#### Response (`201 Created`):
```json
{
  "document_id": "3ff1695d-8d1c-4da9-9b37-ebca57dd00ec",
  "filename": "annual_financial_report.pdf",
  "extension": "pdf",
  "mime_type": "application/pdf",
  "size_bytes": 1048576,
  "status": "uploaded",
  "created_at": "2026-09-28T01:30:00Z",
  "message": "Document uploaded, validated, and persisted successfully"
}
```

---

### 2. Get Document Metadata
```http
GET /api/v1/documents/{document_id}
```
**Description**: Fetches current lifecycle status and ingestion metadata.

#### Response (`200 OK`):
```json
{
  "document_id": "3ff1695d-8d1c-4da9-9b37-ebca57dd00ec",
  "filename": "annual_financial_report.pdf",
  "extension": "pdf",
  "mime_type": "application/pdf",
  "size_bytes": 1048576,
  "status": "parsed",
  "created_at": "2026-09-28T01:30:00Z",
  "message": "Document metadata retrieved successfully"
}
```

---

### 3. Parse Document
```http
POST /api/v1/documents/{document_id}/parse?force=false
```
**Description**: Executes the format-specific parsing strategy, updates status to `parsed`, and stores the canonical AST into PostgreSQL JSONB.
- `force=false` *(default)*: Idempotent call; returns the cached database AST instantly without burning CPU.
- `force=true`: Re-runs the parsing pipeline.

#### Response (`200 OK`):
```json
{
  "document_id": "3ff1695d-8d1c-4da9-9b37-ebca57dd00ec",
  "filename": "annual_financial_report.pdf",
  "total_pages": 2,
  "word_count": 57,
  "char_count": 453,
  "parsed_at": "2026-09-28T01:32:18Z",
  "warnings": [],
  "elements": [
    {
      "element_id": "elem_0000",
      "type": "title",
      "reading_order": 0,
      "page_number": 1,
      "section_path": [],
      "text": "Enterprise Architecture Blueprint",
      "level": 1
    },
    {
      "element_id": "elem_0003",
      "type": "table",
      "reading_order": 3,
      "page_number": 1,
      "section_path": ["Executive Overview"],
      "headers": ["Service Name", "Version", "Status"],
      "rows": [
        ["Parser Worker", "v2.3.0", "Active"],
        ["Vector Indexer", "v1.8.4", "Active"]
      ],
      "markdown": "| Service Name | Version | Status |\n| --- | --- | --- |\n| Parser Worker | v2.3.0 | Active |\n| Vector Indexer | v1.8.4 | Active |"
    }
  ]
}
```

---

### 4. Retrieve Canonical AST
```http
GET /api/v1/documents/{document_id}/parsed
```
**Description**: Retrieves the pre-parsed canonical AST directly from PostgreSQL JSONB in $\mathcal{O}(1)$ time.

#### Response Codes:
- `200 OK`: Canonical AST returned.
- `400 Bad Request`: Document has not been parsed yet (`DOCUMENT_NOT_PARSED`).
- `404 Not Found`: Document ID does not exist (`DOCUMENT_NOT_FOUND`).
- `409 Conflict`: Document is currently being parsed (`DOCUMENT_ALREADY_PROCESSING`).
- `422 Unprocessable Entity`: Document parsing previously failed (`PARSING_FAILED_CORRUPTED`).

---

## 🛡️ Error Envelope Specification

Every API error follows a sanitized, RFC-compliant format. Internal server paths, database credentials, and Python stack traces are never exposed:

```json
{
  "error_code": "DOCUMENT_ALREADY_PROCESSING",
  "message": "Document is currently being parsed. Please wait for completion.",
  "details": {
    "document_id": "3ff1695d-8d1c-4da9-9b37-ebca57dd00ec",
    "status": "processing"
  }
}
```

---

## 🧪 Automated Testing

All test suites verify live operations against PostgreSQL and the ASGI transport:

```bash
# Verify ParserFactory O(1) resolution and strategy singletons
python scratch/test_parser_factory.py

# Verify PDFParser table-first masking, breadcrumbs, and page isolation
python scratch/test_pdf_parser.py

# Verify DocumentService state machine & PostgreSQL JSONB persistence
python scratch/test_document_service_parsing.py

# Verify end-to-end REST API HTTP endpoints
python scratch/test_api_parsing_endpoints.py
```

---

## 🗺️ Roadmap & Next Phases

- [x] **Phase 1: Ingestion & 6-Stage Validation Pipeline**
- [x] **Phase 1.5: PostgreSQL Metadata & Dual-Persistence Rollback**
- [x] **Phase 2: Document Parsing Engine & Canonical AST**
  - [x] Canonical AST Schemas (Pydantic v2 Discriminated Unions)
  - [x] Concrete Strategies (`DocxParser`, `PDFParser`)
  - [x] `ParserFactory` with $\mathcal{O}(1)$ Two-Tier Fallback Dispatch
  - [x] State Machine (`UPLOADED` $\to$ `PROCESSING` $\to$ `PARSED` / `FAILED`)
  - [x] Database-Native JSONB Persistence
  - [x] REST API Routes (`POST /parse`, `GET /parsed`)
- [ ] **Phase 3: Semantic Chunking Engine (RAG Preparation)**
  - [ ] Chunking Schemas (`Chunk`, `ChunkMetadata`, parent section breadcrumbs)
  - [ ] Structure-Aware Section Chunking
  - [ ] Table-Preserving Markdown Chunking
  - [ ] Sliding-Window Token Limit Management
- [ ] **Phase 4: Vector Store & Retrieval Pipeline**
