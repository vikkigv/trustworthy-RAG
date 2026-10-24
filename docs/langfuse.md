# Langfuse (self-hosted) setup

Langfuse v3 self-hosting needs ClickHouse, Redis, and S3/MinIO, so it ships as its
own compose stack. Keep it separate from the app stack:

```bash
mkdir -p infra/langfuse
curl -L https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml \
  -o infra/langfuse/docker-compose.yml
docker compose -f infra/langfuse/docker-compose.yml up -d
```

Open http://localhost:3000, create an org/project, copy the public + secret keys
into `.env`, and set `LANGFUSE_ENABLED=true`. The API will then trace every
retrieval → rerank → generation → verification span.

Note: Langfuse's stack includes its own Redis and Postgres on different ports, so
it won't clash with the app's services.
