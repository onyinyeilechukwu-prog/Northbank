# Phase 11: Reliability, backup and chaos

**Maps to:** mentor Projects **6** (chaos) and **5** (backup/restore).

## Goal
Prove NorthBank survives failure, and that you can recover from the worst case: losing the database.

## Tools
`kubectl`, a chaos tool (Chaos Mesh or LitmusChaos, or plain `kubectl delete pod`), `pg_dump`/`pg_restore` or CronJob-based backups, a load tool (k6, hey or wrk), Grafana from Phase 9.

## Tasks
1. **Backups:** schedule automated Postgres backups (a Kubernetes CronJob writing to durable storage, or an S3 bucket if you are using AWS).
2. **Restore drill:** delete the database (in a safe environment), restore from backup, and verify balances. **A backup you have never restored is not a backup.** Record how long it took (your **RTO**) and how much data was lost (your **RPO**).
3. **Chaos experiments** (state a hypothesis first): kill a random pod; kill the `accounts` pod during a transfer; add network latency between `transactions` and `accounts`; stop Redis; fill a pod's memory.
4. **Load test:** write a script that registers users and performs transfers at increasing rates. Find the point where latency or errors climb. Look at Grafana while it runs.
5. Fix **one** weakness you find (examples: add retries with backoff, set sensible timeouts, tune replicas/limits, add a PodDisruptionBudget). Re-run the test to show improvement.
6. Write **runbooks** in `docs/runbooks/` for each alert from Phase 9: symptoms, likely causes, exact commands, escalation.
7. Run a **game day**: break something without telling yourself what, and fix it using only dashboards, logs and runbooks.
8. Write a blameless **postmortem** for one real failure you caused, using the template in `docs/postmortem-template.md` (create it: summary, impact, timeline, root cause, what went well, what did not, action items).

## Acceptance criteria
- [ ] A restore from backup is documented with measured RTO and RPO.
- [ ] Every chaos experiment has a hypothesis, a result and a conclusion.
- [ ] Each alert has a runbook someone else could follow at 3 a.m.
- [ ] You have one measured before/after improvement.

## Break it on purpose
All of the above is breaking it. Add: corrupt the backup file and see whether your restore script detects it; restore into the wrong database name.

## Extra experiments for the 10-service platform
- **Consumer catch-up:** stop `ledger`, make several transfers, start it again, and confirm the missing entries appear. Measure how long catch-up takes. (This works because each service reads the stream through its own consumer group.)
- **Duplicates:** use `XADD` to put the same event on the stream twice and confirm `ledger`, `notification` and `audit` each record it once.
- **Poison messages:** add garbage to the stream and watch each consumer log and drop it. Then design a **dead-letter stream** so bad events are kept for inspection, not lost.
- **Crashed consumer:** a consumer that dies mid-event leaves it "pending" and the current code never re-reads it. Look at `XPENDING` and learn `XAUTOCLAIM`; implement recovery.
- **Fail closed vs fail open:** stop `fraud` and make a transfer (503). Set `FRAUD_FAIL_OPEN=true` and repeat. Write down when each choice is right for a bank.
- **The loan payout gap:** `loans` pays out first, then saves the loan. Find the failure window, reproduce it if you can, and design a fix (save as `pending` first, or the **outbox pattern**).
- **The lost event:** stop Redis, make a transfer, restart Redis. The transfer exists but its event does not. Sketch an **outbox table** that closes this gap.

## Hints
- Think about the transfer flow: where could a crash leave things half done? (The database transaction in `accounts` protects the money; the lost Redis event is the known gap.)
- Retries are only safe because of idempotency keys. Explain why.

## Cost
$0 locally (or pennies on S3).

## Interview talking points
RTO/RPO, testing backups, chaos engineering principles (hypothesis, blast radius), capacity and load testing, blameless postmortems, how idempotency enables safe retries.
