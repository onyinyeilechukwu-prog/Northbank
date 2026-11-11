# Phase 2: Containerize

**Maps to:** Weeks 5–6 (Docker, Compose).

## Goal
Package each service as a small, secure, reproducible image, and run the whole system with one command.

## Tools
Docker, Docker Compose, nginx (the gateway), Postgres, Redis.

## Tasks
1. Write a **Dockerfile for each service** (ten of them; the services are nearly identical, so look for what can be shared). Requirements:
   - small base image (a `-slim` Python image), pinned to a version tag, not `latest`;
   - copy `requirements.txt` and install **before** copying the code (so layers cache);
   - run as a **non-root user**;
   - listen on port 8000; start with `uvicorn`;
   - a `HEALTHCHECK` that calls `/health`.
2. Add a `.dockerignore` (no `.git`, `.venv`, `*.db`, tests if you want a lean image).
3. Add `psycopg2-binary` to each `requirements.txt`, rebuild, and confirm the services still run.
4. Write a root `docker-compose.yml` with: the ten services, **one Postgres** with a separate database per service (hint: an init script mounted into the Postgres init directory), **Redis**, and the **nginx gateway** on host port 8080.
5. Use `depends_on` with `condition: service_healthy` and add **health checks** for Postgres and Redis.
6. Put secrets in a `.env` file (git-ignored) and commit an `.env.example` with fake values. Reference them with `${VAR}` in Compose.
7. Add a named **volume** for Postgres so data survives `docker compose down`.
8. Run `BASE=http://localhost:8080 python3 scripts/smoke_test.py` against the gateway. Internal endpoints are not routed, so KYC approval and the audit check are skipped unless you provide `KYC_ADMIN_URL` / `AUDIT_URL`; set `REQUIRE_KYC=false` on `accounts` if you want to skip KYC entirely.
9. Confirm the event flow: after a transfer, `GET /notifications` returns a message.

## Acceptance criteria
- [ ] `docker compose up -d` brings everything up from a clean checkout plus `.env`.
- [ ] The smoke test passes through the gateway.
- [ ] Each image runs as non-root (`docker compose exec auth id`).
- [ ] Image sizes are sensible (aim well under 300 MB each; compare with a full `python` base).
- [ ] Data survives `docker compose down` then `up`; it is gone after `down -v`.
- [ ] No secret appears in any image layer or in git.

## Break it on purpose
- Change `JWT_SECRET` in only one service; watch tokens get rejected and find it in the logs.
- Stop Postgres; watch `/ready` go 503 while `/health` stays 200. Restart it and watch recovery.
- Stop Redis; make a transfer and confirm it still succeeds (the event is lost by design: note this as a known gap, and think about how an outbox pattern would fix it).
- Copy the code **before** installing requirements, rebuild after a one-line code change, and compare build times.

## Hints
- Inside Compose, services reach each other by **service name** (`http://accounts:8000`), not `localhost`.
- `docker compose logs -f <service>`, `docker compose ps`, `docker compose exec <service> sh`.
- `docker history <image>` shows layers and sizes.
- Remember from Appendix A: slim images may lack `ping`.

## Cost
$0.

## Interview talking points
Layer caching, non-root containers, multi-stage builds, why `latest` is dangerous, the difference between liveness and readiness, and how Compose networking and DNS work.

## Note
The Dockerfile and Compose hints here were not run by the author of this repo (no Docker daemon was available while it was prepared); the **application** code was. If a hint conflicts with what you see, trust the real error message.
