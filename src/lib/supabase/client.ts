import { createClient as createSupabaseClient } from '@supabase/supabase-js'

// Client-side Supabase client
// Note: Client components still need NEXT_PUBLIC_ vars if used
// The dashboard currently only uses server components, so this is optional
export function createClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY')
  }

  return createSupabaseClient(supabaseUrl, supabaseKey)
}
