-- Add cancelled status values to task_queue status check constraint
-- This allows operator-initiated cancellation to be persisted.

ALTER TABLE task_queue
DROP CONSTRAINT IF EXISTS task_queue_status_check;

ALTER TABLE task_queue
ADD CONSTRAINT task_queue_status_check
CHECK (
  status IN (
    'queued',
    'in_progress',
    'completed',
    'failed',
    'cancelled_failed',
    'cancelled_in_progress',
    'cancelled_other'
  )
);
