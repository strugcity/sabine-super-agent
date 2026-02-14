# Sabine Reminder System - Development Plan

## Overview

Build a hybrid reminder system for Sabine that combines:
1. **Custom SMS reminders** - For quick personal reminders ("remind me at 10 AM about glasses")
2. **Google Calendar event reminders** - For calendar-bound reminders ("remind me 1 hour before my meeting")

This plan follows **Behavior-Driven Development (BDD)** principles, with each step defining expected behaviors before implementation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      User Request                                │
│         "Remind me at 10 AM about my glasses"                   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Sabine Agent (LangGraph)                       │
│  Decides: SMS reminder (standalone) or Calendar event reminder  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  SMS Reminder Skill  │    │  Calendar Reminder Skill │
│  (create_reminder)   │    │  (create_calendar_event) │
└──────────┬───────────┘    └────────────┬─────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────┐
│   Supabase Table     │    │   Google Calendar API    │
│   (reminders)        │    │   (events w/ reminders)  │
└──────────┬───────────┘    └──────────────────────────┘
           │
           ▼
┌──────────────────────┐
│   APScheduler        │
│   (fires at time)    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   Notification       │
│   - SMS (Twilio)     │
│   - Slack (optional) │
└──────────────────────┘
```

---

## Phase 1: Database Foundation

### Step 1.1: Create Reminders Table Migration

**Behavior Specification:**
```gherkin
Feature: Reminders Database Schema
  As the reminder system
  I need a database table to persist reminders
  So that reminders survive server restarts and can be queried

  Scenario: Create a new reminder record
    Given a valid user_id exists
    When I insert a reminder with title "Pick up glasses" and scheduled_time "2026-02-02 10:00:00 CST"
    Then the reminder should be stored with a UUID primary key
    And created_at and updated_at timestamps should be set automatically
    And is_active should default to TRUE
    And is_completed should default to FALSE

  Scenario: Query active reminders for scheduling
    Given there are 5 reminders in the database
    And 3 are active and 2 are completed
    When I query for active reminders ordered by scheduled_time
    Then I should receive only the 3 active reminders
    And they should be ordered by scheduled_time ascending

  Scenario: Support recurring reminders
    Given a reminder with repeat_pattern "weekly"
    When I query the reminder
    Then the repeat_pattern field should be accessible
    And the system can use it to schedule the next occurrence
```

**Task:**
- [ ] Create migration file: `supabase/migrations/YYYYMMDDHHMMSS_create_reminders_table.sql`
- [ ] Define columns: id, user_id, title, description, reminder_type, scheduled_time, repeat_pattern, is_active, is_completed, notification_channels (JSONB), metadata (JSONB), created_at, updated_at
- [ ] Add indexes for efficient querying: (user_id, is_active, scheduled_time), (scheduled_time WHERE is_active)
- [ ] Add RLS policies for service role access
- [ ] Add auto-update trigger for updated_at

**Acceptance Criteria:**
- [ ] Migration runs without errors
- [ ] Can insert/query/update reminders via Supabase client
- [ ] Indexes improve query performance for active reminders

---

### Step 1.2: Create Reminder Pydantic Models

**Behavior Specification:**
```gherkin
Feature: Reminder Data Models
  As a developer
  I need Pydantic models for reminders
  So that I have type safety and validation

  Scenario: Validate reminder creation request
    Given a ReminderCreate model
    When I provide title "Test" and scheduled_time as a valid datetime
    Then the model should validate successfully
    And reminder_type should default to "sms"

  Scenario: Reject invalid reminder
    Given a ReminderCreate model
    When I provide an empty title
    Then validation should fail with a descriptive error

  Scenario: Serialize reminder for API response
    Given a Reminder model with all fields populated
    When I serialize to JSON
    Then all datetime fields should be ISO 8601 formatted
    And UUID fields should be string representations
```

**Task:**
- [ ] Create file: `lib/agent/models/reminder.py`
- [ ] Define ReminderCreate (input validation)
- [ ] Define ReminderUpdate (partial updates)
- [ ] Define Reminder (full model with id, timestamps)
- [ ] Define ReminderType enum: "sms", "email", "slack", "calendar_event"
- [ ] Define RepeatPattern enum: None, "daily", "weekly", "monthly", "yearly"

**Acceptance Criteria:**
- [ ] All models pass type checking (mypy)
- [ ] Validation errors are descriptive
- [ ] Models integrate with FastAPI endpoints

---

## Phase 2: Reminder Skill (Create/Manage)

### Step 2.1: Create Reminder Skill - Manifest

**Behavior Specification:**
```gherkin
Feature: Reminder Skill Discovery
  As the agent registry
  I need a valid manifest.json for the reminder skill
  So that the skill can be auto-discovered and loaded

  Scenario: Skill is discovered on startup
    Given the reminder skill has manifest.json and handler.py
    When the agent starts and loads skills
    Then "create_reminder" should appear in the tools list
    And it should have a description explaining its purpose

  Scenario: Skill parameters are validated
    Given the manifest defines required parameters
    When a user calls the skill without required params
    Then the LangChain StructuredTool should reject the call
    And provide a helpful error message
```

**Task:**
- [ ] Create directory: `lib/skills/reminder/`
- [ ] Create manifest.json with:
  - name: "create_reminder"
  - description: Clear explanation of what it does
  - parameters: title (required), scheduled_time (required), description (optional), reminder_type (optional, default "sms"), repeat_pattern (optional)

**Acceptance Criteria:**
- [ ] Skill appears in `/tools` endpoint
- [ ] Parameters match expected schema
- [ ] Description is helpful for LLM decision-making

---

### Step 2.2: Create Reminder Skill - Handler

**Behavior Specification:**
```gherkin
Feature: Create Reminder Handler
  As a user
  I want to create reminders via natural language
  So that Sabine can remind me about things

  Scenario: Create a one-time SMS reminder
    Given I say "remind me at 10 AM tomorrow about picking up glasses"
    When Sabine calls create_reminder with:
      | title          | Pick up glasses           |
      | scheduled_time | 2026-02-03T10:00:00-06:00 |
      | reminder_type  | sms                       |
    Then a reminder should be saved to the database
    And a scheduler job should be created for that time
    And Sabine should confirm "I'll remind you at 10:00 AM tomorrow about picking up glasses"

  Scenario: Create a recurring weekly reminder
    Given I say "remind me every Sunday at 4 PM to post the baseball video"
    When Sabine calls create_reminder with:
      | title          | Post baseball video |
      | scheduled_time | 2026-02-09T16:00:00-06:00 |
      | repeat_pattern | weekly              |
    Then a reminder should be saved with repeat_pattern = "weekly"
    And a scheduler job should be created
    And Sabine should confirm the recurring schedule

  Scenario: Handle invalid time
    Given I say "remind me yesterday about something"
    When Sabine attempts to create a reminder in the past
    Then the skill should return an error
    And Sabine should ask for a valid future time

  Scenario: Handle timezone correctly
    Given the user is in US Central time
    When I say "remind me at 10 AM"
    Then the scheduled_time should be stored as 10:00 AM Central
    And NOT converted incorrectly to UTC for display
```

**Task:**
- [ ] Create handler.py with async execute() function
- [ ] Parse and validate scheduled_time (handle relative times like "tomorrow", "in 2 hours")
- [ ] Store reminder in Supabase
- [ ] Register job with APScheduler
- [ ] Return success message with confirmation details
- [ ] Handle errors gracefully

**Acceptance Criteria:**
- [ ] One-time reminders are created and scheduled
- [ ] Recurring reminders are created with correct pattern
- [ ] Times are handled in user's timezone (Central)
- [ ] Past times are rejected with helpful message
- [ ] Database record matches scheduler job

---

### Step 2.3: List Reminders Skill

**Behavior Specification:**
```gherkin
Feature: List Reminders
  As a user
  I want to see my upcoming reminders
  So that I know what I've scheduled

  Scenario: List all active reminders
    Given I have 3 active reminders and 1 completed
    When I say "what reminders do I have?"
    Then Sabine should list only the 3 active reminders
    And they should be sorted by scheduled_time
    And show title, time, and repeat pattern if any

  Scenario: No active reminders
    Given I have no active reminders
    When I say "what reminders do I have?"
    Then Sabine should say "You don't have any active reminders"
```

**Task:**
- [ ] Create `list_reminders` skill (manifest.json + handler.py)
- [ ] Query Supabase for active reminders
- [ ] Format output nicely for conversation
- [ ] Include reminder ID for reference (for cancellation)

**Acceptance Criteria:**
- [ ] Returns only active reminders
- [ ] Sorted by scheduled_time
- [ ] Formatted clearly for user

---

### Step 2.4: Cancel Reminder Skill

**Behavior Specification:**
```gherkin
Feature: Cancel Reminder
  As a user
  I want to cancel reminders I no longer need
  So that I don't get unnecessary notifications

  Scenario: Cancel by description
    Given I have a reminder "Pick up glasses" at 10 AM
    When I say "cancel the glasses reminder"
    Then Sabine should find the matching reminder
    And set is_active = FALSE
    And remove the scheduler job
    And confirm "I've cancelled the reminder about picking up glasses"

  Scenario: Ambiguous cancellation
    Given I have two reminders containing "meeting"
    When I say "cancel the meeting reminder"
    Then Sabine should list both and ask which one to cancel

  Scenario: Cancel non-existent reminder
    When I say "cancel my dentist reminder"
    And no such reminder exists
    Then Sabine should say "I couldn't find a reminder about that"
```

**Task:**
- [ ] Create `cancel_reminder` skill
- [ ] Support cancellation by ID or fuzzy title match
- [ ] Deactivate in database (soft delete)
- [ ] Remove scheduler job
- [ ] Handle ambiguous matches

**Acceptance Criteria:**
- [ ] Reminders can be cancelled by description
- [ ] Scheduler job is removed
- [ ] Ambiguous requests prompt for clarification

---

## Phase 3: Notification Delivery

### Step 3.1: Reminder Notification Handler

**Behavior Specification:**
```gherkin
Feature: Reminder Notification Delivery
  As the scheduler
  I need to send notifications when reminders are due
  So that users are alerted at the right time

  Scenario: Send SMS notification for one-time reminder
    Given a reminder is scheduled for 10:00 AM
    When the scheduler fires at 10:00 AM
    Then an SMS should be sent to USER_PHONE
    And the message should include the reminder title
    And the reminder should be marked as completed

  Scenario: Send SMS for recurring reminder
    Given a weekly reminder is scheduled for Sunday 4 PM
    When the scheduler fires at Sunday 4 PM
    Then an SMS should be sent
    And the reminder should NOT be marked as completed
    And the next occurrence should be scheduled for next Sunday

  Scenario: Handle SMS delivery failure
    Given Twilio is unavailable
    When the scheduler tries to send SMS
    Then the failure should be logged
    And the reminder should remain active for retry
    And an error should be recorded in metadata

  Scenario: Multi-channel notification
    Given a reminder with notification_channels = {"sms": true, "slack": true}
    When the reminder fires
    Then both SMS and Slack notifications should be sent
```

**Task:**
- [ ] Create notification handler: `lib/agent/reminder_notifications.py`
- [ ] Implement `fire_reminder(reminder_id)` function
- [ ] Send notification via configured channels (SMS primary)
- [ ] Handle recurring reminders (reschedule next occurrence)
- [ ] Mark one-time reminders as completed
- [ ] Log all notification attempts

**Acceptance Criteria:**
- [ ] SMS is sent at scheduled time
- [ ] Recurring reminders reschedule automatically
- [ ] Failures are logged and handled gracefully
- [ ] Completion status is updated correctly

---

### Step 3.2: Integrate with APScheduler

**Behavior Specification:**
```gherkin
Feature: Scheduler Integration
  As the reminder system
  I need to manage scheduler jobs for each reminder
  So that notifications fire at the correct time

  Scenario: Add job for new reminder
    When a reminder is created for 10:00 AM tomorrow
    Then a DateTrigger job should be added to APScheduler
    And the job ID should match the reminder ID
    And get_jobs() should include this job

  Scenario: Add job for recurring reminder
    When a weekly reminder is created
    Then a CronTrigger job should be added
    And it should fire every week at the same time

  Scenario: Remove job when reminder cancelled
    When a reminder is cancelled
    Then the corresponding scheduler job should be removed
    And get_jobs() should no longer include it

  Scenario: Restore jobs on server restart
    Given there are 5 active reminders in the database
    When the server restarts
    Then all 5 scheduler jobs should be recreated
    And they should have correct trigger times
```

**Task:**
- [ ] Extend `SabineScheduler` class with reminder job methods:
  - `add_reminder_job(reminder_id, scheduled_time, repeat_pattern)`
  - `remove_reminder_job(reminder_id)`
  - `restore_reminder_jobs()` - called on startup
- [ ] Use DateTrigger for one-time, CronTrigger for recurring
- [ ] Store job metadata for debugging

**Acceptance Criteria:**
- [ ] Jobs are added/removed correctly
- [ ] Jobs survive server restart (restored from DB)
- [ ] Trigger types match reminder patterns

---

## Phase 4: Calendar Event Reminders

### Step 4.1: Create Calendar Event with Reminder Skill

**Behavior Specification:**
```gherkin
Feature: Calendar Event Reminders
  As a user
  I want to create calendar events with reminders
  So that I get notified about scheduled events

  Scenario: Create event with default reminder
    Given I say "add a dentist appointment tomorrow at 2 PM"
    When Sabine creates the calendar event
    Then a Google Calendar event should be created
    And it should have a 15-minute popup reminder by default
    And Sabine should confirm the event was created

  Scenario: Create event with custom reminder
    Given I say "add a meeting tomorrow at 3 PM and remind me 1 hour before"
    When Sabine creates the calendar event
    Then the event should have a 60-minute reminder
    And the reminder method should be notification/popup

  Scenario: Create event with SMS reminder (hybrid)
    Given I say "add a flight tomorrow at 6 AM and text me 2 hours before"
    When Sabine creates the event
    Then a Google Calendar event should be created
    AND a separate SMS reminder should be scheduled for 4 AM

  Scenario: Event reminder vs standalone reminder decision
    Given I say "remind me about the dentist tomorrow"
    When Sabine processes this
    Then she should ask: "Would you like me to add this to your calendar or just set a reminder?"
```

**Task:**
- [ ] Create `create_calendar_event` skill (or extend existing calendar skill)
- [ ] Add event creation to Google Calendar API
- [ ] Support reminder overrides (minutes before, method)
- [ ] Optionally create hybrid: calendar event + SMS reminder

**Acceptance Criteria:**
- [ ] Events are created in Google Calendar
- [ ] Reminders are attached to events
- [ ] User can specify reminder timing
- [ ] Hybrid approach works (calendar + SMS)

---

## Phase 5: Testing & Verification

### Step 5.1: Unit Tests for Reminder Models

**Task:**
- [ ] Test ReminderCreate validation
- [ ] Test ReminderUpdate partial updates
- [ ] Test timezone handling
- [ ] Test repeat pattern validation

---

### Step 5.2: Integration Tests for Reminder Skill

**Task:**
- [ ] Test create_reminder with mock scheduler
- [ ] Test list_reminders with seeded data
- [ ] Test cancel_reminder with existing reminder
- [ ] Test error handling (invalid times, missing data)

---

### Step 5.3: End-to-End Test

**Task:**
- [ ] Create reminder via API
- [ ] Verify database record
- [ ] Verify scheduler job
- [ ] Fast-forward time (or use short delay)
- [ ] Verify SMS sent (mock Twilio)
- [ ] Verify completion status

---

## Phase 6: Documentation & Deployment

### Step 6.1: Update Agent System Prompt

**Task:**
- [ ] Add reminder capabilities to Sabine's system prompt
- [ ] Explain when to use SMS reminder vs calendar event
- [ ] Provide example phrasings

---

### Step 6.2: Deploy to Railway

**Task:**
- [ ] Run migration on production Supabase
- [ ] Deploy updated agent to Railway
- [ ] Verify scheduler starts and restores jobs
- [ ] Test with real SMS

---

## Implementation Order

```
Week 1: Foundation
├── Step 1.1: Database migration
├── Step 1.2: Pydantic models
└── Step 2.1: Skill manifest

Week 2: Core Functionality
├── Step 2.2: Create reminder handler
├── Step 2.3: List reminders skill
├── Step 2.4: Cancel reminder skill
└── Step 3.1: Notification handler

Week 3: Scheduler & Calendar
├── Step 3.2: APScheduler integration
├── Step 4.1: Calendar event skill
└── Step 5.1-5.2: Unit & integration tests

Week 4: Polish & Deploy
├── Step 5.3: E2E tests
├── Step 6.1: System prompt update
└── Step 6.2: Production deployment
```

---

## Success Metrics

1. **Functional**: Sabine can create, list, and cancel reminders via natural language
2. **Reliable**: SMS notifications are delivered within 1 minute of scheduled time
3. **Persistent**: Reminders survive server restarts
4. **Timezone-aware**: All times displayed and stored correctly in user's timezone
5. **Hybrid**: Both standalone SMS and calendar-bound reminders work

---

## Dependencies

- [x] Supabase (existing)
- [x] APScheduler (existing)
- [x] Twilio (existing, configured)
- [x] Google Calendar API (existing skill)
- [ ] Twilio in requirements.txt (needs to be added)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Server restart loses scheduled jobs | Restore from DB on startup |
| SMS delivery failure | Log, retry, fall back to email/Slack |
| Timezone confusion | Always store UTC, display in user TZ |
| Duplicate notifications | Track notification status in DB |
| APScheduler memory issues | Use job stores (SQLAlchemy) for large scale |

