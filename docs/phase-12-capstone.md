# Phase 12: Capstone and portfolio

**Maps to:** mentor **Project 9** (Homelab as Code), your CV and interviews.

## Goal
Turn the work into something a recruiter understands in two minutes, and practise explaining it.

## Tasks
1. **One command to a working system.** Add a `Makefile` (or `task` file) with targets like `make test`, `make up`, `make cluster`, `make destroy`. Someone should reproduce your environment from the README alone.
2. **Rewrite the README** as a front page: what it is, an architecture diagram, a screenshot of your Grafana dashboard and Argo CD, a short "how to run", and a section on **decisions and trade-offs**.
3. Record a **3–5 minute demo** (screen recording): change code, watch the pipeline, see the rollout, trigger an alert, read the runbook.
4. Write a **case study** (one page): problem, approach, what broke, what you would do differently.
5. Pin the repositories on your GitHub profile; make sure no secrets or personal data are in history.
6. Add the CV bullets below (edit them to match what you **actually** did).
7. Practise the interview questions out loud, with a friend or recording.

## CV bullets (use only what is true for you)
- "Built a CI/CD pipeline in GitHub Actions for a 4-service microservices application: lint, test, container build, Trivy vulnerability scanning and SHA-tagged image publishing to GHCR."
- "Provisioned AWS infrastructure with Terraform (remote state, tagged resources, PR plan checks) and configured servers with idempotent Ansible roles."
- "Implemented GitOps with Argo CD (automated sync, self-heal) so every production change is a reviewed Git commit with one-command rollback."
- "Deployed to Kubernetes with Helm; configured probes, resource limits, autoscaling and NetworkPolicies."
- "Built Prometheus/Grafana/Loki observability with RED dashboards, SLO-based alerts and runbooks; ran chaos experiments and a backup-restore drill with measured RTO/RPO."

## Interview questions to rehearse
1. Walk me through what happens from `git push` to code running in production.
2. A deploy made error rates spike. What do you do in the first five minutes?
3. Liveness vs readiness probes: what happens if you mix them up?
4. Why tag images with the commit SHA?
5. Terraform state: what is it, where do you store it, what if it is corrupted?
6. Terraform vs Ansible?
7. How do you manage secrets in Git-based workflows?
8. What is idempotency and where does this project rely on it?
9. What would you alert on for a payments service, and why?
10. What are the top three weaknesses of your own project? (Be honest: this question rewards honesty.)
11. What would change if this ran in production with real money? (Managed database, TLS everywhere, an outbox pattern for events, audit logs, rate limiting, secrets rotation, compliance.)

## Acceptance criteria
- [ ] A stranger can run your project from the README.
- [ ] You can explain every file in the repo.
- [ ] You can name what you did **not** do and why.
- [ ] You have a demo link and a case study.

## Interview talking points
Everything. The goal of this phase is to turn experience into a story: situation, what you did, result, and what you learned.
