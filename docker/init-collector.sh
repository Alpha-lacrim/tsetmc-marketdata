#!/bin/sh
set -eu
# psql variable quoting avoids interpolating the password into SQL source or logs.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=collector_password="$TSETMC_COLLECTOR_PASSWORD" <<'SQL'
CREATE ROLE tsetmc_collector LOGIN PASSWORD :'collector_password';
GRANT CONNECT ON DATABASE tsetmc_marketdata TO tsetmc_collector;
GRANT USAGE ON SCHEMA public TO tsetmc_collector;
ALTER DEFAULT PRIVILEGES FOR ROLE tsetmc_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tsetmc_collector;
ALTER DEFAULT PRIVILEGES FOR ROLE tsetmc_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO tsetmc_collector;
SQL
