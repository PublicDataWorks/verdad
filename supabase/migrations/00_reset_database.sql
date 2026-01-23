-- Reset Database Script
-- Run this as postgres superuser to completely reset the database:
-- sudo -u postgres psql -d verdad_debates -f supabase/migrations/00_reset_database.sql

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO verdad_user;
GRANT ALL ON SCHEMA public TO PUBLIC;

-- Create vector extension
CREATE EXTENSION IF NOT EXISTS vector;
