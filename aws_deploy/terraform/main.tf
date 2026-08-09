# PrefectOS batch-ingest on AWS ap-south-1 — pilot-to-production deployment
# ---------------------------------------------------------------------------
# Creates: SQS main+DLQ, S3 bucket, IAM role (scoped Bedrock access),
# gateway EC2 (API + baseline workers), spot worker ASG scaling on queue depth,
# CloudWatch alarms. Uses the default VPC to stay simple; move to a private
# VPC + Bedrock PrivateLink endpoint when a client security review asks.
#
#   terraform init && terraform apply -var admin_cidr=<your-ip>/32
#
# NOTE: written for terraform >=1.5, provider aws ~>5.0. Review the plan
# before applying; NOT applied/validated in this sandbox.

terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } }
}

provider "aws" { region = var.region }

# ── variables ───────────────────────────────────────────────────────────────
variable "region"       { default = "ap-south-1" }
variable "admin_cidr"   { description = "Your IP as x.x.x.x/32 for SSH/API" }
variable "key_name"     { description = "Existing EC2 key pair name" }
variable "app_bucket_suffix" { default = "prefectos" }
variable "gateway_type" { default = "t3.large" }    # API + 2 baseline workers
variable "worker_type"  { default = "c7i.2xlarge" } # 8 vCPU burst workers
variable "max_workers"  { default = 6 }

data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter { name = "vpc-id"; values = [data.aws_vpc.default.id] }
}
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name"; values = ["al2023-ami-2023*-x86_64"] }
}
data "aws_caller_identity" "me" {}

# ── S3: uploads, outputs, app bundle ────────────────────────────────────────
resource "aws_s3_bucket" "app" {
  bucket = "${var.app_bucket_suffix}-${data.aws_caller_identity.me.account_id}"
}
resource "aws_s3_bucket_public_access_block" "app" {
  bucket = aws_s3_bucket.app.id
  block_public_acls = true; block_public_policy = true
  ignore_public_acls = true; restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = aws_s3_bucket.app.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}

# ── SQS: main queue + dead-letter ───────────────────────────────────────────
resource "aws_sqs_queue" "dlq" { name = "prefectos-ingest-dlq" }
resource "aws_sqs_queue" "ingest" {
  name                       = "prefectos-ingest"
  visibility_timeout_seconds = 30              # > 10s per-doc SLA
  receive_wait_time_seconds  = 10              # long polling
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3                    # 3 strikes -> DLQ -> HITL
  })
}

# ── IAM: instance role — least privilege incl. scoped Bedrock ──────────────
resource "aws_iam_role" "node" {
  name = "prefectos-node"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole",
                   Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "node" {
  name = "prefectos-node-policy"
  role = aws_iam_role.node.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvokeClaudeOnly"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.me.account_id}:inference-profile/global.anthropic.*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.me.account_id}:inference-profile/apac.anthropic.*"
        ]
      },
      {
        Sid    = "QueueAccess"
        Effect = "Allow"
        Action = ["sqs:SendMessage", "sqs:SendMessageBatch", "sqs:ReceiveMessage",
                  "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [aws_sqs_queue.ingest.arn, aws_sqs_queue.dlq.arn]
      },
      {
        Sid    = "DocBucket"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.app.arn, "${aws_s3_bucket.app.arn}/*"]
      },
      {
        Sid      = "Telemetry"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData", "logs:CreateLogGroup",
                    "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      }
    ]
  })
}
resource "aws_iam_instance_profile" "node" {
  name = "prefectos-node"
  role = aws_iam_role.node.name
}

# ── security groups ─────────────────────────────────────────────────────────
resource "aws_security_group" "gateway" {
  name   = "prefectos-gateway"
  vpc_id = data.aws_vpc.default.id
  ingress { from_port = 22;   to_port = 22;   protocol = "tcp"; cidr_blocks = [var.admin_cidr] }
  ingress { from_port = 8000; to_port = 8000; protocol = "tcp"; cidr_blocks = [var.admin_cidr] }
  egress  { from_port = 0; to_port = 0; protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }
}
resource "aws_security_group" "worker" {
  name   = "prefectos-worker"
  vpc_id = data.aws_vpc.default.id
  ingress { from_port = 22; to_port = 22; protocol = "tcp"; cidr_blocks = [var.admin_cidr] }
  egress  { from_port = 0; to_port = 0; protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }
}

# ── shared bootstrap (app pulled from S3: upload prefectos_app.zip first) ──
locals {
  bootstrap = <<-EOT
    #!/bin/bash
    set -e
    dnf install -y python3.11 python3.11-pip unzip
    aws s3 cp s3://${aws_s3_bucket.app.bucket}/app/prefectos_app.zip /opt/app.zip
    unzip -o /opt/app.zip -d /opt/prefectos
    cd /opt/prefectos/lc_lg_orchestrator_v2_Version6
    python3.11 -m pip install -q fastapi uvicorn pdfplumber pandas anthropic boto3
    cat > /etc/prefectos.env <<ENV
    INGEST_SQS_URL=${aws_sqs_queue.ingest.url}
    INGEST_SQS_DLQ_URL=${aws_sqs_queue.dlq.url}
    INGEST_S3_BUCKET=${aws_s3_bucket.app.bucket}
    AWS_REGION=${var.region}
    INGEST_LLM_PROVIDER=bedrock
    ROUTE_RESOLVER_PROVIDER=bedrock
    INGEST_EXCEPTION_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0
    ROUTE_RESOLVER_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0
    INGEST_WORKERS=$(nproc)
    ENV
  EOT
}

# ── gateway: API + baseline workers, always on ─────────────────────────────
resource "aws_instance" "gateway" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.gateway_type
  key_name               = var.key_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.gateway.id]
  iam_instance_profile   = aws_iam_instance_profile.node.name
  user_data = <<-EOT
    ${local.bootstrap}
    cat > /etc/systemd/system/prefectos-api.service <<UNIT
    [Unit]
    Description=PrefectOS batch-ingest API
    After=network.target
    [Service]
    EnvironmentFile=/etc/prefectos.env
    WorkingDirectory=/opt/prefectos/lc_lg_orchestrator_v2_Version6
    ExecStart=/usr/bin/python3.11 -m uvicorn server:app --host 0.0.0.0 --port 8000
    Restart=always
    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload && systemctl enable --now prefectos-api
  EOT
  tags = { Name = "prefectos-gateway" }
}

# ── burst workers: spot ASG, scale on queue depth, idle at zero ────────────
resource "aws_launch_template" "worker" {
  name_prefix   = "prefectos-worker-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.worker_type
  key_name      = var.key_name
  iam_instance_profile { name = aws_iam_instance_profile.node.name }
  vpc_security_group_ids = [aws_security_group.worker.id]
  instance_market_options { market_type = "spot" }   # queue makes spot safe
  user_data = base64encode(<<-EOT
    ${local.bootstrap}
    cat > /etc/systemd/system/prefectos-worker.service <<UNIT
    [Unit]
    Description=PrefectOS ingest worker
    After=network.target
    [Service]
    EnvironmentFile=/etc/prefectos.env
    WorkingDirectory=/opt/prefectos/lc_lg_orchestrator_v2_Version6
    ExecStart=/usr/bin/python3.11 -m batch_ingest.run_worker
    Restart=always
    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload && systemctl enable --now prefectos-worker
  EOT
  )
}

resource "aws_autoscaling_group" "workers" {
  name                = "prefectos-workers"
  min_size            = 0                       # scale-to-zero between bursts
  max_size            = var.max_workers
  desired_capacity    = 0
  vpc_zone_identifier = data.aws_subnets.default.ids
  launch_template { id = aws_launch_template.worker.id, version = "$Latest" }
  tag { key = "Name"; value = "prefectos-worker"; propagate_at_launch = true }
}

resource "aws_autoscaling_policy" "scale_out" {
  name                   = "queue-deep-add-workers"
  autoscaling_group_name = aws_autoscaling_group.workers.name
  policy_type            = "StepScaling"
  adjustment_type        = "ChangeInCapacity"
  step_adjustment { metric_interval_lower_bound = 0;    metric_interval_upper_bound = 1500; scaling_adjustment = 2 }
  step_adjustment { metric_interval_lower_bound = 1500; scaling_adjustment = 4 }
}
resource "aws_autoscaling_policy" "scale_in" {
  name                   = "queue-empty-remove-workers"
  autoscaling_group_name = aws_autoscaling_group.workers.name
  policy_type            = "StepScaling"
  adjustment_type        = "ExactCapacity"
  step_adjustment { metric_interval_upper_bound = 0; scaling_adjustment = 0 }
}

resource "aws_cloudwatch_metric_alarm" "queue_deep" {
  alarm_name          = "prefectos-queue-deep"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.ingest.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 500                     # ~2 users' batches queued
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_autoscaling_policy.scale_out.arn]
}
resource "aws_cloudwatch_metric_alarm" "queue_empty" {
  alarm_name          = "prefectos-queue-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.ingest.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5                       # 5 quiet minutes -> scale to 0
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_autoscaling_policy.scale_in.arn]
}

# ── outputs ────────────────────────────────────────────────────────────────
output "gateway_public_ip" { value = aws_instance.gateway.public_ip }
output "sqs_queue_url"     { value = aws_sqs_queue.ingest.url }
output "app_bucket"        { value = aws_s3_bucket.app.bucket }
