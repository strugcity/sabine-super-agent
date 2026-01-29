// =============================================================================
// Database Types - Context Engine
// =============================================================================
// TypeScript types for Supabase tables (entities, memories, tasks)
// Based on: supabase/migrations/20260129170000_init_context_engine.sql
// =============================================================================

export type DomainEnum = 'work' | 'family' | 'personal' | 'logistics';

export type EntityStatus = 'active' | 'archived' | 'deleted';

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';

// -----------------------------------------------------------------------------
// Entity Type
// -----------------------------------------------------------------------------
export interface Entity {
  id: string;
  name: string;
  type: string; // 'project', 'person', 'event', 'location', etc.
  domain: DomainEnum;
  attributes: Record<string, any>; // Flexible JSON for entity-specific data
  status: EntityStatus;
  created_at: string;
  updated_at: string;
}

// -----------------------------------------------------------------------------
// Memory Type
// -----------------------------------------------------------------------------
export interface Memory {
  id: string;
  content: string;
  embedding: number[] | null; // Vector embedding (1536 dimensions)
  entity_links: string[]; // Array of entity UUIDs
  metadata: Record<string, any>; // Additional context
  importance_score: number; // 0-1
  created_at: string;
  updated_at: string;
}

// -----------------------------------------------------------------------------
// Task Type
// -----------------------------------------------------------------------------
export interface Task {
  id: string;
  title: string;
  description: string | null;
  entity_id: string | null; // Optional link to entity
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  completed_at: string | null;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
}

// -----------------------------------------------------------------------------
// Grouped Entities (for Dashboard Display)
// -----------------------------------------------------------------------------
export interface EntitiesByDomain {
  work: Entity[];
  family: Entity[];
  personal: Entity[];
  logistics: Entity[];
}
