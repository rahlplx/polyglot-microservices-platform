-- Create per-service databases for local dev
CREATE DATABASE identity_db;
CREATE DATABASE order_db;
CREATE DATABASE catalog_db;
CREATE DATABASE payment_db;
CREATE DATABASE notification_db;
CREATE DATABASE analytics_db;
CREATE DATABASE schema_registry_db;

-- Grant access to platform user
GRANT ALL PRIVILEGES ON DATABASE identity_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE order_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE catalog_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE payment_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE notification_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE analytics_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE schema_registry_db TO platform;
