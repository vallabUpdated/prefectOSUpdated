# PrefectOS on AWS + Bedrock (ap-south-1) — deployment kit

Architecture: gateway EC2 (FastAPI + baseline workers, always on) · SQS
main+DLQ queue · S3 for uploads/outputs (shared storage for multi-VM
workers) · spot worker ASG scaling 0->6 on queue depth · Bedrock via IAM
role (NO API keys stored anywhere on the boxes).

## Code changes already in this build
- batch_ingest/queue_sqs.py — SQS backend (long poll, visibility timeout,
  DLQ drain -> escalated_hitl). Selected automatically when INGEST_SQS_URL set.
- worker.py — ack-after-terminal-state; transparent s3:// document localize.
- api.py — uploads mirrored to S3 when INGEST_S3_BUCKET set.
- run_worker.py — worker-only entrypoint for ASG instances.
- llm_exceptions.py / pooled_agents.py / routing.py — INGEST_LLM_PROVIDER=
  bedrock / ROUTE_*_PROVIDER=bedrock -> AnthropicBedrock client using the
  instance IAM role. Tested with moto (fake AWS): SQS submit/process/ack
  and mixed s3://+local batches pass.

## Deploy order
1. AWS console -> Bedrock -> Model access -> enable Anthropic Claude models
   (one-time, per account/region).
2. Zip this repo as prefectos_app.zip.
3. cd aws_deploy/terraform && terraform init &&
   terraform apply -var admin_cidr=<your-ip>/32 -var key_name=<keypair>
4. aws s3 cp prefectos_app.zip s3://<app_bucket_output>/app/
5. Reboot gateway (or terraform taint) so user_data picks up the bundle.
6. Smoke test:
   curl -F user_id=pilot -F files=@statement.pdf \
        http://<gateway_ip>:8000/ingest/batches

## Scaling behaviour
- Queue > 500 docs for 1 min  -> +2 spot workers; > 2000 -> +4.
- Queue < 1 for 5 min         -> workers scale to 0 (spot bill stops).
- Spot interruption is safe: unacked SQS messages reappear after the 30s
  visibility timeout and another worker takes them.
- 3 failed attempts on a doc  -> DLQ -> drain_dlq seals escalated_hitl.

## Cost picture (moderate pilot->prod volume)
Gateway t3.large 24/7 ~₹6-7K/mo · burst c7i.2xlarge spot ~₹6-8/hr only
while queues are deep · SQS/S3 negligible · Bedrock ~₹125 per 5,000-doc
burst on Haiku with cached prompts. Typical light-production month: ₹15-40K.

## Security notes
- IAM policy grants bedrock:InvokeModel ONLY on anthropic.* model and
  global./apac. inference-profile ARNs — nothing else in Bedrock.
- No ANTHROPIC_API_KEY anywhere; the instance role signs Bedrock calls.
- API/SSH restricted to admin_cidr. Before client traffic: put an ALB +
  ACM TLS cert in front of :8000 and tighten to 443.
- Data residency: documents at rest stay in ap-south-1 (S3/EBS); Bedrock
  global profile routes inference outside India. For apac-only routing use
  the apac.anthropic... profile id; verify model availability first.
