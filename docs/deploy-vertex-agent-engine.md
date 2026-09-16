# Deploying to Vertex AI Agent Engine

> **Status: NOT EXECUTED.** Nothing in this document has been run. This agent
> has not been deployed to Agent Engine or to any other cloud, and no cloud
> resources were created while building this repository. The steps below come
> from reading the `adk deploy agent_engine` command in `google-adk` 2.9.1
> (`adk deploy agent_engine --help` and its source). Check them against the
> current Google Cloud documentation before you use them. Commands and flags
> change between ADK releases.

## What changes in the cloud

Locally the agent starts `mcp-logistica` as a **child process over stdio** and
reads a **SQLite file**. Both still work inside an Agent Engine container, but
their meaning changes:

| Local | In Agent Engine |
|---|---|
| `wms_mcp` installed in the same venv | `wms_mcp` must be **staged into the image** (see Packaging) |
| `data/wms.sqlite` on your disk | A file baked into the image. The container file system is not durable storage: writes can be lost on restart or scale-out, and every instance has its own copy |
| One user at a time | Many sessions against the same instance |

So a cloud deployment of **this repository** is a demo of the agent, not of a
warehouse backend. Deploy it with `WMS_WRITE_POLICY=off`. A real deployment
would keep the MCP server as a separate service (streamable HTTP with
authentication) in front of the real WMS database. The toolset would then use
`StreamableHTTPConnectionParams` instead of stdio. That change is not
implemented here.

## Requirements

- A Google Cloud project with billing enabled and the Vertex AI API turned on.
- `gcloud` installed and authenticated. ADK uses Application Default
  Credentials (`gcloud auth application-default login`).
- A region close to your users and your data (for EU data, an EU region).
- The same `google-adk` version you tested with. `adk deploy agent_engine`
  defaults `--adk_version` to the installed one: 2.9.1 here.
- IAM: the person deploying needs rights to create Agent Engine resources and
  to run Cloud Build. The runtime service account should get only what the
  agent needs, which here is calling Gemini on Vertex AI.

## Packaging

`adk deploy agent_engine` copies the agent folder into a staging directory,
builds a container with Cloud Build and creates the Agent Engine resource.
Four things need care for this agent.

1. **Dependencies.** If the agent folder has no `requirements.txt`, the command
   writes one with only `google-adk`. This agent also needs `mcp` pinned to the
   version `mcp-logistica` was tested with. Create
   `agents/wms_assistant/requirements.txt` for the deployment (it is listed in
   `.gitignore`, so it stays out of the repository):

   ```text
   google-adk[mcp]==2.9.1
   mcp>=1.30,<1.31
   ```

2. **The MCP server code.** `--extra_packages` stages a local file or directory
   at `/app/<basename>` and puts `/app` on `PYTHONPATH`. Stage the `wms_mcp`
   package itself, not the repository root:

   ```bash
   --extra_packages ../mcp-logistica/src/wms_mcp
   ```

   The toolsets forward `PYTHONPATH` to the server process
   (`toolsets.FORWARDED_ENV`), so `python -m wms_mcp.server` can import the
   staged package. That forwarding is covered by a unit test; the import inside
   a real Agent Engine image has **not** been checked.

3. **Imports inside the agent package.** The agent modules import
   `wms_assistant.*` with absolute imports. The staging layout
   (`<tmp>/agents/wms_assistant`) has to make that name importable. If the
   deployed agent fails on import, switch those imports to relative ones or
   stage the package with `--extra_packages agents/wms_assistant`. **Unverified.**

4. **The demo database.** Seed a file and stage its directory:

   ```bash
   make seed DB=deploy/data/wms.sqlite
   --extra_packages deploy/data        # lands at /app/data/wms.sqlite
   ```

## Environment variables

`adk deploy agent_engine` reads `agents/wms_assistant/.env` and passes its
values to the deployed agent. (`--env_file` and `--requirements_file` still
exist in 2.9.1 but `--help` marks them deprecated; do not rely on them.)
`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` from that file are used as
`--project` and `--region` when those flags are absent.

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=europe-west1
WMS_WRITE_POLICY=off
WMS_DB_PATH=/app/data/wms.sqlite
# WMS_MODEL=                      # default: ADK's default Gemini model
```

- **Do not put API keys in this file.** Its values become plain environment
  variables of the deployed service. On Vertex AI, Gemini uses the service
  account, so no key is needed. For Claude or OpenAI through LiteLLM, keep the
  key in Secret Manager and expose it through the secret support of Agent
  Engine (check the current documentation for how).
- `WMS_WRITE_POLICY` must stay `off` for this demo (see above). With
  `dry_run` or `on`, every write needs a human approval
  (`adk_request_confirmation`). Whatever client calls the deployed agent must
  show that request to a person and send the answer back. A client that
  ignores it will simply never write.

## Deploy

```bash
# from the repository root, after `make install`
adk deploy agent_engine \
  --project=your-project-id \
  --region=europe-west1 \
  --display_name="wms-assistant-demo" \
  --description="Read-only warehouse assistant on synthetic data" \
  --extra_packages ../mcp-logistica/src/wms_mcp \
  --extra_packages deploy/data \
  agents/wms_assistant
```

Optional flags worth knowing:

- `--otel_to_cloud` sends traces to Cloud Trace. Message content is kept out
  of spans unless you set `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`. Keep it out:
  prompts can contain customer names.
- `--agent_engine_id` updates an existing instance instead of creating a new
  one.
- `--worker_pool` builds the image on a private Cloud Build pool (VPC-SC).
- `--temp_folder` chooses the staging directory. Its contents are deleted first.

A minimal smoke test after deploying: send "Which orders have been in the
warehouse for more than 48 hours?" and check that the answer lists the six
seeded order ids. Then send "Mark order 10432 as a stock issue" and check that
the agent says writes are disabled.

## Cost

No figures are given here because nothing was run or billed. The cost drivers
are:

- **Agent Engine runtime**: compute and memory while instances are up, plus
  managed sessions or memory if you use them.
- **Model tokens**: every turn sends the instruction, the tool declarations
  (seven tools with write policy on, five with it off) and the conversation
  history. Tool results such as order details add to the input.
- **Evaluation**: `adk eval` with the rubric metric calls a judge model
  several times per case (`num_samples` in `evals/test_config.json`).
- **Cloud Build and Artifact Registry** for every deploy, and **Cloud Logging
  and Trace** volume.

Before deploying:

- set a billing budget with alerts on the project;
- use the smallest instance settings the console offers for a demo;
- delete the Agent Engine resource when you are done (console, or the Vertex
  AI SDK). An idle deployment can still cost money.

Check the current Vertex AI pricing page for the actual rates.

## Security checklist

- [ ] Runtime service account has only the roles it needs; no owner/editor.
- [ ] No API keys in `.env`; secrets come from Secret Manager.
- [ ] `WMS_WRITE_POLICY=off` for the demo. In a real setup, writes go through
      a human approval step that the client actually shows.
- [ ] Only synthetic data in the image. The staged SQLite file is readable by
      anyone who can read the image.
- [ ] Message content kept out of traces and logs.
- [ ] Region chosen for data residency.
- [ ] Access to the Agent Engine endpoint limited to the identities that need it.
- [ ] Budget alert configured, and a date to delete the demo.

## Design note: an AWS alternative for writes

Not built, not tested; a direction only. On AWS, a write tool would validate
the request and put it on an **SQS** queue with an idempotency key and the
approving user; a **Lambda** consumer with its own narrow role would apply it
and record the outcome in **DynamoDB**, which would also hold pending
approvals and session state. The agent would then report "queued", not
"done", until a read tool shows the result.
