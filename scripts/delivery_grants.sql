-- Source database ONLY, after 0005_delivery, as the schema administrator.
-- This preview worker shares the existing trusted collector role for short local transactions.
-- It never receives company SQL credentials or permission to migrate automatically.
GRANT SELECT,INSERT,UPDATE ON sync_delivery_state TO tsetmc_collector;
