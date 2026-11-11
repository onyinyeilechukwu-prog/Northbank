# Phase 5: Configuration management (Ansible)

**Maps to:** Bonus Ansible lesson, mentor Project 8.

## Goal
Terraform created the server. Ansible **configures** it: packages, users, Docker, firewall, and deploying NorthBank, all idempotent and repeatable.

## Tools
Ansible, SSH, YAML (your YAML lesson), the server from Phase 4 or a local VM.

## Tasks
1. Create `infra/ansible/` with an **inventory** (static file first; optionally generate it from Terraform output), `ansible.cfg` and `site.yml`.
2. Test connectivity with the `ping` module.
3. Write **roles**: `common` (updates, useful packages, time zone, a non-root admin user, SSH hardening), `firewall` (ufw: allow SSH **before** enabling; see the Appendix A item on checking for an ALLOW rule), `docker` (install Docker Engine, add the user to the `docker` group), `northbank` (copy the Compose file and `.env`, pull images, `docker compose up -d`).
4. Use **variables** and **templates** (Jinja2) for the `.env` file; keep secrets in **Ansible Vault**, not plain text.
5. Use **handlers** (restart SSH only when its config changed).
6. Run the playbook twice. The second run must report **zero changes**. That is idempotency.
7. Run with `--check --diff` first, as a dry run.

## Acceptance criteria
- [ ] Running `site.yml` against a **brand-new** server fully provisions NorthBank.
- [ ] A second run changes nothing.
- [ ] No secret is stored in plain text in the repo.
- [ ] You can explain each role in one sentence.

## Break it on purpose
- Enable ufw **without** allowing SSH on a throwaway VM and learn what lock-out feels like (Ticket 102 exists for this).
- Edit a config file by hand on the server, re-run the playbook, and watch Ansible put it back.
- Use `shell:` for something and then redo it with a proper module; compare idempotency.
- Run with a wrong Vault password and read the error.

## Hints
- Prefer real modules (`apt`, `user`, `ufw`, `template`, `copy`, `systemd`, `community.docker.*`) over `shell`/`command`.
- `ansible-playbook -i inventory site.yml --check --diff`, `ansible-vault create|edit|encrypt`.
- `ansible-lint` is worth running.

## Cost
Same server as Phase 4. Stop or destroy it when you are done.

## Interview talking points
Terraform vs Ansible (provisioning vs configuration), idempotency, push vs pull models, roles, Vault, and how you avoid configuration drift.
