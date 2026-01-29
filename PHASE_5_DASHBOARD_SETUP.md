# Phase 5: Memory Dashboard - Setup Guide

## Overview

The Memory Dashboard is a Next.js-powered interface for viewing and managing the Context Engine's knowledge base. It provides:

- **Entity Cards**: Organized view of entities grouped by domain (Work, Family, Personal, Logistics)
- **Memory Stream**: Timeline of semantic memories with importance scores and entity links
- **Server-Side Rendering**: Direct Supabase connection for fast, read-only data display

## Architecture

```
src/
├── app/
│   ├── dashboard/
│   │   └── memory/
│   │       └── page.tsx          # Main dashboard page (Server Component)
│   └── page.tsx                   # Home page with dashboard link
├── components/
│   ├── EntityCard.tsx             # Entity display component
│   └── MemoryStream.tsx           # Memory timeline component
└── lib/
    ├── supabase/
    │   ├── server.ts              # Server-side Supabase client
    │   └── client.ts              # Client-side Supabase client
    └── types/
        └── database.ts            # TypeScript types for DB models
```

## Setup Instructions

### 1. Configure Environment Variables

Create or update `.env.local` with your Supabase credentials:

```bash
# Get these from: https://app.supabase.com/project/_/settings/api
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key
```

### 2. Verify Database Schema

Ensure your Supabase database has the Context Engine schema applied:

```bash
# Check if migrations are applied
# The database should have these tables:
# - entities (with domain, type, attributes)
# - memories (with embedding, entity_links, metadata)
# - tasks (optional, for future use)
```

If not applied, run the migrations:

```bash
# From the project root
cd supabase
# Apply the schema using Supabase CLI or SQL Editor
```

### 3. Install Dependencies

Dependencies are already installed via npm:

```bash
npm install @supabase/ssr @supabase/supabase-js
```

### 4. Run the Development Server

```bash
npm run dev
```

Visit: http://localhost:3000

### 5. Access the Dashboard

Navigate to: http://localhost:3000/dashboard/memory

Or click the "Memory Dashboard" button on the home page.

## Features

### Entity Cards

- **Domain Grouping**: Entities organized by Work, Family, Personal, Logistics
- **Visual Hierarchy**: Color-coded by domain with status badges
- **Attribute Preview**: Shows first 3 attributes with truncation
- **Status Indicators**: Active, archived, deleted status

### Memory Stream

- **Chronological Timeline**: Most recent memories first (limit 50)
- **Importance Scoring**: Color-coded importance (0-100%)
- **Entity Links**: Shows linked entities with truncated UUIDs
- **Metadata Details**: Expandable metadata viewer
- **Empty States**: Helpful messages when no data exists

## Database Queries

### Entities Query

```typescript
// Fetches active entities ordered by creation date
const { data } = await supabase
  .from('entities')
  .select('*')
  .eq('status', 'active')
  .order('created_at', { ascending: false });
```

### Memories Query

```typescript
// Fetches 50 most recent memories
const { data } = await supabase
  .from('memories')
  .select('*')
  .order('created_at', { ascending: false })
  .limit(50);
```

## Styling

The dashboard uses:

- **Tailwind CSS**: Utility-first styling
- **Color Scheme**:
  - Work: Blue
  - Family: Pink
  - Personal: Purple
  - Logistics: Green
- **Responsive Design**: Mobile-first with grid layouts

## Data Flow

```
User → /dashboard/memory
  ↓
Server Component (page.tsx)
  ↓
Supabase Server Client
  ↓
PostgreSQL Database
  ↓
Render JSX with Entity & Memory Components
  ↓
Client Browser
```

## Authentication (Future Phase)

Currently, the dashboard has **no authentication**. RLS policies are set to public access.

Future phases will add:

- **Clerk Integration**: User authentication
- **RLS Policies**: User-specific data access
- **Admin Dashboard**: Privileged views for admins

## Testing

### Manual Testing Checklist

- [ ] Dashboard loads without errors
- [ ] Entities display correctly grouped by domain
- [ ] Memories show in chronological order
- [ ] Entity links expand to show UUIDs
- [ ] Metadata details are expandable
- [ ] Empty states show when no data exists
- [ ] Navigation from home page works
- [ ] Responsive layout works on mobile

### Sample Data

To test the dashboard, add sample data via Supabase SQL Editor:

```sql
-- Sample Entity
INSERT INTO entities (name, type, domain, attributes, status) VALUES
('Project Phoenix', 'project', 'work', '{"deadline": "2026-03-01", "team": "Engineering"}', 'active');

-- Sample Memory
INSERT INTO memories (content, importance_score, metadata) VALUES
('Discussed timeline for Project Phoenix. Team agreed on March 1st deadline.', 0.8, '{"source": "meeting", "date": "2026-01-29"}');
```

## Troubleshooting

### "Cannot connect to Supabase"

- Verify `.env.local` has correct credentials
- Check Supabase project is active
- Ensure RLS policies allow read access

### "No entities/memories found"

- Run migrations: `supabase/migrations/*.sql`
- Add sample data (see above)
- Check Supabase dashboard for table data

### TypeScript Errors

```bash
# Rebuild TypeScript
npm run build
```

## Next Steps

- [ ] Add authentication (Clerk or Basic Auth)
- [ ] Implement CRUD operations (Create, Update, Delete)
- [ ] Add search and filtering
- [ ] Build Custody Calendar view
- [ ] Add real-time subscriptions

## Files Changed

### Created
- `src/lib/supabase/server.ts` - Server-side Supabase client
- `src/lib/supabase/client.ts` - Client-side Supabase client
- `src/lib/types/database.ts` - Database types
- `src/components/EntityCard.tsx` - Entity display component
- `src/components/MemoryStream.tsx` - Memory timeline component
- `src/app/dashboard/memory/page.tsx` - Dashboard page
- `.env.local` - Environment variables (template)

### Modified
- `src/app/page.tsx` - Added dashboard link
- `package.json` - Added @supabase/ssr dependency

## Production Deployment

### Vercel Deployment

1. Push code to GitHub
2. Connect to Vercel
3. Add environment variables in Vercel dashboard:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
4. Deploy

### Environment Variables in Vercel

```
Settings → Environment Variables → Add:
- NEXT_PUBLIC_SUPABASE_URL: https://your-project.supabase.co
- NEXT_PUBLIC_SUPABASE_ANON_KEY: eyJ...
```

## Support

For issues or questions, refer to:

- **Supabase Docs**: https://supabase.com/docs
- **Next.js Docs**: https://nextjs.org/docs
- **Project README**: `README.md`

---

**Phase 5 Complete!** 🎉

The Memory Dashboard is now functional and ready for viewing entities and memories from your Context Engine.
