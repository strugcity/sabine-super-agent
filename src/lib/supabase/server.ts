import { createClient as createSupabaseClient } from '@supabase/supabase-js'

// Server-side Supabase client using service role key
// Uses existing Vercel env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
// Falls back to NEXT_PUBLIC_ versions for local dev
export async function createClient() {
  const supabaseUrl = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Missing Supabase environment variables')
  }

  return createSupabaseClient(supabaseUrl, supabaseKey)
}
