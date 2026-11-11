# Phase 4: Infrastructure as Code (Terraform)

**Maps to:** Weeks 8–9, 11 (AWS, Terraform).

## Goal
Create the cloud environment for NorthBank from code: repeatable, reviewable, destroyable.

## Tools
Terraform, AWS (VPC, EC2, security groups, S3, IAM), AWS CLI.

## Cost warning (read first)
Set a **budget alert** before starting. Use the smallest instances. **Run `terraform destroy` at the end of every session.** Avoid NAT gateways and load balancers while learning: they bill hourly. Check your own account's current free-tier terms (Appendix A, item 9).

## Tasks
1. Create a `infra/terraform/` folder. Configure the AWS provider with a **pinned version** and a `required_version` for Terraform.
2. Set up **remote state**: an S3 bucket (versioned, encrypted, public access blocked). Decide how you handle state locking and write down your choice.
3. Build a module (or well-organised files) for: a VPC with one public subnet, an internet gateway and route table; a security group allowing SSH **only from your IP** and HTTP from anywhere; one EC2 instance (Ubuntu) with a key pair, tags and an IAM instance profile.
4. Use **variables** (with types and descriptions), **outputs** (public IP) and a `terraform.tfvars` that is git-ignored.
5. Add tags (`Project=northbank`, `Owner=<you>`, `Env=dev`) to everything, using `default_tags`.
6. Run `fmt`, `validate`, `plan`. Read the plan line by line before `apply`.
7. Add a CI job (extend Phase 3) that runs `terraform fmt -check`, `validate` and `plan` on PRs touching `infra/`.
8. `destroy`, then re-apply to prove it is reproducible.

## Acceptance criteria
- [ ] A fresh `terraform apply` produces a reachable server with no manual console clicking.
- [ ] State lives remotely; `.tfstate` is not in git.
- [ ] SSH is not open to `0.0.0.0/0`.
- [ ] Every resource is tagged.
- [ ] `terraform destroy` leaves nothing behind (verify in the console and with the cost checklist in Appendix D).

## Break it on purpose
- Change the instance type in the console by hand, then run `plan` and read the **drift**.
- Delete the security group by hand and see what Terraform wants to do.
- Run two `apply`s at once (or simulate) and learn why locking matters.
- Rename a resource in code and observe the destroy/create it implies; learn what `terraform state mv` and `moved` blocks are for.

## Hints
- `terraform init`, `fmt`, `validate`, `plan -out`, `apply`, `destroy`.
- Use a data source to find the current Ubuntu AMI instead of hard-coding an ID.
- Your public IP: look it up, then write it as a `/32`.
- Never put keys in `.tf` files. Use your AWS CLI profile or environment variables.

## Interview talking points
Declarative vs imperative, state and why it is sensitive, drift, modules, plan/apply review as a change-control gate, and what you would do if state were lost.
