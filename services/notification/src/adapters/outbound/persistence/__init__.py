"""
Persistence adapters for the Notification service.

These adapters implement the outbound ports for database operations using
SQLAlchemy 2.0 async ORM with asyncpg driver for PostgreSQL. The adapters
handle notification records, tracking events, template definitions, and
ML model parameter storage.
"""
