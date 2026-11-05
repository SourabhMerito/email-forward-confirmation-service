# Lambda container image for job type 15 (email forward confirmation).
# Only requests + beautifulsoup4 on top of the AWS Lambda Python base image (boto3 is built in).
FROM public.ecr.aws/lambda/python:3.12

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt -t ${LAMBDA_TASK_ROOT}

COPY handler.py ${LAMBDA_TASK_ROOT}/
COPY config ${LAMBDA_TASK_ROOT}/config
COPY services ${LAMBDA_TASK_ROOT}/services
COPY utils ${LAMBDA_TASK_ROOT}/utils

# Secrets baked from GitHub Actions secrets at build time, as in the autopilot and
# txn-analysis-service images. Anything set on the Lambda function's configuration overrides these.
# The jigsaw-api callback URL is not baked in: it comes from each event's `apiLink`.
ARG ENVIRONMENT
ARG GMAIL_CLIENT_ID
ARG GMAIL_CLIENT_SECRET
ARG GMAIL_REFRESH_TOKEN
ARG SLACK_DATA_FETCHING_TOKEN
ENV ENVIRONMENT=${ENVIRONMENT}
ENV GMAIL_CLIENT_ID=${GMAIL_CLIENT_ID}
ENV GMAIL_CLIENT_SECRET=${GMAIL_CLIENT_SECRET}
ENV GMAIL_REFRESH_TOKEN=${GMAIL_REFRESH_TOKEN}
ENV SLACK_DATA_FETCHING_TOKEN=${SLACK_DATA_FETCHING_TOKEN}

# Tunables. Override them on the Lambda configuration without rebuilding the image.
ENV HELPDESK_EMAIL=helpdesk@clickmerito.com
ENV FORWARD_EMAIL_LOOKBACK_HOURS=24
ENV POLL_TIMEOUT_SEC=60
ENV POLL_INTERVAL_SEC=2

CMD ["handler.lambda_handler"]
