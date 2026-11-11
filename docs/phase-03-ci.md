# Phase 3: Continuous Integration

**Maps to:** Week 7 (GitHub Actions), mentor Project 4 groundwork.

## Goal
Every pull request automatically lints, tests, builds and scans the code, and every merge to `main` publishes versioned images. A broken PR must be impossible to merge.

## Tools
GitHub Actions, a linter (e.g. ruff), pytest, Docker Buildx, **Trivy** (vulnerability scan), GitHub Container Registry (GHCR).

## Tasks
1. Create `.github/workflows/ci.yml` triggered on `pull_request` and `push` to `main`.
2. Use a **matrix** so the ten services are tested in parallel from one job definition.
3. Steps per service: checkout, set up Python with **pip caching**, install requirements and dev requirements, lint, run pytest.
4. Add a job that **builds each Docker image** (no push on PRs).
5. Add a **Trivy** scan of each built image; fail the job on `CRITICAL` findings (decide how you treat `HIGH`, and write the decision down).
6. On merge to `main` only, **push** images to GHCR, tagged with the **commit SHA** (and optionally `latest`).
7. Give the workflow **least-privilege** `permissions:`; only the push job gets `packages: write`.
8. In branch protection, make these checks **required**.
9. Add a status badge to the README.

## Acceptance criteria
- [ ] A PR with a failing test shows a red check and cannot be merged.
- [ ] A PR that only touches one service still gets sensible results (bonus: use path filters).
- [ ] After merging, images with SHA tags appear in your GHCR packages.
- [ ] No long-lived credentials are stored in the repo; the push uses the built-in `GITHUB_TOKEN`.
- [ ] Total CI time is reasonable thanks to caching (note before and after).

## Break it on purpose
- Push a PR that makes a test fail; read the log; fix it.
- Add a vulnerable old dependency pin in one service and watch Trivy complain.
- Remove the `permissions:` block and note the default token's scope.
- Pin an action to a version tag that does not exist and read the error (Appendix A, item 8).

## Hints
- `uses:` lines should be pinned to a **real** version (check each action's releases page) or a commit SHA.
- `docker/build-push-action`, `docker/login-action`, `docker/metadata-action` are the usual trio; read their docs examples.
- Compose-style secrets are not needed here: `secrets.GITHUB_TOKEN` exists automatically.
- Image names on GHCR must be lowercase.

## Cost
$0 (GitHub Actions free minutes are generous for a small public repo; check current terms for private repos).

## Interview talking points
CI vs CD, why tag images by commit SHA instead of `latest`, matrix builds, caching, least-privilege tokens, shift-left security, and what "required status check" means.

## Note
Action names and options change. Treat the hints as pointers and read each action's current README.
