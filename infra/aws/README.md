# Pulse backend on AWS

The production API runs on **AWS App Runner** (`us-east-1`, same region as
Supabase), replacing the homelab compose deployment. This mirrors what prod
actually ran: the API container only — no Celery worker or Redis (add an ECS
service + ElastiCache when those go live).

**Database** is now **AWS RDS for PostgreSQL 16** (`pulse-db`), reached over the
private VPC via a App Runner VPC connector — it is not publicly accessible.
**Auth stays on Supabase** (unchanged; see `SUPABASE_*` env vars).

**RAG embeddings** (business-knowledge retrieval for campaign generation, see
`backend/app/services/rag/`) use **AWS Bedrock** (`cohere.embed-v4:0`, 1536-dim)
via the ambient AWS credential chain — the App Runner instance role holds
`bedrock:InvokeModel` scoped to that one model ARN (policy `pulse-bedrock-embed`
on role `pulse-apprunner-instance`). Vectors are stored in `pulse-db` via the
Postgres `pgvector` extension (`business_knowledge` table). Chat generation
itself is unaffected — that still goes through TokenMart.

## Topology

| Piece | Where |
|---|---|
| Container image | ECR `761018860175.dkr.ecr.us-east-1.amazonaws.com/pulse-api` |
| Runtime | App Runner service `pulse-api` (0.25 vCPU / 0.5 GB, auto-deploys `:latest`) |
| Secrets | SSM Parameter Store, SecureStrings under `/pulse/<KEY>` |
| Non-secret env | Set directly on the App Runner service (see below) |
| CI deploy | `.github/workflows/aws-deploy.yml` → OIDC role `pulse-github-deploy` → ECR push |
| Health check | HTTP `GET /api/health` |
| DB | AWS RDS Postgres `pulse-db` (`us-east-1`, private, `db.t4g.micro`), reached via VPC connector `pulse-vpc-connector` |
| Auth | Supabase (unchanged) |

IAM roles: `pulse-apprunner-ecr-access` (pull image), `pulse-apprunner-instance`
(read `/pulse/*` SSM params), `pulse-github-deploy` (CI image push, trusted only
for `repo:anoshmisiosdev/Pulse` on `main`).

Networking: `pulse-rds-sg` allows inbound 5432 only from `pulse-apprunner-sg`;
the RDS instance has `PubliclyAccessible=false`. App Runner's egress is set to
`VPC` via `pulse-vpc-connector`, which also uses `pulse-apprunner-sg`. Schema
is created by `app/main.py`'s `create_all` on startup (idempotent) plus Alembic
for anything added after `20260709_0001` — run `alembic upgrade head` against
`DATABASE_URL` for those. To run Alembic/psql against `pulse-db` from outside
the VPC (it has no bastion yet), temporarily flip it public and restrict
`pulse-rds-sg` to your IP, then revert both — see `rds-provision.sh` history
in git for the exact commands used during the initial cutover.

**Internet egress from App Runner**: switching egress to `VPC` mode (required
for private RDS access) means App Runner ONLY reaches what's routable inside
the VPC — RDS, yes; anything external (Supabase JWKS for RS256 token
verification, AWS Bedrock, Stripe/Square/Resend/Twilio/Perplexity/TokenMart/
Anthropic) needs real internet egress, which a VPC-only connector doesn't have
by default. Fixed via NAT Gateway `pulse-nat` (subnet `subnet-00915037b1a22d60c`
— the AZ excluded from the connector itself, so it's dedicated purely to
hosting the NAT) + route table `pulse-apprunner-private-rt`, which routes
`0.0.0.0/0` through it and is associated with all 5 of the connector's
subnets. Without this, requests needing an external call hang until timeout
(minutes) rather than failing fast — this is what caused the "stuck on
customer loading" incident on 2026-07-12: RS256 JWT verification (JWKS fetch)
and Bedrock embedding calls were both silently hanging. If you ever recreate
the VPC connector or its subnets, this NAT setup needs to be redone too.

## Everyday operations

**Deploy:** merge to `main` touching `backend/**`. CI pushes the image; App
Runner rolls it out automatically. Manual deploy:

```bash
cd backend
docker build --platform linux/amd64 -t 761018860175.dkr.ecr.us-east-1.amazonaws.com/pulse-api:latest .
aws ecr get-login-password | docker login --username AWS --password-stdin 761018860175.dkr.ecr.us-east-1.amazonaws.com
docker push 761018860175.dkr.ecr.us-east-1.amazonaws.com/pulse-api:latest
```

(`--platform linux/amd64` is mandatory — App Runner is x86_64 only.)

**Change a secret:** edit the repo-root `.env`, then

```bash
infra/aws/push-env-to-ssm.sh
aws apprunner start-deployment --service-arn <service-arn>   # restart to pick up
```

**Change a non-secret env var:** App Runner console → pulse-api →
Configuration → Environment variables (or `aws apprunner update-service`).

**Logs:** CloudWatch log groups `/aws/apprunner/pulse-api/*` — `application`
for the app, `service` for App Runner lifecycle events.

**Status / URL:**

```bash
aws apprunner list-services
aws apprunner describe-service --service-arn <arn> --query 'Service.{Status:Status,Url:ServiceUrl}'
```

## Cutover checklist (homelab → AWS)

1. Service healthy: `curl https://<apprunner-url>/api/health`.
2. Custom domain `api.riyanshomelab.com` associated in App Runner; add the
   CNAME + certificate-validation records it prints to your DNS.
3. Wait for the domain status to become `active`, then confirm
   `curl https://api.riyanshomelab.com/api/health` hits App Runner.
4. Square/Stripe OAuth redirect URLs keep working unchanged (same hostname).
5. Decommission the homelab: delete `.github/workflows/docker-image.yml`
   (self-hosted runner deploy), stop the compose stack, remove the NPM proxy
   host.

## Cost

Roughly $5–15/mo at current traffic for App Runner + ECR (bills the 0.25 vCPU
instance only while serving requests, plus a small provisioned-memory charge
when idle; ECR storage is pennies) — **plus ~$32-35/mo for the NAT Gateway**
(hourly charge regardless of traffic, plus ~$0.045/GB processed), which is
required for any internet egress from the VPC-connected App Runner service.
