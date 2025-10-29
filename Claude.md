# Claude Code Instructions

## Quick Deployment

To deploy the latest agent code:

```bash
./deploy.sh
```

This will:
1. Activate the Python virtual environment
2. Build the ARM64 Docker container via AWS CodeBuild
3. Push the image to ECR
4. Update the AgentCore Runtime with the new image

## Manual Deployment

If you prefer to deploy manually:

```bash
source venv/bin/activate
agentcore launch
```

## Testing After Deployment

Check logs to verify deployment:

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/vrc_insights_agent-Tdnt4wBJle-DEFAULT \
  --log-stream-name-prefix "2025/10/29/[runtime-logs]" \
  --since 5m \
  --format short
```

Send a test message:

```bash
# Generate JWT token and send test message
node -e "const crypto=require('crypto');const s='vrc-training-platform-secret-key-2025';const h=Buffer.from(JSON.stringify({alg:'HS256',typ:'JWT'})).toString('base64url');const p=Buffer.from(JSON.stringify({strava_user_id:'107447578',exp:Math.floor(Date.now()/1000)+3600})).toString('base64url');const sig=crypto.createHmac('sha256',s).update(h+'.'+p).digest('base64url');console.log(h+'.'+p+'.'+sig);" | xargs -I {} curl -X POST https://slropiyam4p6nhnhq5hphyk54y0hdwmw.lambda-url.us-east-1.on.aws/ -H "Content-Type: application/json" -H "X-Session-Token: {}" -d '{"message":"Test message"}'
```

## Project Structure

- `agent.py` - Main agent implementation with MemoryHookProvider for conversation persistence
- `deploy.sh` - Deployment script
- `.bedrock_agentcore.yaml` - AgentCore configuration
- `requirements.txt` - Python dependencies
- `Dockerfile` - Container configuration for ARM64
- `README.md` - Project documentation

## Key Components

### Agent Runtime
- **Runtime ID**: `vrc_insights_agent-Tdnt4wBJle`
- **Memory ID**: `vrc_insights_agent_mem-q1TYxG9Jjh`
- **ECR Repository**: `609061237212.dkr.ecr.us-east-1.amazonaws.com/bedrock-agentcore-vrc_insights_agent`

### Lambda Functions
- `vrc-invoke-insights-agent` - Invokes agent with streaming responses
- `vrc-get-conversation-messages` - Retrieves conversation history
- `vrc-get-user-activities` - Fetches Strava activities
- `vrc-strava-proxy` - Proxies Strava API requests

## Memory Persistence

The agent uses **MemoryHookProvider** pattern for conversation persistence:

- Hooks register on agent initialization
- Messages are manually saved to AgentCore Memory during streaming
- USER message saved before streaming starts
- ASSISTANT message saved after streaming completes
- This preserves both real-time streaming UX and conversation persistence

Look for these log messages to confirm memory is working:
- "✅ Memory hooks registered"
- "✅ Stored message with Event ID: ..."
- "✅ Manually saved assistant response to memory (...)"

## Troubleshooting

### CodeBuild Failures

If CodeBuild fails with "Internal Service Error", this is a transient AWS issue. Simply retry:

```bash
./deploy.sh
```

### Check Current Runtime Status

```bash
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id vrc_insights_agent-Tdnt4wBJle \
  --query '{status:status,lastUpdated:lastUpdatedTime}' \
  --output json
```

### Verify Memory Events

```bash
aws bedrock-agentcore list-events \
  --memory-id vrc_insights_agent_mem-q1TYxG9Jjh \
  --session-id <session-id> \
  --actor-id <session-id>
```

Note: `actorId` must equal `sessionId` for AgentCore Memory.
