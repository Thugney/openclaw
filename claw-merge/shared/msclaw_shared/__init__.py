"""MSClaw shared contracts, models, and utilities.

Core modules:
  - config: Centralised configuration from environment variables
  - db: SQLAlchemy models and session management
  - bus: NATS JetStream message bus
  - policy: OPA policy gate
  - audit: Hash-chained append-only audit ledger
  - idempotency: Durable idempotency enforcement
  - artifacts: MinIO artifact storage
  - adapters: Microsoft API adapters (real + mock)
"""
