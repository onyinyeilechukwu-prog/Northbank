# Phase 0: Repo, branching and workflow

**Maps to:** Week 3 (Git), Tickets 103 (hooks and branch protection).

## Goal
Turn this folder into a properly managed GitHub repository with a workflow that mirrors a real team: protected `main`, pull requests, and local guard rails.

## Tools
Git, GitHub, pre-commit hooks (the ones you already wrote), optionally the `pre-commit` framework.

## Tasks
1. Create a new **empty** GitHub repository named `northbank`. Do not add a README there (this repo has one).
2. `git init` here, make an initial commit on `main`, add the remote, push.
3. Add a `CODEOWNERS` file (you own everything for now) and a pull request template in `.github/pull_request_template.md` with: what changed, why, how it was tested, rollback plan.
4. Turn on **branch protection** for `main`: require a pull request, block direct pushes, and (after Phase 3) require the CI check to pass.
5. Install your **pre-commit** hook that blocks `PASSWORD` / `SECRET_KEY` in added lines, using the corrected version from Appendix A of your study guide. Test that it blocks.
6. Pick a branch naming convention (e.g. `feature/…`, `fix/…`, `chore/…`) and a commit message convention; write both in `CONTRIBUTING.md`.
7. Open your first PR (e.g. "Add CONTRIBUTING.md"), review it yourself, merge it with a **squash** merge.

## Acceptance criteria
- [ ] You cannot push straight to `main` (try it, read the error).
- [ ] `git log --oneline` on `main` reads like a story.
- [ ] Committing a line containing `SECRET_KEY=abc` is blocked locally.
- [ ] `.gitignore` stops `.env`, `*.pem` and `*.db` from being added (prove it with `git status` after creating one).
- [ ] `CONTRIBUTING.md` and the PR template exist.

## Break it on purpose
- Commit a fake secret with `--no-verify`. Observe that local hooks are **advisory**. Note this for Phase 10, where CI scanning is the real gate.
- Create a merge conflict between two branches on the same line of the README, then resolve it by hand.

## Hints
- `git branch -M main`, `git remote add origin <url>`, `git push -u origin main`.
- A hook is a file in `.git/hooks/` named exactly `pre-commit`, with the executable bit set.
- Branch protection lives in GitHub: Settings, Branches (or Rules).

## Cost
$0.

## Interview talking points
Why protected branches and PR review exist; the difference between local hooks and server-side enforcement; merge vs squash vs rebase and when you would use each.
