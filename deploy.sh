#!/bin/bash
# VRC Insights Agent Deployment Script
# Deploys the agent to AWS Bedrock AgentCore Runtime

set -e  # Exit on error

echo "🚀 VRC Insights Agent Deployment"
echo "================================"
echo ""

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Deploy using agentcore CLI
echo "🔨 Building and deploying agent to AgentCore Runtime..."
echo "   This will:"
echo "   - Build ARM64 Docker container via CodeBuild"
echo "   - Push to ECR repository"
echo "   - Update AgentCore Runtime"
echo ""

agentcore launch

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "   - Check logs: aws logs tail /aws/bedrock-agentcore/runtimes/vrc_insights_agent-Tdnt4wBJle-DEFAULT --log-stream-name-prefix \"2025/10/29/[runtime-logs]\" --since 5m"
echo "   - Test agent: Send message via Lambda function URL"
echo ""
