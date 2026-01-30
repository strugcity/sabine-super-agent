'use server'

import { createClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'
import { DomainEnum } from '@/lib/types/database'

// =============================================================================
// Entity Actions
// =============================================================================

export async function updateEntity(
  id: string,
  data: {
    name?: string
    type?: string
    domain?: DomainEnum
    attributes?: Record<string, unknown>
    status?: 'active' | 'archived' | 'deleted'
  }
) {
  const supabase = await createClient()

  const { error } = await supabase
    .from('entities')
    .update({
      ...data,
      updated_at: new Date().toISOString(),
    })
    .eq('id', id)

  if (error) {
    console.error('Error updating entity:', error)
    return { success: false, error: error.message }
  }

  revalidatePath('/dashboard/memory')
  return { success: true }
}

export async function deleteEntity(id: string) {
  const supabase = await createClient()

  // Soft delete by setting status to 'deleted'
  const { error } = await supabase
    .from('entities')
    .update({
      status: 'deleted',
      updated_at: new Date().toISOString(),
    })
    .eq('id', id)

  if (error) {
    console.error('Error deleting entity:', error)
    return { success: false, error: error.message }
  }

  revalidatePath('/dashboard/memory')
  return { success: true }
}

export async function createEntity(data: {
  name: string
  type: string
  domain: DomainEnum
  attributes?: Record<string, unknown>
}) {
  const supabase = await createClient()

  const { data: newEntity, error } = await supabase
    .from('entities')
    .insert({
      name: data.name,
      type: data.type,
      domain: data.domain,
      attributes: data.attributes || {},
      status: 'active',
    })
    .select()
    .single()

  if (error) {
    console.error('Error creating entity:', error)
    return { success: false, error: error.message }
  }

  revalidatePath('/dashboard/memory')
  return { success: true, entity: newEntity }
}

// =============================================================================
// Memory Actions
// =============================================================================

export async function deleteMemory(id: string) {
  const supabase = await createClient()

  // Hard delete for memories (they can be re-ingested)
  const { error } = await supabase
    .from('memories')
    .delete()
    .eq('id', id)

  if (error) {
    console.error('Error deleting memory:', error)
    return { success: false, error: error.message }
  }

  revalidatePath('/dashboard/memory')
  return { success: true }
}

export async function updateMemory(
  id: string,
  data: {
    content?: string
    importance_score?: number
    metadata?: Record<string, unknown>
  }
) {
  const supabase = await createClient()

  const { error } = await supabase
    .from('memories')
    .update({
      ...data,
      updated_at: new Date().toISOString(),
    })
    .eq('id', id)

  if (error) {
    console.error('Error updating memory:', error)
    return { success: false, error: error.message }
  }

  revalidatePath('/dashboard/memory')
  return { success: true }
}
