--
-- 002_roles.sql
--
-- Creates a least-privilege read-only role for CData Connect Cloud and
-- grants current and future SELECT privileges in the public schema.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cdata_ro') THEN
    CREATE ROLE cdata_ro LOGIN PASSWORD 'strongpassword' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END$$;

-- Grants: database connect and schema usage
GRANT CONNECT ON DATABASE healthdb TO cdata_ro;
GRANT USAGE ON SCHEMA public TO cdata_ro;

-- Current tables/views
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cdata_ro;

-- Future tables/views default privileges (only for objects created by current owner)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cdata_ro;

