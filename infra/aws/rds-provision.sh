#!/usr/bin/env bash
# Provision RDS for PostgreSQL (replacing Supabase as the app database — Auth
# stays on Supabase for now) plus the networking pulse-api needs to reach it
# privately: an App Runner VPC connector and two security groups.
#
# Idempotent-ish: safe to re-run, skips resources that already exist by name.
# After this finishes, run the schema/data migration steps in
# infra/aws/README.md before cutting pulse-api over.
set -euo pipefail

REGION="us-east-1"
VPC_ID="vpc-09faaebb065babaa8"
DB_INSTANCE_ID="pulse-db"
DB_NAME="pulse"
MASTER_USERNAME="pulseadmin"
APPRUNNER_SG_NAME="pulse-apprunner-sg"
RDS_SG_NAME="pulse-rds-sg"
SUBNET_GROUP_NAME="pulse-db-subnet-group"
VPC_CONNECTOR_NAME="pulse-vpc-connector"

echo "== Subnets in $VPC_ID =="
# subnet-00915037b1a22d60c (us-east-1e) is excluded: App Runner VPC connectors
# don't support that AZ in this account (CreateVpcConnector returns
# InvalidRequestException for it) — confirmed by trial during initial setup.
SUBNET_IDS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[?SubnetId!='subnet-00915037b1a22d60c'].SubnetId" --output text)
echo "$SUBNET_IDS"

echo "== Security group: $APPRUNNER_SG_NAME =="
APPRUNNER_SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$APPRUNNER_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
if [[ "$APPRUNNER_SG_ID" == "None" || -z "$APPRUNNER_SG_ID" ]]; then
  APPRUNNER_SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$APPRUNNER_SG_NAME" --vpc-id "$VPC_ID" \
    --description "Egress SG for the pulse-api App Runner VPC connector" \
    --query 'GroupId' --output text)
fi
echo "$APPRUNNER_SG_ID"

echo "== Security group: $RDS_SG_NAME =="
RDS_SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$RDS_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
if [[ "$RDS_SG_ID" == "None" || -z "$RDS_SG_ID" ]]; then
  RDS_SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$RDS_SG_NAME" --vpc-id "$VPC_ID" \
    --description "Inbound 5432 only from pulse-apprunner-sg" \
    --query 'GroupId' --output text)
fi
echo "$RDS_SG_ID"

echo "== Ingress: 5432 on $RDS_SG_NAME from $APPRUNNER_SG_NAME =="
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$RDS_SG_ID" --protocol tcp --port 5432 \
  --source-group "$APPRUNNER_SG_ID" 2>/dev/null \
  || echo "(rule already present)"

echo "== DB subnet group: $SUBNET_GROUP_NAME =="
if ! aws rds describe-db-subnet-groups --region "$REGION" \
    --db-subnet-group-name "$SUBNET_GROUP_NAME" >/dev/null 2>&1; then
  aws rds create-db-subnet-group --region "$REGION" \
    --db-subnet-group-name "$SUBNET_GROUP_NAME" \
    --db-subnet-group-description "Default VPC subnets for pulse-db" \
    --subnet-ids $SUBNET_IDS >/dev/null
fi
echo "ok"

echo "== RDS instance: $DB_INSTANCE_ID =="
if ! aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" >/dev/null 2>&1; then
  aws rds create-db-instance --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --db-name "$DB_NAME" \
    --engine postgres \
    --engine-version 16 \
    --db-instance-class db.t4g.micro \
    --allocated-storage 20 \
    --storage-type gp3 \
    --master-username "$MASTER_USERNAME" \
    --manage-master-user-password \
    --vpc-security-group-ids "$RDS_SG_ID" \
    --db-subnet-group-name "$SUBNET_GROUP_NAME" \
    --no-multi-az \
    --no-publicly-accessible \
    --backup-retention-period 7 \
    --no-deletion-protection \
    --tags Key=project,Value=pulse >/dev/null
  echo "create-db-instance submitted, waiting for it to become available (~5-10 min)..."
else
  echo "(already exists)"
fi
aws rds wait db-instance-available --region "$REGION" --db-instance-identifier "$DB_INSTANCE_ID"

ENDPOINT=$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)
SECRET_ARN=$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" \
  --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)

echo "== App Runner VPC connector: $VPC_CONNECTOR_NAME =="
CONNECTOR_ARN=$(aws apprunner list-vpc-connectors --region "$REGION" \
  --query "VpcConnectors[?VpcConnectorName=='$VPC_CONNECTOR_NAME'].VpcConnectorArn | [0]" \
  --output text 2>/dev/null || echo "None")
if [[ "$CONNECTOR_ARN" == "None" || -z "$CONNECTOR_ARN" ]]; then
  CONNECTOR_ARN=$(aws apprunner create-vpc-connector --region "$REGION" \
    --vpc-connector-name "$VPC_CONNECTOR_NAME" \
    --subnets $SUBNET_IDS \
    --security-groups "$APPRUNNER_SG_ID" \
    --query 'VpcConnector.VpcConnectorArn' --output text)
fi
echo "$CONNECTOR_ARN"

cat <<SUMMARY

== Done ==
RDS endpoint:        $ENDPOINT
Master secret ARN:   $SECRET_ARN   (aws secretsmanager get-secret-value --secret-id "$SECRET_ARN")
VPC connector ARN:   $CONNECTOR_ARN
pulse-rds-sg:        $RDS_SG_ID
pulse-apprunner-sg:  $APPRUNNER_SG_ID

Next: build schema (alembic upgrade head against this endpoint), load data from
Supabase, then attach the VPC connector to pulse-api and flip DATABASE_URL.
See infra/aws/README.md.
SUMMARY
