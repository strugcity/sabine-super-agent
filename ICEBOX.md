# Personal Super Agent - Icebox

This document tracks future enhancements, ideas, and tasks that are not immediately prioritized but valuable for future development.

---

## 🚀 High Priority (Next Sprint)

### Gmail Webhook Implementation
**Status**: Planned
**Effort**: Medium (4-6 hours)
**Dependencies**: Google Workspace MCP integration (✅ Complete)

- [ ] Create `src/lib/gmail/parser.ts` for Pub/Sub message parsing
- [ ] Create `src/app/api/gmail/webhook/route.ts` webhook handler
- [ ] Setup Google Cloud Pub/Sub topic and subscription
- [ ] Configure Gmail push notifications
- [ ] Test real-time email notification flow
- [ ] Update system prompt in `lib/agent/core.py` to handle Gmail notifications

**Value**: Enables real-time email responses without polling

**Related Plan**: See `.claude/plans/glimmering-squishing-island.md`

---

### Twilio A2P 10DLC Campaign Approval Follow-up
**Status**: Waiting on External Approval
**Effort**: Low (1 hour)
**Dependencies**: Twilio campaign approval

- [ ] Monitor campaign approval status
- [ ] Test SMS functionality once approved
- [ ] Verify message delivery and formatting
- [ ] Document any limitations or throughput restrictions

**Value**: Enables production SMS communication

**Context**: Campaign submitted 2026-01-23, approval typically takes 1-3 business days

---

## 📧 Google Workspace Enhancements

### Calendar Integration Testing
**Status**: Not Started
**Effort**: Low (2-3 hours)

- [ ] Test `get_events` tool with user's calendar
- [ ] Test `create_event` with various parameters
- [ ] Test event modification and deletion
- [ ] Verify timezone handling
- [ ] Create example prompts for calendar management

**Value**: Validates calendar functionality works end-to-end

---

### Drive Integration Testing
**Status**: Not Started
**Effort**: Low (2-3 hours)

- [ ] Test file search capabilities
- [ ] Test file content retrieval
- [ ] Test file creation and updates
- [ ] Verify permissions handling
- [ ] Test with various file types (Docs, Sheets, PDFs, images)

**Value**: Validates Drive functionality works end-to-end

---

### Advanced Email Automation
**Status**: Idea Phase
**Effort**: High (8-10 hours)

- [ ] Create rule system for automated email responses
- [ ] Implement email classification (urgent, spam, personal, work)
- [ ] Build email summarization for daily digests
- [ ] Add support for email templates
- [ ] Implement smart reply suggestions

**Value**: Reduces manual email management overhead

---

## 🧠 Agent Intelligence

### Context Memory Improvements
**Status**: Not Started
**Effort**: High (12-16 hours)

- [ ] Implement conversation summarization for long sessions
- [ ] Add user preference learning
- [ ] Build task completion tracking
- [ ] Create memory consolidation system
- [ ] Add ability to recall past interactions

**Value**: Makes agent more personalized and effective over time

---

### Multi-User Support
**Status**: Partially Complete
**Effort**: Medium (6-8 hours)

**Completed**:
- ✅ User identification via phone number (SMS)
- ✅ User UUID storage in Supabase
- ✅ Session management per user

**Remaining**:
- [ ] User identity lookup from Gmail email addresses
- [ ] User preference storage and retrieval
- [ ] Per-user OAuth token management
- [ ] Admin dashboard for user management
- [ ] User onboarding flow

**Value**: Allows multiple people to use the agent

---

### Proactive Agent Behavior
**Status**: Idea Phase
**Effort**: High (10-12 hours)

- [ ] Morning briefing (calendar, weather, emails)
- [ ] Proactive reminders based on context
- [ ] Anomaly detection (unusual emails, calendar conflicts)
- [ ] Suggested actions based on patterns
- [ ] Daily/weekly summary reports

**Value**: Agent becomes truly proactive, not just reactive

---

## 🔌 Additional Integrations

### Microsoft Teams
**Status**: Not Started
**Effort**: Medium (6-8 hours)
**Dependencies**: Company security approval

- [ ] Research Teams MCP servers or API options
- [ ] Implement OAuth authentication
- [ ] Add message sending capabilities
- [ ] Add channel monitoring
- [ ] Test with company Teams instance

**Value**: Enables workplace communication via Teams

**Blocker**: May require company IT approval

---

### Slack Integration
**Status**: Not Started
**Effort**: Medium (6-8 hours)

- [ ] Find or deploy Slack MCP server
- [ ] Configure OAuth for Slack workspace
- [ ] Test channel messaging
- [ ] Test direct messaging
- [ ] Implement slash commands for Slack

**Value**: Alternative to Teams for workplace communication

---

### GitHub Integration
**Status**: Not Started
**Effort**: Low (3-4 hours)

- [ ] Deploy GitHub MCP server
- [ ] Configure GitHub OAuth
- [ ] Test issue creation and management
- [ ] Test PR creation and comments
- [ ] Add code review assistance

**Value**: Automates common GitHub workflows

---

### Task Management (Todoist/Asana/Linear)
**Status**: Not Started
**Effort**: Medium (4-6 hours)

- [ ] Research available MCP servers
- [ ] Select preferred task management tool
- [ ] Implement integration
- [ ] Test task creation from voice/SMS
- [ ] Add task completion tracking

**Value**: Unified task management across channels

---

## 🎙️ Voice & Communication

### Voice Call Handling
**Status**: Partially Complete
**Effort**: Medium (6-8 hours)

**Completed**:
- ✅ Twilio voice webhook handler
- ✅ Basic transcription via Whisper
- ✅ Text-to-speech responses

**Remaining**:
- [ ] Improve voice quality and naturalness
- [ ] Add conversation state management for calls
- [ ] Implement call transfer/forwarding
- [ ] Add voicemail transcription
- [ ] Multi-language support

**Value**: Better voice interaction experience

---

### WhatsApp Integration
**Status**: Not Started
**Effort**: Medium (4-6 hours)

- [ ] Setup Twilio WhatsApp sandbox
- [ ] Create WhatsApp webhook handler
- [ ] Test message sending/receiving
- [ ] Add media support (images, voice notes)
- [ ] Production WhatsApp Business API setup

**Value**: Enables communication via popular messaging platform

---

## 🛠️ Infrastructure & DevOps

### Production Deployment
**Status**: Partially Complete
**Effort**: High (8-10 hours)

**Completed**:
- ✅ Vercel deployment for Next.js frontend
- ✅ Twilio SMS integration working

**Remaining**:
- [ ] Deploy Python agent to Railway/Fly.io/similar
- [ ] Setup production database (Supabase Pro tier)
- [ ] Configure production MCP server hosting
- [ ] Add monitoring and alerting (Sentry, Datadog)
- [ ] Setup automated backups
- [ ] Configure CI/CD pipeline
- [ ] Load testing and performance optimization

**Value**: Makes agent production-ready and reliable

---

### Security Hardening
**Status**: Not Started
**Effort**: Medium (6-8 hours)

- [ ] Implement rate limiting on all endpoints
- [ ] Add request validation and sanitization
- [ ] Setup API key rotation system
- [ ] Implement audit logging
- [ ] Add encryption for sensitive data at rest
- [ ] Security audit and penetration testing
- [ ] GDPR/privacy compliance review

**Value**: Protects user data and prevents abuse

---

### Monitoring & Observability
**Status**: Minimal
**Effort**: Medium (4-6 hours)

**Current**:
- Basic logging via Python logging module
- No centralized monitoring

**Needed**:
- [ ] Setup Sentry for error tracking
- [ ] Add application metrics (Prometheus/Datadog)
- [ ] Create dashboards for key metrics
- [ ] Setup alerting for failures
- [ ] Add performance profiling
- [ ] User activity analytics

**Value**: Enables proactive issue detection and resolution

---

## 📱 User Experience

### Web Dashboard
**Status**: Basic UI Exists
**Effort**: High (16-20 hours)

**Current**:
- Basic Next.js chat interface

**Enhancements Needed**:
- [ ] Conversation history view
- [ ] Task/reminder management UI
- [ ] Settings page for preferences
- [ ] OAuth connection management
- [ ] Usage statistics and insights
- [ ] Mobile-responsive design
- [ ] Dark mode support

**Value**: Provides visual interface for agent interaction

---

### Mobile App
**Status**: Idea Phase
**Effort**: Very High (40+ hours)

- [ ] Evaluate React Native vs native development
- [ ] Design mobile-first UI/UX
- [ ] Implement push notifications
- [ ] Add voice input via mobile
- [ ] Support for photos/camera
- [ ] Offline mode support
- [ ] App store deployment

**Value**: Native mobile experience with better integration

---

## 🧪 Testing & Quality

### Test Coverage Improvements
**Status**: Minimal Testing
**Effort**: High (10-12 hours)

**Current State**:
- Manual end-to-end testing only
- No automated test suite

**Needed**:
- [ ] Unit tests for core agent logic
- [ ] Integration tests for MCP client
- [ ] End-to-end tests for SMS/voice workflows
- [ ] Load testing for API endpoints
- [ ] Mock testing for external services
- [ ] CI pipeline for automated testing

**Value**: Prevents regressions and improves reliability

---

## 📚 Documentation

### User Documentation
**Status**: Minimal
**Effort**: Medium (6-8 hours)

- [ ] User guide for SMS/voice interaction
- [ ] Email automation setup guide
- [ ] Calendar management examples
- [ ] FAQ section
- [ ] Troubleshooting guide
- [ ] Privacy policy and data handling
- [ ] Video tutorials

**Value**: Helps users get maximum value from agent

---

### Developer Documentation
**Status**: Basic README
**Effort**: Medium (6-8 hours)

- [ ] Architecture documentation
- [ ] API reference documentation
- [ ] MCP integration guide
- [ ] Contributing guidelines
- [ ] Deployment guide
- [ ] Database schema documentation
- [ ] Code style guide

**Value**: Enables contributions and maintenance

---

## 💡 Experimental Features

### Multimodal Capabilities
**Status**: Idea Phase
**Effort**: High (12-16 hours)

- [ ] Image analysis via Claude Vision
- [ ] OCR for document processing
- [ ] Photo organization via Drive
- [ ] Screenshot analysis for troubleshooting
- [ ] Diagram/chart interpretation

**Value**: Expands agent capabilities beyond text

---

### Agent Collaboration
**Status**: Idea Phase
**Effort**: Very High (20+ hours)

- [ ] Multi-agent system architecture
- [ ] Specialized sub-agents (calendar expert, email expert)
- [ ] Agent-to-agent communication protocol
- [ ] Consensus and conflict resolution
- [ ] Distributed task execution

**Value**: More sophisticated problem-solving capabilities

---

### Learning from Feedback
**Status**: Idea Phase
**Effort**: High (12-16 hours)

- [ ] User feedback collection system
- [ ] Response quality rating
- [ ] Fine-tuning dataset generation
- [ ] Continuous improvement loop
- [ ] A/B testing framework

**Value**: Agent improves over time based on usage

---

## 🔧 Technical Debt

### Code Refactoring
**Status**: Ongoing
**Effort**: Medium (varies)

- [ ] Remove deprecated `@app.on_event` in favor of lifespan handlers
- [ ] Consolidate environment variable loading
- [ ] Remove test files from repository (move to `.gitignore`)
- [ ] Standardize error handling across modules
- [ ] Improve type hints in Python code
- [ ] Refactor MCP client for better testability

**Value**: Cleaner, more maintainable codebase

---

### Dependency Updates
**Status**: Ongoing
**Effort**: Low (ongoing)

- [ ] Regular dependency updates
- [ ] Security vulnerability scanning
- [ ] Deprecation warning resolution
- [ ] Python version upgrade plan
- [ ] Node.js version upgrade plan

**Value**: Security and compatibility

---

## 📋 Notes

### Recently Completed
- ✅ Twilio SMS integration (2026-01-22)
- ✅ A2P 10DLC campaign setup (2026-01-23)
- ✅ Google Workspace MCP integration (2026-01-23)
- ✅ MCP streamable-http protocol update (2026-01-23)
- ✅ OAuth authentication for Google services (2026-01-23)
- ✅ Environment variable loading fixes (2026-01-23)

### Current Blockers
- Twilio A2P 10DLC campaign approval (external dependency)
- Microsoft Teams integration (company security approval needed)

### Priority Assessment Criteria
- **High**: Core functionality, user-facing features, security issues
- **Medium**: Quality of life improvements, additional integrations
- **Low**: Nice-to-haves, experimental features, optimizations

---

**Last Updated**: 2026-01-23
**Maintainer**: Personal Super Agent Team
