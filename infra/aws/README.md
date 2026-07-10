# Pulse backend on AWS

The production API runs on **AWS App Runner** (`us-east-1`, same region as
Supabase), replacing the homelab compose deployment. Postgres and Auth stay on
Supabase. This mirrors what prod actually ran: the API container only — no
Celery worker or Redis (add an ECS service + ElastiCache when those go live).

## Topology

| Piece | Where |
|---|---|
| Container image | ECR `761018860175.dkr.ecr.us-east-1.amazonaws.com/pulse-api` |
| Runtime | App Runner service `pulse-api` (0.25 vCPU / 0.5 GB, auto-deploys `:latest`) |
| Secrets | SSM Parameter Store, SecureStrings under `/pulse/<KEY>` |
| Non-secret env | Set directly on the App Runner service (see below) |
| CI deploy | `.github/workflows/aws-deploy.yml` → OIDC role `pulse-github-deploy` → ECR push |
| Health check | HTTP `GET /api/health` |
| DB / Auth | Supabase (unchanged) |

IAM roles: `pulse-apprunner-ecr-access` (pull image), `pulse-apprunner-instance`
(read `/pulse/*` SSM params), `pulse-github-deploy` (CI image push, trusted only
for `repo:anoshmisiosdev/Pulse` on `main`).

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

Roughly $5–15/mo at current traffic: App Runner bills the 0.25 vCPU instance
only while serving requests (plus a small provisioned-memory charge when idle);
ECR storage is pennies.
