-- Runs once on first start of the Postgres container (docker-entrypoint-initdb.d).
-- rs_owner owns the schema and runs migrations; rs_app is what the API/worker connect as.
-- rs_app is NOT the table owner, so row-level security always applies to it.
CREATE ROLE rs_owner LOGIN PASSWORD 'rs_owner' CREATEDB;
CREATE ROLE rs_app LOGIN PASSWORD 'rs_app';
CREATE DATABASE reporting OWNER rs_owner;
\connect reporting
ALTER SCHEMA public OWNER TO rs_owner;
