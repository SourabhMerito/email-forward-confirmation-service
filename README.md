# email-forward-confirmation-service

AWS Lambda for **job type 15 (`EMAIL_FORWARD_CONFIRMATION`)**. It replaces the autopilot Batch run of the RF
task `Complete Email Forward Confirmation`, which spent most of its time starting a multi-GB browser image.

What one invocation does:

1. Searches the helpdesk inbox (`helpdesk@clickmerito.com`) for Google's forwarding confirmation email for the
   user's mailbox, from the last **`FORWARD_EMAIL_LOOKBACK_HOURS` (default 24)**.
2. If none is there yet, polls **every 2s for up to 60s** (`POLL_INTERVAL_SEC`, `POLL_TIMEOUT_SEC`).
3. **Confirms the forwarding automatically**: opens the link, submits the `Confirm` form over HTTP (no browser)
   and accepts the result only when Google's page says `Confirmation Success!` (or that the address is already
   confirmed). If the newest email's link fails, up to 2 older ones are tried.
4. Sends the job 15 callback to jigsaw-api `POST {event.apiLink}/Charts/handleemailforwarding` **exactly once**, with
   the same body autopilot sends, and a Slack alert to `#partner-alerts` on failure.

| Result | `errorCode` |
|---|---|
| Forwarding confirmed | `null` (`isEmailForwarded: true`) |
| No confirmation email within the window after 60s of polling | `FORWARD_EMAIL_NOT_FOUND` |
| Email found, but Google didn't confirm | `FORWARD_CONFIRM_FAILED` |
| Portal has no job 15 flow (e.g. Myntra) | `UNSUPPORTED_JOB` |
| Gmail auth failure, bad event, crash | `TECHNICAL_ERROR` |

The handler never raises, so async invokes don't retry and send a second callback.

## Layout

```
handler.py                     lambda_handler: event loading, polling loop, reporting
config/settings.py             environment variables
services/gmail_service.py      Gmail API (OAuth refresh once per invocation) and the search query
services/email_parser.py       MIME decoding and confirmation link extraction
services/forward_confirmer.py  automatic confirmation (GET link → submit Confirm form → check result)
services/callback_service.py   jigsaw-api callback body and delivery (3 attempts)
services/slack_service.py      failure alert
```

## Environment variables

| Name | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `dev` | `dev` or `beta` (prod), as in autopilot |
| `API_URL` | | optional fallback only: the jigsaw-api URL normally comes from the event's `apiLink` |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | | OAuth client for `helpdesk@clickmerito.com` |
| `SLACK_DATA_FETCHING_TOKEN` | | Slack bot token; alerts are skipped when unset |
| `HELPDESK_EMAIL` | `helpdesk@clickmerito.com` | forwarding address users add in Gmail |
| `FORWARD_EMAIL_LOOKBACK_HOURS` | `24` | how far back to search; invalid or non-positive values fall back to 24 |
| `POLL_TIMEOUT_SEC` | `60` | how long to wait for the email to arrive |
| `POLL_INTERVAL_SEC` | `2` | time between searches |
| `S3_BUCKET` | per environment | only used for `{"key": ...}` events (`dev: uploadfiles-jigsaw`, `beta: meritoapp`) |

The secrets are baked into the image from GitHub secrets at build time. The tunables are `ENV` defaults in the
`Dockerfile`, so they can be changed on the Lambda configuration without a rebuild.

## Event

The same JSON autopilot receives in `job_details` (see `events/sample_event.json`). These forms are accepted:
the event itself, `{"job_details": "<event JSON string>"}`, or `{"key": "<s3 key>"}` pointing at it in S3.
Fields used: `apiLink` (jigsaw-api base URL for the callback), `job.id`, `connectionId`, `user.companyId`,
`userId`, `authMethod`, `integrationPartner`, and the user's mailbox from `customer_id` or
`apiConfig[0].customer_id`. If `apiLink` is missing, the `API_URL` env var is used; with neither set, no
callback can be sent and the run is logged as critical.

## Local development

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Check automatic confirmation against a real link (add `helpdesk@clickmerito.com` as a forwarding address from
a test Gmail account first, then copy the link from the confirmation email):

```bash
.venv/bin/python -m services.forward_confirmer "https://mail-settings.google.com/mail/vf-..."
```

Run the container locally through the Lambda runtime emulator built into the base image:

```bash
docker build --platform linux/amd64 -t email-forward-confirmation:local .
docker run --rm -p 9000:8080 --env-file .env email-forward-confirmation:local
curl -XPOST localhost:9000/2015-03-31/functions/function/invocations -d @events/sample_event.json
```

## Deployment

Pushing to `development` deploys `email-forward-confirmation-dev`, and pushing to `main` deploys
`email-forward-confirmation-prod`. Each workflow builds the image, pushes it to ECR as
`email-forward-confirmation/<env>:latest` and points the function at it.

GitHub secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_ACCOUNT_ID`, `GMAIL_CLIENT_ID`,
`GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, and optionally `SLACK_DATA_FETCHING_TOKEN` (without it, Slack
alerts are skipped).

### One-time AWS setup (per environment, shown for dev)

```bash
ACCOUNT=<aws account id>; REGION=ap-south-1; ENV=dev
IMAGE=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/email-forward-confirmation/$ENV:latest

aws ecr create-repository --repository-name email-forward-confirmation/$ENV --region $REGION

aws iam create-role --role-name email-forward-confirmation-lambda \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name email-forward-confirmation-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name email-forward-confirmation-lambda --policy-name read-job-details \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":["arn:aws:s3:::uploadfiles-jigsaw/*","arn:aws:s3:::meritoapp/*"]}]}'

# The function needs an image to exist, so push one by hand the first time.
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com
docker build --platform linux/amd64 --provenance=false -t $IMAGE --build-arg ENVIRONMENT=$ENV \
  --build-arg GMAIL_CLIENT_ID=... --build-arg GMAIL_CLIENT_SECRET=... \
  --build-arg GMAIL_REFRESH_TOKEN=... --build-arg SLACK_DATA_FETCHING_TOKEN=... .
docker push $IMAGE

aws lambda create-function --function-name email-forward-confirmation-$ENV --region $REGION \
  --package-type Image --code ImageUri=$IMAGE --architectures x86_64 \
  --role arn:aws:iam::$ACCOUNT:role/email-forward-confirmation-lambda \
  --timeout 180 --memory-size 256

# Async invokes must not retry: the handler already reports every outcome once.
aws lambda put-function-event-invoke-config --function-name email-forward-confirmation-$ENV \
  --region $REGION --maximum-retry-attempts 0
```

For prod, use `ENV=prod` with `ENVIRONMENT=beta`. The 180s timeout covers 60s of polling
plus the HTTP timeouts of the confirm and callback calls. A normal run takes a few seconds.

Grant `lambda:InvokeFunction` on the function to whatever dispatches job 15 (next section).

## Dispatching job 15 to this Lambda

jigsaw-api starts job 15 in `connectionForwarding.service.ts` → `IpConnectorService.postConnect`, which POSTs
to `${IP_URL}/integrations/<ip>/connect`. The service behind that URL builds the autopilot event and submits
the Batch job. That's where to switch over: for `jobType === 15`, invoke this Lambda asynchronously with the
**same event JSON** instead of submitting the Batch job:

```js
import { LambdaClient, InvokeCommand } from '@aws-sdk/client-lambda';

await new LambdaClient({ region: 'ap-south-1' }).send(new InvokeCommand({
  FunctionName: `email-forward-confirmation-${env}`, // dev | prod
  InvocationType: 'Event',
  Payload: Buffer.from(JSON.stringify(event)), // what Batch receives in job_details today, including apiLink
}));
```

The event must carry `apiLink` (the jigsaw-api base URL for the environment). The Lambda posts its callback there.

Nothing changes on the callback side: the route and body are the same, so jigsaw-api's
`handleEmailForwardCallback` works unchanged.

**Rollback:** autopilot still has the job 15 RF flow, so switching the dispatch back to Batch restores the old
behaviour.
