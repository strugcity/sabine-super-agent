#!/bin/bash

# =============================================================================
# Personal Super Agent - Apply Database Schema
# =============================================================================
# This script applies the schema.sql to your Supabase database
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Personal Super Agent - Database Schema Setup              ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Please create a .env file with your DATABASE_URL"
    echo "Example: DATABASE_URL=postgresql://postgres:password@db.project.supabase.co:5432/postgres"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo -e "${RED}Error: DATABASE_URL not found in .env file!${NC}"
    echo ""
    echo "Please add your DATABASE_URL to .env:"
    echo "DATABASE_URL=postgresql://postgres:password@db.yourproject.supabase.co:5432/postgres"
    echo ""
    echo "You can find this in your Supabase project settings under 'Database' -> 'Connection string'"
    exit 1
fi

# Check if psql is installed
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql (PostgreSQL client) is not installed!${NC}"
    echo ""
    echo "Please install PostgreSQL client tools:"
    echo "  - macOS: brew install postgresql"
    echo "  - Ubuntu/Debian: sudo apt-get install postgresql-client"
    echo "  - Windows: Download from https://www.postgresql.org/download/windows/"
    echo ""
    echo -e "${YELLOW}Alternative: Copy supabase/schema.sql and paste it into the Supabase SQL Editor${NC}"
    exit 1
fi

echo -e "${YELLOW}About to apply schema to database...${NC}"
echo ""
echo "Database: $(echo $DATABASE_URL | sed 's/:[^:]*@/@/g')"  # Hide password
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${GREEN}Applying schema...${NC}"

# Apply the schema
psql "$DATABASE_URL" < supabase/schema.sql

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Schema applied successfully!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Verify the tables were created in Supabase Dashboard"
    echo "2. Check that pgvector extension is enabled"
    echo "3. Create a test user (optional)"
    echo ""
    echo "To verify from command line:"
    echo "  psql \"\$DATABASE_URL\" -c \"\\dt\""
else
    echo ""
    echo -e "${RED}✗ Failed to apply schema${NC}"
    echo ""
    echo "If you get a 'permission denied' error, try using the Supabase SQL Editor instead:"
    echo "1. Copy the contents of supabase/schema.sql"
    echo "2. Go to your Supabase Dashboard -> SQL Editor"
    echo "3. Paste and run the SQL"
    exit 1
fi
