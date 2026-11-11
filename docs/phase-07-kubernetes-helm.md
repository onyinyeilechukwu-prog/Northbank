# Phase 7: Kubernetes and Helm

**Maps to:** Week 12, mentor Projects 2 and 5 groundwork.

## Goal
Run NorthBank on Kubernetes the way a team would, then package it with Helm.

## Tools
`kind` (Kubernetes in Docker, free), `kubectl`, Helm, an ingress controller, the images from Phase 3.

## Tasks
1. Create a local cluster with `kind` (a config mapping host ports for ingress).
2. Load or pull your images into the cluster.
3. Write manifests for each service: **Deployment** (replicas, resource requests and limits, **liveness probe on `/health`, readiness probe on `/ready`**), **Service**, and a **ConfigMap**/**Secret** for environment variables.
4. Run Postgres and Redis in the cluster (a StatefulSet with a PersistentVolumeClaim for Postgres is the learning goal; note that production teams usually use a managed database).
5. Add an **Ingress** replacing the nginx gateway.
6. Use a **namespace** (`northbank`) and label everything consistently.
7. Add a **HorizontalPodAutoscaler** for `transactions` (needs metrics-server).
8. Convert the manifests into a **Helm chart** with a `values.yaml` and separate `values-dev.yaml` / `values-prod.yaml` overrides. Use templates so you do not copy-paste ten deployments.
9. Run the smoke test through the ingress.

## Acceptance criteria
- [ ] `helm install` from a clean cluster gives a working system.
- [ ] Killing a pod (`kubectl delete pod`) causes no user-visible outage when replicas > 1.
- [ ] A rolling update (`helm upgrade` with a new image tag) completes with no failed requests.
- [ ] `helm rollback` works.
- [ ] Secrets are not in the chart's default values.

## Break it on purpose
- Set a memory limit too low and watch **OOMKilled**.
- Break the readiness probe path and watch the pod stay `Running` but receive no traffic.
- Point `DATABASE_URL` at a wrong host and read the logs and `kubectl describe` events.
- Set a wrong image tag and diagnose `ImagePullBackOff`.
- Use `kubectl rollout undo`.

## Hints
- `kubectl get pods -w`, `describe`, `logs`, `exec`, `port-forward`, `rollout status`.
- `helm create` generates a scaffold; delete what you do not need.
- Probes: readiness decides traffic, liveness decides restarts. Using the wrong one is a classic mistake.
- Re-read your Week 12 notes for object definitions.

## Cost
$0 locally.

## Interview talking points
Pods vs Deployments vs Services, probes, requests vs limits, rolling updates, config and secrets, Helm templating and values, why StatefulSets exist.
