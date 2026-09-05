# Database migrations

Run migrations from the repository root after setting `DATABASE_URL`:

```bash
alembic upgrade head
```

Create a new migration with:

```bash
alembic revision -m "describe the schema change"
```

Review generated SQL before applying it to production.
