# Phase 6: Continuous delivery and blue/green

**Maps to:** Week 7 Session 2, mentor **Project 4** (blue-green).

## Goal
Deploy a new version with **no downtime** and be able to roll back in seconds.

## Tools
GitHub Actions (deploy job), Docker Compose or the gateway, nginx, a shell script.

## Tasks
1. Run two copies of the stack, **blue** and **green**, behind the nginx gateway. At any moment, only one receives traffic.
2. Write a deploy script that: pulls the new image tags (by SHA), starts the idle colour, waits for `/ready` on every service, runs the smoke test **against the idle colour**, then switches nginx to it and reloads.
3. Write a **rollback** script that switches back, and prove it works.
4. Extend the workflow: after CI passes on `main`, a deploy job connects to the server (SSH key stored as a GitHub **secret**, or an OIDC-based approach if you want to go further) and runs the script.
5. Use a GitHub **environment** with a required reviewer so production deploys need your approval.
6. Record the deployed version: expose the image SHA somewhere you can read it (a `/version` endpoint is a small code change you can make as a PR).

## Acceptance criteria
- [ ] Deploying a visible change causes no failed requests (run a `curl` loop during the switch and count errors).
- [ ] Rollback takes under a minute and is one command.
- [ ] A deploy cannot proceed if the idle colour fails its readiness or smoke checks.
- [ ] Nothing is deployed without passing CI and (for prod) approval.

## Break it on purpose
- Deploy an image that crashes on start; the switch must **not** happen.
- Deploy a version whose `/ready` fails because of a bad database URL.
- Cut over, then roll back mid-traffic.
- Make a database migration that is not backward compatible and think through why blue/green with a shared database needs the **expand/contract** pattern.

## Hints
- nginx `upstream` blocks and `nginx -s reload` do a graceful reload.
- Keep both colours on different host ports; the gateway chooses.
- `curl -s -o /dev/null -w "%{http_code}\n"` in a loop is a crude but effective availability probe.

## Cost
Server cost only; destroy when finished.

## Interview talking points
Blue/green vs rolling vs canary, rollback strategy, database compatibility during deploys, approvals and environments, secrets in pipelines.
