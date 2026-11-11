# Phase 8: GitOps with Argo CD

**Maps to:** mentor **Project 1** (GitOps).

## Goal
Git becomes the single source of truth for what runs in the cluster. Nobody runs `kubectl apply` by hand; a controller reconciles the cluster to match Git.

## Tools
Argo CD (installed into `kind`), a separate **config repo** (recommended) or a folder, the Helm chart from Phase 7.

## Tasks
1. Install Argo CD into your `kind` cluster; log in to its UI.
2. Create a second repository, `northbank-gitops`, holding environment folders (e.g. `dev/`, `prod/`) with Helm values or manifests that reference **image tags**.
3. Create an Argo CD **Application** pointing at it, with **automated sync**, **self-heal** and **prune** enabled.
4. Change the CI pipeline: after building an image, CI **opens a PR (or commits) to the gitops repo** updating the image tag, instead of deploying directly.
5. Demonstrate the full loop: change code, PR, CI builds, tag updated in config repo, Argo syncs, new version runs.
6. Try an **app-of-apps** or ApplicationSet structure for dev and prod.

## Acceptance criteria
- [ ] A merge produces a deployment with **no manual kubectl or helm commands**.
- [ ] Manually editing a Deployment in the cluster gets reverted by self-heal.
- [ ] Rolling back is a `git revert`.
- [ ] You can show Git history as the audit trail of every change.

## Break it on purpose
- `kubectl scale` a deployment by hand and watch Argo revert it.
- Commit invalid YAML to the config repo and see how Argo reports it.
- Delete a manifest from Git and watch **prune** remove the resource.
- Point the Application at a wrong path.

## Hints
- Keep **application code** and **deployment config** in separate repos so config changes do not trigger code builds.
- Argo CD uses its own CRDs; read the `Application` spec fields before writing one.
- Never commit raw secrets to the config repo (Phase 10 solves this properly).

## Cost
$0.

## Interview talking points
Push vs pull deployments, drift detection and self-heal, why GitOps improves audit and rollback, separation of app and config repos, how secrets work under GitOps.
