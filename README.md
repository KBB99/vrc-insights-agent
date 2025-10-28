# VRC Insights Agent

AI-powered running coach agent for Village Run Club training platform, built with AWS Bedrock AgentCore and Strands Agents SDK.

## Overview

This agent provides personalized running insights and coaching based on Strava activity data. It uses:
- **AWS Bedrock AgentCore Runtime** for hosting the agent container
- **Strands Agents SDK** for agent framework and tools
- **Claude 3.5 Sonnet** as the LLM
- **AgentCore Memory** for conversation persistence
- **Strava API** for activity data

## Features

- Analyze running activities (pace, distance, heart rate, elevation)
- Generate personalized weekly training insights
- Track training load and recovery
- Provide coaching recommendations
- Maintain conversation history across sessions

## Architecture

### Components

1. **Agent Container** (`agent.py`): Main Strands agent with tools for Strava API access
2. **Lambda Functions**:
   - `vrc-invoke-insights-agent`: Invokes agent with streaming responses
   - `vrc-get-conversation-messages`: Retrieves conversation history from AgentCore Memory
   - `vrc-get-user-activities`: Fetches Strava activities for a user
   - `vrc-strava-proxy`: Proxies requests to Strava API
3. **Frontend**: Static HTML/JS dashboard for chat interface
4. **AgentCore Memory**: DynamoDB-backed conversation persistence

### Agent Tools

- `get_user_activities`: Fetch recent runs from Strava
- `get_detailed_activity`: Get detailed activity with streams (HR, pace, etc.)
- `analyze_training_load`: Calculate training metrics and trends

## Deployment

### Prerequisites

- AWS Account with Bedrock access
- Strava API credentials
- Docker installed locally
- AWS CLI configured

### Build and Deploy

1. **Build Docker Image**:
```bash
aws codebuild start-build --project-name bedrock-agentcore-vrc_insights_agent-builder
```

2. **Update AgentCore Runtime**:
```bash
python3 scripts/update_runtime.py
```

3. **Deploy Lambda Functions**:
```bash
# Package and deploy each Lambda function
cd lambdas/invoke-insights
zip -r function.zip index.mjs
aws lambda update-function-code --function-name vrc-invoke-insights-agent --zip-file fileb://function.zip
```

## Configuration

### Environment Variables

**Agent Container**:
- `BEDROCK_AGENTCORE_MEMORY_ID`: AgentCore Memory ID for conversation storage
- `JWT_SECRET`: Secret for validating JWT session tokens

**Lambda Functions**:
- `STRAVA_CLIENT_ID`: Strava OAuth client ID
- `STRAVA_CLIENT_SECRET`: Strava OAuth client secret
- `JWT_SECRET`: Secret for JWT tokens

### IAM Role

The AgentCore runtime requires an IAM role with:
- `AmazonBedrockFullAccess`: For invoking Claude models
- `AmazonDynamoDBFullAccess`: For AgentCore Memory access
- `CloudWatchLogsFullAccess`: For logging

Trust policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```

## Memory Implementation

The agent uses **MemoryHookProvider** pattern for conversation persistence:

```python
class MemoryHookProvider(HookProvider):
    def on_agent_initialized(self, event):
        # Load recent conversation history
        recent_turns = self.memory_session.get_last_k_turns(k=10)

    def on_message_added(self, event):
        # Save messages to AgentCore Memory
        self.memory_session.add_turns(messages=[...])
```

This ensures:
- Conversations persist across sessions
- Chat history loads when resuming sessions
- Each user has isolated conversation storage

## Testing

### Test Agent Invocation

```bash
# Generate JWT token
JWT=$(node -e "const crypto=require('crypto');...")

# Send test message
curl -X POST https://[lambda-url] \
  -H "Content-Type: application/json" \
  -H "X-Session-Token: $JWT" \
  -d '{"message":"What were my runs this week?"}'
```

### Check Memory Persistence

```bash
aws bedrock-agentcore list-events \
  --memory-id vrc_insights_agent_mem-q1TYxG9Jjh \
  --session-id [session-id] \
  --actor-id [session-id]
```

## Troubleshooting

### Hooks Not Triggering

- **Issue**: Messages not persisting to AgentCore Memory
- **Cause**: Streaming methods bypass hook system
- **Solution**: Use `run_async()` instead of `stream_async()`, then manually chunk response

### Role Validation Errors

- **Issue**: "Role validation failed"
- **Solution**: Ensure IAM role has trust policy for `bedrock-agentcore.amazonaws.com`

### Memory Access Errors

- **Issue**: Can't retrieve conversation history
- **Solution**: Verify `actorId` equals `sessionId` in `list-events` calls

## License

MIT
