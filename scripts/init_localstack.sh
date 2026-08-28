#!/bin/bash
# Provisions the local S3 bucket and DynamoDB table inside LocalStack.
# LocalStack runs this automatically once its services are ready.
# Keep these names in sync with S3_BUCKET / DYNAMODB_TABLE in .env.local.
set -euo pipefail

BUCKET="${S3_BUCKET:-papaclaude-local}"
TABLE="${DYNAMODB_TABLE:-papaclaude-local}"

echo "Creating S3 bucket: ${BUCKET}"
awslocal s3 mb "s3://${BUCKET}" || true

echo "Creating DynamoDB table: ${TABLE}"
awslocal dynamodb create-table \
  --table-name "${TABLE}" \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST || true

echo "LocalStack init complete."
