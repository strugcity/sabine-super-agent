# Product Requirements Document (PRD): Sabine

## 1. Executive Summary
Sabine is a context-aware personal assistant agent accessible via SMS (Twilio). She orchestrates the user's digital life by integrating Google Workspace (Gmail, Calendar) with a persistent "Dual-Brain" memory system (Supabase).

## 2. Core Features (V1)

### 2.1 The Interface
* **Primary Channel:** SMS (Twilio).
* **Secondary Interface:** Management Dashboard (Web).
* **Tone:** Concise, helpful, professional. No fluff.

### 2.2 The "Dual-Brain" Memory Architecture
* **Vector Store (Semantic):** Stores unstructured preferences (e.g., "The kids like pizza").
* **Knowledge Graph/SQL (Deterministic):** Stores hard rules.
    * **Custody Schedule:** A specific calendar/table defining where children are on specific dates.
    * **Trigger Rules:** Boolean logic for notifications (e.g., "If SMS from Mom -> Priority High").
* **Context Injection:** Every prompt to the LLM is pre-injected with the *current* state (Date, Location, Custody Status).

### 2.3 Integrations (MCP Layer)
* **Google Calendar:** Read events, create events, check availability.
* **Gmail:** Read threads, draft replies, send emails (via Alias `sabine@strugcity.com`).
* **Twilio:** Inbound/Outbound SMS webhook handling.

### 2.4 Management Dashboard
* **Purpose:** A "God Mode" for the user to view and edit Sabine's brain.
* **Capabilities:**
    * View/Edit "Memories" (delete incorrect facts).
    * View/Edit "Custody Schedule" (visual calendar interface).
    * Manage "Rules" (Trigger logic).

## 3. Technical Architecture

### 3.1 Stack
* **Frontend:** Next.js (Dashboard + API Routes for Twilio Webhooks).
* **Backend:** Python (FastAPI) running the Agentic Logic (LangGraph).
* **Database:** Supabase (PostgreSQL + pgvector).
* **Protocol:** Model Context Protocol (MCP) to bridge Python Agent <-> Google Tools.

#### Strategic Architecture Decision: Monolithic Brain
**Decision:** We are adopting a **"Monolithic Brain"** architecture using Supabase for both relational data (Postgres) and semantic search (pgvector).

**Rationale:** To enable unified queries and reduce synchronization drift between distinct graph and vector databases. This approach provides:
- **Unified Storage:** Single source of truth for both structured entities and unstructured memories
- **Transactional Consistency:** Atomic updates across relational and vector data
- **Simplified Operations:** Reduced infrastructure complexity and maintenance overhead
- **Query Efficiency:** Native SQL joins between entities and their vector embeddings

### 3.2 Data Flow
1.  **Input:** User sends SMS -> Twilio -> Next.js Webhook.
2.  **Routing:** Next.js pushes message to Python Agent (via Queue or HTTP).
3.  **Context Construction:** Python Agent queries Supabase (Custody/Rules) + Google (Calendar).
4.  **Inference:** LLM (Claude 3.5 Sonnet) decides action.
5.  **Action:** Agent executes Tool (Draft Email / Create Event).
6.  **Response:** Agent sends SMS back to user.

## 4. Constraints & Risks
* **Latency:** Twilio has a hard timeout. **Mitigation:** Send an immediate "Processing..." generic response for complex tasks (Async flow).
* **Auth:** Google Workspace Tokens must be refreshed automatically.
* **Safety:** The `custody_schedule` is the Source of Truth. It overrides any LLM inference.
* **Privacy:** Only authorized phone numbers (Allowlist) can interact with Sabine.

## 5. Out of Scope (V1)
* Voice/Audio calls.
* Multi-user accounts (Sabine currently serves 1 primary user + registered family members).
* Always-on autonomous monitoring (Proactive features are Cron/Trigger-based only).
