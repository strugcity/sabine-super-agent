-- Add approval fields and awaiting_approval status to task_queue

ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS approval_required BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS approval_reason TEXT;

ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS approved_by TEXT;

ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

ALTER TABLE task_queue
DROP CONSTRAINT IF EXISTS task_queue_status_check;

ALTER TABLE task_queue
ADD CONSTRAINT task_queue_status_check
CHECK (
  status IN (
    'queued',
    'in_progress',
    'awaiting_approval',
    'completed',
    'failed',
    'cancelled_failed',
    'cancelled_in_progress',
    'cancelled_other'
  )
);
