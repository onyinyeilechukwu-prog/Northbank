# Phase 10: Security and secrets

**Maps to:** mentor **Project 10** (Vault), Week 8 (IAM), Week 5/7 (Trivy).

## Goal
Show you build security **into** the pipeline and platform, not as an afterthought.

## Tools
Trivy, gitleaks, SBOM tooling (e.g. syft), Vault or External Secrets Operator, Kubernetes NetworkPolicy, pod security settings.

## Tasks
1. **Fix the deliberate weakness:** the services fall back to an insecure default `JWT_SECRET` and log a warning. Make a PR that makes each service **refuse to start** without a real secret when an `APP_ENV=production` setting is present. Add a test.
2. Add **gitleaks** to CI and to a pre-commit hook; prove it blocks a fake key.
3. Scan dependencies and images with **Trivy**; generate an **SBOM** and attach it to the build artifacts.
4. Pin all base images and dependencies; enable automated dependency PRs (Dependabot or similar).
5. Replace plain Kubernetes Secrets in Git with a proper approach: **External Secrets Operator** with a backend, or **HashiCorp Vault** (dev mode is fine to learn), or **sealed secrets**. Pick one and document the trade-offs.
6. Add **NetworkPolicies**: default-deny in the `northbank` namespace, then allow only the real flows (gateway to services, `transactions` to `accounts` and Redis, `notification` to Redis, each service to its database).
7. Harden pods: `runAsNonRoot`, read-only root filesystem where possible, drop capabilities, no privilege escalation.
8. Rotate `JWT_SECRET` and `INTERNAL_TOKEN` once, documenting exactly what breaks and how you roll without downtime (hint: think about accepting two keys during a rollover).
9. Write `docs/threat-model.md`: assets, who could attack, what you did, **what you did not do**.

## Acceptance criteria
- [ ] The app will not start in production mode with the default secret.
- [ ] CI fails on a committed secret and on a critical vulnerability.
- [ ] No plaintext secret exists in either repo's history.
- [ ] A pod in another namespace cannot reach `accounts`.
- [ ] You can state the top three remaining risks honestly.

## Break it on purpose
- Commit a fake AWS key on a branch and watch gitleaks catch it. Then learn why you must **rotate** a leaked key rather than just delete the commit.
- Apply a default-deny policy and watch everything break, then add the allows one by one.
- Run a container as root on purpose and compare with the hardened one.

## Extra experiments for the 10-service platform
- **Prove the gateway hides internals:** `curl` an `/internal/*` path and the `audit` or `fraud` hosts through the gateway and confirm you cannot reach them. Then ask: what protects those endpoints **inside** the cluster? (Answer: a shared token. What are its weaknesses, and what would replace it in production? Think mutual TLS, service accounts, a service mesh.)
- **Rotate `INTERNAL_TOKEN`:** seven services use it. Plan a rotation with no downtime and write the order of steps.
- **Cards:** the app stores only the last 4 digits. Explain why storing the full number would put you in PCI scope.
- **Audit:** it is meant to be an append-only record. What stops someone with database access from editing it? Design one control (separate database credentials, write-only role, WORM storage).
- **Least privilege:** give each service its own database user that can only touch its own database.

## Hints
- Known gaps in the demo app you can list in your threat model: no rate limiting or account lockout, JWT has no revocation, the demo `deposit` endpoint lets any logged-in user create money from nothing, no TLS inside the cluster, no audit log.
- Least privilege applies to IAM roles, CI tokens and Kubernetes service accounts.

## Cost
$0 locally.

## Interview talking points
Shift-left security, secrets management options and trade-offs, supply-chain risk, least privilege, defence in depth, what a leaked credential response looks like.
