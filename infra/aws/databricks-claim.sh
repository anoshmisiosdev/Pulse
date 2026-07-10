#!/usr/bin/env bash
# Arm the Databricks cross-account role so YOUR Databricks account can claim it.
#
# The role is created with a placeholder external ID, which makes it unclaimable.
# After signing up at https://accounts.databricks.com, copy your Databricks
# account ID (a UUID, shown in the account console user menu) and run:
#
#   infra/aws/databricks-claim.sh <databricks-account-id>
#
# The external ID must equal your Databricks account ID — that's how AWS knows
# it's *your* Databricks account assuming the role and not someone else's.
set -euo pipefail

DATABRICKS_ACCOUNT_ID="${1:?usage: databricks-claim.sh <databricks-account-id>}"

aws iam update-assume-role-policy \
  --role-name pulse-databricks-cross-account \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Principal\": {\"AWS\": \"arn:aws:iam::414351767826:root\"},
      \"Action\": \"sts:AssumeRole\",
      \"Condition\": {\"StringEquals\": {\"sts:ExternalId\": \"${DATABRICKS_ACCOUNT_ID}\"}}
    }]
  }"

echo "Armed. In the Databricks account console use:"
echo "  Credential configuration role ARN: arn:aws:iam::761018860175:role/pulse-databricks-cross-account"
echo "  Storage configuration bucket:      pulse-databricks-root-761018860175"
