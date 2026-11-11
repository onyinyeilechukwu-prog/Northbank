# Phase 9: Monitoring and observability

**Maps to:** mentor Projects **3** (monitoring) and **7** (observability).

## Goal
Know whether NorthBank is healthy, **before** a customer tells you. Build dashboards, logs and alerts, and define what "healthy" means with SLOs.

## Tools
Prometheus, Grafana, Alertmanager, Loki (+ Promtail or Grafana Alloy) for logs, optionally OpenTelemetry/Tempo for traces. Run via the `kube-prometheus-stack` Helm chart on `kind`, or via Compose first.

## What the app already gives you
Each service exposes `/metrics` with `http_requests_total{service,method,path,status}` and a latency histogram (`http_request_duration_seconds`), and writes **JSON logs**. Read `services/*/app/observability.py` to see exactly which metric names and labels exist.

## Tasks
1. Deploy Prometheus and Grafana. Configure Prometheus to **scrape** all ten services (a ServiceMonitor in Kubernetes, or a scrape config in Compose).
2. Build a Grafana dashboard using the **RED method** per service: **R**ate (requests/sec), **E**rrors (5xx ratio), **D**uration (p95 latency from the histogram). Write the PromQL yourself.
3. Add infrastructure panels: CPU, memory, restarts per pod.
4. Add **Loki** and make logs searchable by service; add a Grafana panel linking from a metric spike to the matching logs.
5. Define two **SLOs** in `docs/slos.md`, for example "99% of `POST /transfers` return non-5xx over 30 days" and "95% of requests under 500 ms". Explain the **error budget**.
6. Write **alert rules** (Alertmanager): high 5xx ratio, high p95 latency, a service down (`up == 0`), pod crash looping. Each alert needs a severity, a summary, and a **runbook link** (see Phase 11).
7. Send alerts to a real channel (Slack webhook or email) and trigger one on purpose.
8. Optional: add tracing with OpenTelemetry and view a request across services.

## Acceptance criteria
- [ ] One dashboard answers "is NorthBank healthy right now?" in five seconds.
- [ ] Killing a service fires an alert within your chosen window and **resolves** when it returns.
- [ ] You can go from an alert, to the dashboard, to the logs of the failing service.
- [ ] SLOs are written down with numbers, not adjectives.

## Break it on purpose
- Stop `accounts`; watch `transactions` 503s climb on the dashboard and the alert fire.
- Add `time.sleep(1)` to one endpoint (on a branch) and see it in p95 latency.
- Make a service return 500 for a fraction of requests and watch the error-ratio panel.
- Create a noisy alert and then fix it (alert fatigue is a real problem).

## Extra experiments for the 10-service platform
- Build one **service map** panel: which service calls which (`transactions` to `fraud` and `accounts`, and so on). Draw it from the metrics, then compare with the architecture diagram.
- The app does **not** export event-bus health. Measure it yourself: Redis Streams commands such as `XLEN`, `XPENDING` and `XINFO GROUPS` show how far behind each consumer group is. Decide how you would get "consumer lag" into Prometheus (a small exporter, or a metric you add to the app via a PR).
- Alert when the **fraud** deny ratio suddenly jumps (could be an attack, or a bad rule change).
- Add a business metric of your own, for example transfers completed per minute, and think about why a business dashboard is different from a health dashboard.

## Hints
- `rate(http_requests_total[5m])`, `histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket[5m])))`.
- Alert on **symptoms users feel** (errors, latency), not only causes (CPU).
- Cardinality: that is why the app uses the **route template** as the `path` label, not the raw URL. Be ready to explain it.

## Cost
$0 locally.

## Interview talking points
Metrics vs logs vs traces, RED and USE methods, SLI/SLO/error budget, alert design, cardinality, and what you would alert on for a payments system.
