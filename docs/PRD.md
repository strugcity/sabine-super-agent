# Product Requirements Document (PRD)

## Sabine Personal Assistant

**Version:** 1.0
**Last Updated:** January 27, 2026
**Status:** In Development
**Owner:** Product Team

---

## Executive Summary

Sabine is an AI-powered personal assistant designed to manage family logistics, complex multi-person coordination, and deep contextual information through natural communication channels (SMS, email, and voice). Unlike traditional assistants that require apps or specific devices, Sabine is device-agnostic and deeply context-aware, understanding family situations like custody schedules, individual preferences, and historical context to provide intelligent, proactive assistance.

The product addresses the critical gap in existing AI assistants: they lack persistent memory, family context awareness, and seamless integration across communication channels. Sabine solves this by combining a dual-brain memory system (semantic + deterministic) with deep context injection and multi-channel accessibility.

---

## Problem Statement

### Current Challenges

1. **Fragmented Family Coordination**: Families managing shared custody, multiple schedules, and complex logistics lack a single, intelligent coordination system that understands their unique context.

2. **Device Dependency**: Existing AI assistants (Siri, Alexa, Google Assistant) require specific devices or apps, creating barriers to access and limiting usefulness across different situations.

3. **Context Loss**: Traditional assistants have no memory of previous interactions, family rules, or important contextual information, requiring users to re-explain their situation repeatedly.

4. **Communication Channel Silos**: Important information is scattered across SMS, email, voice calls, and apps with no unified intelligent layer connecting them.

5. **Lack of Proactive Intelligence**: Most assistants are reactive—they wait for commands rather than proactively managing tasks based on context, rules, and schedules.

### Impact

- Parents waste 5-10 hours per week on coordination tasks
- Missed appointments and scheduling conflicts cause stress
- Important context and preferences are forgotten or lost
- Family members lack a shared source of truth for logistics

---

## Target Users

### Primary Persona: "Coordinating Parent"

**Profile:**
- Age: 30-45
- Role: Parent managing shared custody or complex family logistics
- Tech savviness: Moderate (comfortable with SMS and email, but not necessarily apps)
- Pain points: Overwhelmed by coordination tasks, needs reliable assistance without adding more apps

**Goals:**
- Quickly check custody schedules and availability
- Coordinate with co-parent on logistics
- Manage appointments, pickups, and activities
- Have a reliable assistant that remembers family context
- Access help via whatever device/channel is available

**User Story:**
> "As a parent managing shared custody, I need an assistant that understands our custody schedule and can help me coordinate with my co-parent, so I can quickly make decisions without constantly checking calendars or forgetting important details."

### Secondary Persona: "Busy Professional"

**Profile:**
- Age: 25-55
- Role: Professional managing complex work and personal tasks
- Tech savviness: High
- Pain points: Too many tools, context switching overhead, need for intelligent automation

**Goals:**
- Delegate task management to AI assistant
- Get intelligent email triage and responses
- Access information hands-free via SMS or voice
- Automate routine coordination tasks

---

## User Stories and Use Cases

### Core User Stories

#### US-1: Custody Schedule Management
**As a** parent with shared custody
**I want** to quickly ask about custody schedules
**So that** I can plan activities and coordinate with my co-parent

**Acceptance Criteria:**
- User can ask "Who has the kids this weekend?" via SMS
- System retrieves accurate custody information from knowledge graph
- Response includes relevant dates, parent assignments, and any special notes
- System remembers custody rules (e.g., alternating weekends, holiday schedules)

#### US-2: SMS-Based Communication
**As a** user on the go
**I want** to interact with my assistant via SMS
**So that** I can get help without needing a specific app or device

**Acceptance Criteria:**
- User can send SMS to designated Twilio number
- System validates sender is authorized
- Response is sent back via SMS within 10 seconds
- Conversation context is maintained across multiple messages

#### US-3: Email Intelligence
**As a** user receiving many emails
**I want** the assistant to read and respond to emails on my behalf
**So that** I can focus on high-priority communications

**Acceptance Criteria:**
- System monitors Gmail inbox via webhook
- AI reads incoming emails and determines if response is needed
- Drafts intelligent responses based on email content and user context
- Prevents loops by detecting auto-replies
- Only responds to authorized senders

#### US-4: Deep Context Awareness
**As a** user with established preferences and rules
**I want** the assistant to remember my context
**So that** I don't have to re-explain my situation every time

**Acceptance Criteria:**
- System loads user rules, preferences, and past memories before responding
- Responses are personalized based on user context
- Assistant proactively applies rules (e.g., "Never schedule meetings before 9am")
- Memory system stores important facts for future reference

#### US-5: Tool Integration
**As a** user managing multiple services
**I want** the assistant to interact with my Google Workspace
**So that** I can delegate tasks like calendar management and document retrieval

**Acceptance Criteria:**
- System connects to Gmail, Calendar, Drive, Docs, and Sheets
- User can ask assistant to search emails, create events, or retrieve documents
- All operations respect user permissions and authorization
- Errors are handled gracefully with clear feedback

### Extended Use Cases

#### UC-1: Morning Coordination
**Scenario:** Parent wakes up and needs to confirm day's schedule

**Flow:**
1. User texts: "What's on my schedule today?"
2. Sabine loads user context (timezone, calendar access, custody schedule)
3. Retrieves calendar events from Google Calendar
4. Checks custody schedule for child-related logistics
5. Responds with comprehensive summary:
   - Work meetings
   - Child pickup times
   - Custody status
   - Weather if relevant

**Success Criteria:** Response time < 10 seconds, includes all relevant information

#### UC-2: Last-Minute Schedule Change
**Scenario:** Co-parent emails about custody schedule swap

**Flow:**
1. Email arrives in Gmail inbox
2. Gmail push notification triggers Sabine webhook
3. Sabine reads email, extracts schedule change request
4. Checks current custody schedule for conflicts
5. Drafts response confirming or suggesting alternative
6. (Optional) Updates custody schedule if confirmed
7. Notifies primary user via SMS about change

**Success Criteria:** Response drafted within 2 minutes, accurate schedule conflict detection

#### UC-3: Hands-Free Information Access
**Scenario:** User driving and needs quick information

**Flow:**
1. User calls Sabine's Twilio number
2. Voice menu prompts user to speak query
3. Whisper transcribes speech to text
4. Sabine processes query with full context
5. Response is read back via text-to-speech
6. User can follow up with additional questions

**Success Criteria:** Natural conversation flow, accurate transcription, < 5 seconds per response

---

## Features and Requirements

### Functional Requirements

#### FR-1: Multi-Channel Communication
- **FR-1.1**: Support SMS via Twilio integration
- **FR-1.2**: Support email via Gmail API
- **FR-1.3**: Support voice calls via Twilio Voice (roadmap)
- **FR-1.4**: Maintain conversation context across channels
- **FR-1.5**: Route responses back through originating channel

#### FR-2: Deep Context System
- **FR-2.1**: Load user rules, preferences, and config before each query
- **FR-2.2**: Inject custody schedule data when relevant
- **FR-2.3**: Retrieve recent memories from vector store
- **FR-2.4**: Apply user-defined triggers and actions automatically
- **FR-2.5**: Support user-specific timezone handling

#### FR-3: Dual-Brain Memory
- **FR-3.1**: Vector store for semantic/fuzzy memory (pgvector)
- **FR-3.2**: Knowledge graph for deterministic logic (SQL)
- **FR-3.3**: Importance scoring for memory prioritization
- **FR-3.4**: Automatic memory persistence after conversations
- **FR-3.5**: Memory retrieval with similarity search

#### FR-4: Authorization and Security
- **FR-4.1**: Phone number validation for SMS (ADMIN_PHONE whitelist)
- **FR-4.2**: Email sender authorization (GMAIL_AUTHORIZED_EMAILS)
- **FR-4.3**: API key authentication for all endpoints
- **FR-4.4**: Twilio signature validation
- **FR-4.5**: Secure credential management via environment variables

#### FR-5: Tool Integration
- **FR-5.1**: Unified tool registry combining local and remote tools
- **FR-5.2**: Model Context Protocol (MCP) client for external integrations
- **FR-5.3**: Google Workspace integration (Gmail, Calendar, Drive, Docs, Sheets)
- **FR-5.4**: Custom local skills (weather, custody management)
- **FR-5.5**: Dynamic tool discovery and loading

#### FR-6: Agent Intelligence
- **FR-6.1**: LangGraph ReAct agent orchestration
- **FR-6.2**: Claude 3.5 Sonnet as primary reasoning model
- **FR-6.3**: Prompt caching for cost optimization (90% reduction)
- **FR-6.4**: Conversation history management
- **FR-6.5**: Error handling and graceful degradation

#### FR-7: Data Management
- **FR-7.1**: User account management
- **FR-7.2**: Multi-identity support (SMS, email, Slack)
- **FR-7.3**: Conversation state persistence
- **FR-7.4**: Audit trail for all interactions
- **FR-7.5**: Custody schedule CRUD operations

### Non-Functional Requirements

#### NFR-1: Performance
- **NFR-1.1**: SMS response time < 10 seconds (p95)
- **NFR-1.2**: Email response generation < 2 minutes
- **NFR-1.3**: API endpoint response < 5 seconds for cached queries
- **NFR-1.4**: System startup time < 30 seconds
- **NFR-1.5**: Support for concurrent users (target: 100 simultaneous conversations)

#### NFR-2: Reliability
- **NFR-2.1**: System uptime 99.5% (excluding scheduled maintenance)
- **NFR-2.2**: Automatic retry logic for external service failures
- **NFR-2.3**: Graceful degradation when MCP servers unavailable
- **NFR-2.4**: Data persistence guarantees (no conversation loss)
- **NFR-2.5**: Idempotent operations to prevent duplicate actions

#### NFR-3: Scalability
- **NFR-3.1**: Horizontal scaling for Python API service
- **NFR-3.2**: Database connection pooling
- **NFR-3.3**: Efficient vector similarity search (< 100ms for 10k memories)
- **NFR-3.4**: Rate limiting per user (10 requests/minute)
- **NFR-3.5**: Background job processing for non-urgent tasks

#### NFR-4: Security
- **NFR-4.1**: All API communications over HTTPS
- **NFR-4.2**: Secrets stored in environment variables (never in code)
- **NFR-4.3**: Constant-time API key comparison
- **NFR-4.4**: SQL injection prevention via parameterized queries
- **NFR-4.5**: Rate limiting to prevent abuse

#### NFR-5: Maintainability
- **NFR-5.1**: Comprehensive logging (INFO level minimum)
- **NFR-5.2**: Health check endpoints for monitoring
- **NFR-5.3**: Modular architecture for easy feature addition
- **NFR-5.4**: Clear separation of concerns (Next.js frontend, Python backend)
- **NFR-5.5**: Automated deployment pipelines

#### NFR-6: Cost Efficiency
- **NFR-6.1**: Prompt caching to reduce LLM API costs by 90%
- **NFR-6.2**: Efficient database queries with proper indexing
- **NFR-6.3**: Smart memory retrieval (only load recent/relevant memories)
- **NFR-6.4**: Connection reuse for external services
- **NFR-6.5**: Target: < $0.05 per conversation

---

## Success Metrics

### Primary KPIs

1. **User Engagement**
   - Daily active users (DAU)
   - Messages per user per day
   - Conversation completion rate (user gets satisfactory answer)
   - Channel distribution (SMS vs email vs voice)

2. **System Performance**
   - Average response time (target: < 10s for SMS)
   - p95 response time
   - System uptime (target: 99.5%)
   - Cache hit rate (target: > 80%)

3. **Intelligence Quality**
   - Context awareness score (manual evaluation)
   - Task completion rate (e.g., calendar events created successfully)
   - Error rate (failed tool calls, incorrect information)
   - User satisfaction score (1-5 rating after interaction)

4. **Cost Efficiency**
   - Cost per conversation
   - Token usage per conversation
   - Cache savings percentage
   - Infrastructure cost per user

### Secondary Metrics

- Memory accuracy (fact retention over time)
- Tool usage distribution
- Authorization rejection rate
- Conversation length (turns per session)
- Feature adoption rate (% users using each tool)

---

## Out of Scope (V1)

The following features are explicitly NOT included in the initial release:

1. **Multi-User Collaboration**: Family member accounts with shared context (planned for V2)
2. **Voice Calls**: Full Twilio Voice integration with Whisper (in progress, not V1)
3. **Mobile App**: Native iOS/Android apps (may never build—prioritizing device-agnostic approach)
4. **Payment Processing**: Billing, subscriptions, payment management
5. **Third-Party Integrations**: Non-Google services (Slack, Microsoft 365, etc.) beyond MCP
6. **Advanced Analytics**: Dashboard with conversation analytics and insights
7. **Custom Triggers**: User-defined automation workflows (basic rule system only in V1)
8. **Group Conversations**: Multi-party SMS or email threads
9. **File Attachments**: Sending/receiving files via SMS or email (beyond text)
10. **Internationalization**: Non-English language support

---

## Dependencies

### External Services

1. **Anthropic Claude API** (Critical)
   - Dependency: Primary AI reasoning engine
   - Risk: API downtime or rate limiting
   - Mitigation: Implement retry logic, fallback to cached responses when possible

2. **Twilio** (Critical for SMS)
   - Dependency: SMS sending/receiving
   - Risk: Service outage or delivery delays
   - Mitigation: Status monitoring, graceful error messages to users

3. **Google Workspace APIs** (High)
   - Dependency: Gmail, Calendar, Drive integration
   - Risk: OAuth token expiration, API changes
   - Mitigation: Token refresh logic, graceful degradation if unavailable

4. **Supabase** (Critical)
   - Dependency: Database hosting, pgvector support
   - Risk: Downtime, connection limits
   - Mitigation: Connection pooling, read replicas for scaling

5. **MCP Servers** (Medium)
   - Dependency: External tool integrations
   - Risk: Custom server downtime
   - Mitigation: Graceful degradation, continue with local tools only

### Internal Components

1. **Next.js Frontend** (Critical)
   - Provides webhook endpoints for Twilio and Gmail
   - Risk: Vercel deployment issues
   - Mitigation: Health checks, automated rollback

2. **Python FastAPI Backend** (Critical)
   - Core agent logic and orchestration
   - Risk: Memory leaks, slow performance
   - Mitigation: Regular restarts, monitoring, load testing

3. **LangGraph** (High)
   - Agent orchestration framework
   - Risk: Breaking changes in updates
   - Mitigation: Pin specific versions, test before upgrading

---

## Technical Constraints

1. **Response Time**: SMS responses must be < 30 seconds (Twilio timeout)
2. **Message Length**: SMS limited to 1600 characters (Twilio segment limit)
3. **Email Rate Limits**: Gmail API has per-day quotas
4. **Token Limits**: Claude API has context window limits (200k tokens)
5. **Database Size**: pgvector performance degrades with > 1M vectors without optimization

---

## Release Planning

### Phase 1: MVP (Current)
**Status:** 80% Complete
**Timeline:** Completed Q4 2025

**Deliverables:**
- ✅ SMS integration (Twilio)
- ✅ Basic agent with Claude 3.5 Sonnet
- ✅ Deep context injection
- ✅ Unified tool registry
- ✅ Dual-brain memory system
- ✅ Google Workspace integration (MCP)
- ✅ Phone number authorization
- ✅ Email handler (Gmail)
- ⏳ Voice call support (90% complete)

### Phase 2: Polish & Scale (Q1 2026)
**Focus:** Production readiness and reliability

**Deliverables:**
- Voice call integration (Twilio Voice + Whisper)
- Enhanced error handling and monitoring
- Rate limiting and abuse prevention
- Performance optimization (caching, query optimization)
- Comprehensive testing suite
- Production deployment automation
- Documentation for end users

### Phase 3: Intelligence Expansion (Q2 2026)
**Focus:** Smarter agent with more capabilities

**Deliverables:**
- Proactive notifications based on rules
- Advanced memory management (auto-summarization)
- Custom skill marketplace
- Multi-user support (family accounts)
- Improved natural language understanding
- Context-aware suggestions

### Phase 4: Ecosystem (Q3-Q4 2026)
**Focus:** Platform expansion and integrations

**Deliverables:**
- Additional integrations (Slack, Microsoft 365)
- Public API for third-party developers
- Webhook system for custom automation
- Analytics dashboard
- Mobile-optimized web interface
- White-label options for enterprise

---

## Open Questions

1. **Multi-User Access**: How should we handle family accounts with shared context but different permissions?
   - Should children have limited access?
   - How do we manage privacy between co-parents?

2. **Pricing Model**: What's the monetization strategy?
   - Per-user subscription?
   - Usage-based pricing?
   - Freemium model?

3. **Data Retention**: How long should we keep conversation history and memories?
   - Privacy concerns vs. long-term context value
   - GDPR/CCPA compliance requirements

4. **Proactive Assistance**: When should Sabine initiate conversations vs. wait for user queries?
   - Risk of being annoying vs. being helpful
   - User preferences and control mechanisms

5. **Error Recovery**: How should the system handle partial failures (e.g., can't access Google Calendar)?
   - Fail fast vs. degrade gracefully?
   - User expectations management

---

## Appendix

### Glossary

- **Deep Context**: User-specific information (rules, schedules, preferences) loaded before each query
- **Dual-Brain Memory**: Combination of vector store (semantic) and knowledge graph (deterministic)
- **MCP**: Model Context Protocol - standard for connecting AI assistants to external tools
- **LangGraph**: Agent orchestration framework built on LangChain
- **Tool Registry**: Unified system for discovering and invoking both local and remote tools
- **Prompt Caching**: Technique to cache static portions of prompts for cost and speed optimization

### References

- [Twilio Integration Guide](./TWILIO_INTEGRATION.md)
- [Database Schema Documentation](../supabase/README.md)
- [Agent Architecture README](../lib/agent/README.md)
- [Model Context Protocol Specification](https://spec.modelcontextprotocol.io/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
