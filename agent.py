"""VRC Training Insights Agent - Strands agent with Strava integration"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import boto3
from strands import Agent, tool
from strands.hooks import AgentInitializedEvent, HookProvider, HookRegistry, MessageAddedEvent
from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole
from bedrock_agentcore.memory.session import MemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp, BedrockAgentCoreContext

# Initialize AWS clients
dynamodb = boto3.client('dynamodb', region_name='us-east-1')

# Strava API configuration
STRAVA_API_BASE = 'https://www.strava.com/api/v3'

class StravaTools:
    """Tools for fetching Strava data using stored user tokens"""

    @staticmethod
    def get_user_tokens(strava_user_id: str) -> Dict[str, str]:
        """Fetch user's Strava tokens from DynamoDB"""
        try:
            response = dynamodb.get_item(
                TableName='vrc-users',
                Key={'strava_user_id': {'S': strava_user_id}}
            )

            if 'Item' not in response:
                raise ValueError(f"User {strava_user_id} not found")

            item = response['Item']
            access_token = item['access_token']['S']
            refresh_token = item['refresh_token']['S']
            expires_at = int(item['expires_at']['N'])

            # Check if token needs refresh
            if expires_at < int(datetime.now().timestamp()) + 3600:
                access_token, refresh_token = StravaTools.refresh_token(
                    strava_user_id, refresh_token
                )

            return {
                'access_token': access_token,
                'refresh_token': refresh_token
            }
        except Exception as e:
            raise Exception(f"Error fetching user tokens: {str(e)}")

    @staticmethod
    def refresh_token(strava_user_id: str, refresh_token: str) -> tuple[str, str]:
        """Refresh Strava access token"""
        import requests

        response = requests.post(
            'https://www.strava.com/api/v3/oauth/token',
            data={
                'client_id': '181417',
                'client_secret': '74c6a5c3e63e1deed676096a23bf4f207fb77887',
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }
        )

        if not response.ok:
            raise Exception(f"Token refresh failed: {response.status_code}")

        token_data = response.json()
        new_access_token = token_data['access_token']
        new_refresh_token = token_data['refresh_token']
        new_expires_at = token_data['expires_at']

        # Update DynamoDB
        dynamodb.update_item(
            TableName='vrc-users',
            Key={'strava_user_id': {'S': strava_user_id}},
            UpdateExpression='SET access_token = :at, refresh_token = :rt, expires_at = :ea, updated_at = :ua',
            ExpressionAttributeValues={
                ':at': {'S': new_access_token},
                ':rt': {'S': new_refresh_token},
                ':ea': {'N': str(new_expires_at)},
                ':ua': {'S': datetime.now().isoformat()}
            }
        )

        return new_access_token, new_refresh_token

@tool
def calculate(expression: str) -> str:
    """
    Perform mathematical calculations with high precision.

    IMPORTANT: Use this tool for ALL mathematical operations including:
    - Adding/summing numbers (e.g., "2.5 + 3.7 + 4.2")
    - Subtracting numbers (e.g., "50 - 42")
    - Multiplying numbers (e.g., "6.2 * 7")
    - Dividing numbers (e.g., "100 / 7")
    - Complex expressions (e.g., "(62.4 + 43.2 + 38.1) / 3")

    Args:
        expression: Mathematical expression to evaluate (e.g., "2.5 + 3.7 + 4.2")

    Returns:
        String with the calculation result

    Examples:
        calculate("51.2 + 49.8") -> "101.0"
        calculate("(62 + 43 + 38) / 3") -> "47.666666666666664"
        calculate("51 * 1.1") -> "56.1"
    """
    try:
        # Sanitize expression - only allow numbers, operators, parentheses, and whitespace
        if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expression):
            return json.dumps({
                'error': 'Invalid expression. Only numbers and basic operators (+, -, *, /, parentheses) are allowed.'
            })

        # Evaluate the expression safely
        result = eval(expression, {"__builtins__": {}}, {})

        return json.dumps({
            'expression': expression,
            'result': result
        })
    except Exception as e:
        return json.dumps({
            'error': f'Calculation error: {str(e)}',
            'expression': expression
        })

@tool
def get_recent_activities(strava_user_id: str, per_page: int = 30, days_back: int = 30) -> str:
    """
    Fetch user's recent Strava activities.

    Args:
        strava_user_id: Strava user ID
        per_page: Number of activities to fetch (default 30)
        days_back: Number of days to look back (default 30)

    Returns:
        JSON string with activities data
    """
    import requests

    tokens = StravaTools.get_user_tokens(strava_user_id)
    after_timestamp = int((datetime.now() - timedelta(days=days_back)).timestamp())

    response = requests.get(
        f'{STRAVA_API_BASE}/athlete/activities',
        headers={'Authorization': f"Bearer {tokens['access_token']}"},
        params={'per_page': per_page, 'after': after_timestamp}
    )

    if not response.ok:
        return json.dumps({'error': f"Strava API error: {response.status_code}"})

    activities = response.json()

    # Transform for analysis
    transformed = []
    for activity in activities:
        transformed.append({
            'id': activity['id'],
            'name': activity['name'],
            'type': activity['type'],
            'sport_type': activity.get('sport_type'),
            'start_date': activity['start_date_local'],
            'distance_meters': activity['distance'],
            'distance_miles': round(activity['distance'] / 1609.34, 2),
            'moving_time_seconds': activity['moving_time'],
            'elapsed_time_seconds': activity['elapsed_time'],
            'total_elevation_gain_meters': activity['total_elevation_gain'],
            'average_speed_ms': activity.get('average_speed'),
            'max_speed_ms': activity.get('max_speed'),
            'average_heartrate': activity.get('average_heartrate'),
            'max_heartrate': activity.get('max_heartrate'),
            'average_watts': activity.get('average_watts'),
            'max_watts': activity.get('max_watts'),
            'suffer_score': activity.get('suffer_score'),
            'pace_min_per_mile': round((activity['moving_time'] / 60) / (activity['distance'] / 1609.34), 2) if activity['distance'] > 0 else None
        })

    return json.dumps({
        'count': len(transformed),
        'activities': transformed
    }, indent=2)


@tool
def get_athlete_stats(strava_user_id: str) -> str:
    """
    Fetch athlete's all-time, year-to-date, and recent stats.

    Args:
        strava_user_id: Strava user ID

    Returns:
        JSON string with stats data
    """
    import requests

    tokens = StravaTools.get_user_tokens(strava_user_id)

    response = requests.get(
        f'{STRAVA_API_BASE}/athletes/{strava_user_id}/stats',
        headers={'Authorization': f"Bearer {tokens['access_token']}"}
    )

    if not response.ok:
        return json.dumps({'error': f"Strava API error: {response.status_code}"})

    return json.dumps(response.json(), indent=2)


@tool
def get_activity_details(strava_user_id: str, activity_id: int) -> str:
    """
    Fetch detailed information about a specific activity.

    Args:
        strava_user_id: Strava user ID
        activity_id: Activity ID

    Returns:
        JSON string with activity details
    """
    import requests

    tokens = StravaTools.get_user_tokens(strava_user_id)

    response = requests.get(
        f'{STRAVA_API_BASE}/activities/{activity_id}',
        headers={'Authorization': f"Bearer {tokens['access_token']}"}
    )

    if not response.ok:
        return json.dumps({'error': f"Strava API error: {response.status_code}"})

    return json.dumps(response.json(), indent=2)


@tool
def get_club_members_recent_activities(strava_user_id: str, club_id: int = None, days_back: int = 7) -> str:
    """
    Fetch recent activities from club members for comparison.

    Args:
        strava_user_id: Strava user ID
        club_id: Strava club ID (optional, will fetch user's clubs if not provided)
        days_back: Number of days to look back (default 7)

    Returns:
        JSON string with club activities
    """
    import requests

    tokens = StravaTools.get_user_tokens(strava_user_id)

    # If no club_id provided, get user's first club
    if club_id is None:
        clubs_response = requests.get(
            f'{STRAVA_API_BASE}/athlete/clubs',
            headers={'Authorization': f"Bearer {tokens['access_token']}"}
        )

        if not clubs_response.ok or not clubs_response.json():
            return json.dumps({'error': 'No clubs found'})

        club_id = clubs_response.json()[0]['id']

    # Get club activities
    response = requests.get(
        f'{STRAVA_API_BASE}/clubs/{club_id}/activities',
        headers={'Authorization': f"Bearer {tokens['access_token']}"},
        params={'per_page': 50}
    )

    if not response.ok:
        return json.dumps({'error': f"Strava API error: {response.status_code}"})

    activities = response.json()
    cutoff_date = datetime.now() - timedelta(days=days_back)

    # Filter by date and transform
    recent_activities = []
    for activity in activities:
        activity_date = datetime.fromisoformat(activity['start_date_local'].replace('Z', '+00:00'))
        if activity_date >= cutoff_date:
            recent_activities.append({
                'athlete_name': f"{activity['athlete']['firstname']} {activity['athlete']['lastname']}",
                'name': activity['name'],
                'type': activity['type'],
                'distance_miles': round(activity['distance'] / 1609.34, 2),
                'moving_time_seconds': activity['moving_time'],
                'start_date': activity['start_date_local']
            })

    return json.dumps({
        'club_id': club_id,
        'count': len(recent_activities),
        'activities': recent_activities
    }, indent=2)


@tool
def save_training_plan(strava_user_id: str, plan_json: str) -> str:
    """
    Save a training plan to storage.

    Use this to store training plans that you've created for the athlete.

    Args:
        strava_user_id: Strava user ID
        plan_json: JSON string with structure:
        {
            "goal": "Sub-3 Marathon - April 20, 2025",
            "created_at": "2025-10-20",
            "weeks": [
                {
                    "week_start": "2025-10-21",
                    "workouts": [
                        {
                            "day": "Monday",
                            "type": "Easy Run",
                            "distance": 6,
                            "target_pace": "9:30-10:00/mi",
                            "target_hr": "<145 bpm",
                            "notes": "Recovery pace, conversational",
                            "completed": false,
                            "actual_distance": null,
                            "actual_pace": null,
                            "actual_hr": null,
                            "activity_id": null,
                            "ai_summary": null
                        }
                    ]
                }
            ]
        }

    Returns:
        Confirmation message with number of weeks saved
    """
    try:
        plan_data = json.loads(plan_json)

        if 'weeks' not in plan_data or not plan_data['weeks']:
            return json.dumps({'error': 'Invalid plan format - missing weeks array'})

        goal = plan_data.get('goal', 'Training Plan')
        created_at = plan_data.get('created_at', datetime.now().strftime('%Y-%m-%d'))
        weeks_saved = 0

        # Save each week to DynamoDB
        for week in plan_data['weeks']:
            week_start = week.get('week_start')
            workouts = week.get('workouts', [])

            if not week_start:
                continue

            dynamodb.put_item(
                TableName='vrc-training-plans',
                Item={
                    'user_id': {'S': strava_user_id},
                    'week_start_date': {'S': week_start},
                    'goal': {'S': goal},
                    'created_at': {'S': created_at},
                    'plan_data': {'S': json.dumps({
                        'workouts': workouts,
                        'goal': goal
                    })}
                }
            )
            weeks_saved += 1

        return json.dumps({
            'success': True,
            'message': f'Training plan saved successfully! {weeks_saved} weeks stored.',
            'goal': goal,
            'weeks': weeks_saved
        })

    except json.JSONDecodeError as e:
        return json.dumps({'error': f'Invalid JSON format: {str(e)}'})
    except Exception as e:
        return json.dumps({'error': f'Failed to save plan: {str(e)}'})


@tool
def get_training_plan(strava_user_id: str, week_start_date: str = None) -> str:
    """
    Get the training plan for a specific week (or current week if not specified).

    Use this to retrieve the athlete's plan so you can check their progress or make adjustments.

    Args:
        strava_user_id: Strava user ID
        week_start_date: Optional week start date in format "2025-10-21" (Monday).
                        If None, returns current week's plan.

    Returns:
        JSON string with that week's plan including completion status, or error if no plan exists
    """
    try:
        # If no date provided, get current week's Monday
        if not week_start_date:
            today = datetime.now()
            # Calculate Monday of current week (0 = Monday, 6 = Sunday)
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            week_start_date = monday.strftime('%Y-%m-%d')

        # Query DynamoDB
        response = dynamodb.get_item(
            TableName='vrc-training-plans',
            Key={
                'user_id': {'S': strava_user_id},
                'week_start_date': {'S': week_start_date}
            }
        )

        if 'Item' not in response:
            return json.dumps({
                'found': False,
                'message': f'No training plan found for week of {week_start_date}',
                'week_start': week_start_date
            })

        item = response['Item']
        plan_data = json.loads(item['plan_data']['S'])

        return json.dumps({
            'found': True,
            'week_start': week_start_date,
            'goal': item.get('goal', {}).get('S', 'Training Plan'),
            'created_at': item.get('created_at', {}).get('S', 'Unknown'),
            'workouts': plan_data.get('workouts', [])
        }, indent=2)

    except Exception as e:
        return json.dumps({'error': f'Failed to retrieve plan: {str(e)}'})


@tool
def update_workout_in_plan(strava_user_id: str, week_start_date: str, day: str, updates: str) -> str:
    """
    Update a specific workout in the training plan.

    Use this to mark workouts as completed after matching them with Strava activities,
    or to modify workout details.

    Args:
        strava_user_id: Strava user ID
        week_start_date: Week start date in format "2025-10-21" (Monday)
        day: Day of week ("Monday", "Tuesday", etc.)
        updates: JSON string with fields to update, e.g.:
        {
            "completed": true,
            "actual_distance": 6.2,
            "actual_pace": "9:45/mi",
            "actual_hr": 138,
            "ai_summary": "Perfect! Nailed the easy pace. HR was right in the zone.",
            "activity_id": "12345678"
        }

    Returns:
        Confirmation message or error
    """
    try:
        # Get the existing plan
        response = dynamodb.get_item(
            TableName='vrc-training-plans',
            Key={
                'user_id': {'S': strava_user_id},
                'week_start_date': {'S': week_start_date}
            }
        )

        if 'Item' not in response:
            return json.dumps({'error': f'No plan found for week of {week_start_date}'})

        # Parse plan data
        item = response['Item']
        plan_data = json.loads(item['plan_data']['S'])
        workouts = plan_data.get('workouts', [])

        # Find the workout for the specified day
        workout_found = False
        for workout in workouts:
            if workout.get('day') == day:
                # Parse updates
                update_data = json.loads(updates)

                # Merge updates into workout
                for key, value in update_data.items():
                    workout[key] = value

                workout_found = True
                break

        if not workout_found:
            return json.dumps({'error': f'No workout found for {day} in week of {week_start_date}'})

        # Save updated plan back to DynamoDB
        dynamodb.put_item(
            TableName='vrc-training-plans',
            Item={
                'user_id': {'S': strava_user_id},
                'week_start_date': {'S': week_start_date},
                'goal': item.get('goal', {'S': 'Training Plan'}),
                'created_at': item.get('created_at', {'S': datetime.now().strftime('%Y-%m-%d')}),
                'plan_data': {'S': json.dumps(plan_data)}
            }
        )

        return json.dumps({
            'success': True,
            'message': f'Workout updated successfully for {day}, week of {week_start_date}',
            'updated_workout': workout
        }, indent=2)

    except json.JSONDecodeError as e:
        return json.dumps({'error': f'Invalid JSON in updates: {str(e)}'})
    except Exception as e:
        return json.dumps({'error': f'Failed to update workout: {str(e)}'})


# Configure persistent memory with summarization
coaching_summary_prompt = """
Summarize this coaching conversation between V and the athlete.

MUST PRESERVE:
- Training goals (race dates, target times like "sub-3 marathon")
- Active training plans (goal, key workouts, timeline)
- Personal context (injuries, travel, time constraints)
- Key coaching advice given (pace zones, workout recommendations)
- PRs and achievements mentioned
- Athlete preferences (likes/dislikes certain workouts, scheduling constraints)
- Important decisions made (plan adjustments, training philosophy)

KEEP BRIEF:
- General encouragement and pleasantries
- Detailed workout analysis (keep only the conclusions)

Format as structured bullet points:
## Current Goal & Active Plan
## Key Coaching Advice Given
## Athlete Context & Constraints
## Recent Progress & Achievements
"""

# Memory Hook Provider for AgentCore Memory persistence
class MemoryHookProvider(HookProvider):
    """Custom hook provider that persists messages to AgentCore Memory using MemorySession"""

    def __init__(self, memory_session):
        self.memory_session = memory_session

    def on_agent_initialized(self, event: AgentInitializedEvent):
        """Load recent conversation history when agent starts"""
        try:
            # Get last 10 conversation turns from AgentCore Memory
            recent_turns = self.memory_session.get_last_k_turns(k=10)

            if recent_turns:
                # Format conversation history for context
                context_messages = []
                for turn in recent_turns:
                    for message in turn:
                        role = message['role']
                        content = message['content']['text']
                        context_messages.append(f"{role}: {content}")

                context = "\n".join(context_messages)
                # Add context to agent's system prompt
                event.agent.system_prompt += f"\n\nRecent conversation:\n{context}"
                print(f"✅ Loaded {len(recent_turns)} conversation turns from AgentCore Memory")

        except Exception as e:
            print(f"❌ Memory load error: {e}")

    def on_message_added(self, event: MessageAddedEvent):
        """Store messages in AgentCore Memory"""
        messages = event.agent.messages
        try:
            if messages and len(messages) > 0 and messages[-1]["content"][0].get("text"):
                message_text = messages[-1]["content"][0]["text"]
                message_role = MessageRole.USER if messages[-1]["role"] == "user" else MessageRole.ASSISTANT

                # Save to AgentCore Memory using MemorySession
                result = self.memory_session.add_turns(
                    messages=[ConversationalMessage(message_text, message_role)]
                )

                event_id = result['eventId']
                print(f"✅ Stored message with Event ID: {event_id}, Role: {message_role.value}")

        except Exception as e:
            print(f"❌ Memory save error: {e}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")

    def register_hooks(self, registry: HookRegistry):
        # Register memory hooks
        registry.add_callback(MessageAddedEvent, self.on_message_added)
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        print("✅ Memory hooks registered")


# Agent factory function - creates agent per-request with AgentCore Memory session persistence
def create_agent_with_session(session_id: str, strava_user_id: str) -> Agent:
    """Create a new Agent instance with AgentCore Memory persistence using MemorySession.

    Args:
        session_id: Unique session identifier for this conversation
        strava_user_id: Strava user ID for agent identification

    Returns:
        Agent: Configured Agent instance with AgentCore Memory session persistence
    """
    # Get memory ID from environment variable
    memory_id = os.getenv('BEDROCK_AGENTCORE_MEMORY_ID')
    if not memory_id:
        raise ValueError('BEDROCK_AGENTCORE_MEMORY_ID environment variable not set')

    # Create MemorySessionManager and MemorySession
    session_manager = MemorySessionManager(memory_id=memory_id, region_name='us-east-1')
    memory_session = session_manager.create_memory_session(
        actor_id=session_id,  # Use session_id as actor_id
        session_id=session_id
    )

    # Create Strands agent with memory hooks
    # Use fixed agent_id based on user to ensure consistent message tracking
    agent = Agent(
        agent_id=f"v-coach-{strava_user_id}",  # Fixed agent ID per user
        name="V - Village Run Club Coach",
        hooks=[MemoryHookProvider(memory_session)],  # Use custom memory hooks
        model="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        system_prompt="""You are V, the supportive and knowledgeable coach for Village Run Club members.

# WHO YOU ARE

You're V - a coach who genuinely cares about each athlete's progress. You're a supportive friend first, expert second. You use "we" language because you're in this together with every runner. You balance encouragement with real, constructive feedback. You're data-driven but always human-first.

# YOUR VOICE

- Warm, encouraging, but direct when needed
- Use casual but intelligent language
- Emojis very sparingly (💪 🔥 for genuine big wins only)
- Start with acknowledgment, then provide analysis
- Ask questions to understand goals better
- Celebrate effort and consistency, not just results

# DATA & TOOLS

You have access to:
- Recent activities (runs, rides, swims, etc.)
- Athlete stats (all-time, year-to-date, recent)
- Detailed activity data (pace, heart rate, power, elevation)
- Club member activities for comparison
- A calculator tool for accurate mathematical calculations

⚠️ CRITICAL: ALWAYS use the calculate() tool for ALL math:
- Weekly totals: calculate("6.2 + 8.5 + 5.1 + 7.3 + 10.2 + 4.8 + 9.1")
- Averages: calculate("(51 + 50 + 48) / 3")
- Percentages: calculate("50 * 1.1")
- NEVER do mental math or approximate - always use calculate()

# YOUR APPROACH

When analyzing training:
1. **Acknowledge first** - Recognize their effort/progress
2. **Use specific data** - Reference actual numbers from their Strava
3. **Provide context** - Explain what the data means
4. **Give actionable next steps** - Be specific about what to do

Structure responses like:
- Start warm: "You've been putting in the work!" or "Let me break down what I'm seeing"
- Present data: Use calculate() for precise numbers, reference specific activities
- Provide insight: Explain patterns, trends, what's working
- Suggest next steps: Specific, actionable recommendations
- End with engagement: Ask about their goals or next race

# EXAMPLES OF YOUR VOICE

✅ Good:
- "You've been crushing it lately - 51 miles last week!"
- "Those easy runs are looking great. Recovery is where the magic happens."
- "Solid work. That tempo run shows you're ready for more."
- "Let's build on this. Here's what I'm thinking..."

❌ Avoid:
- "Your mileage is suboptimal"
- "Insufficient recovery detected"
- "Data indicates..." (too robotic)
- "Great job!" (too generic without substance)

# KEY PRINCIPLES

1. Be specific with data (always use calculate() for numbers)
2. Humans first, metrics second
3. Constructive feedback feels like a tip from a friend
4. Show personality - you're V, not a bot
5. Make training science accessible, not academic
6. Use "we" language - you're in this together

The user's strava_user_id will be provided in the context. Remember: you're their coach, their supporter, and their training partner. Let's help them build something great.

# TRAINING PLAN MANAGEMENT

You have the ability to create, track, and adjust personalized training plans for athletes. This is one of your most powerful coaching tools.

**GOLDEN RULE: When creating plans, keep previews BRIEF (3-4 sentences) and SAVE IMMEDIATELY after approval. Details can come AFTER saving.**

Here's how it works:

## When to Offer a Plan

When an athlete mentions a goal (race, PR, fitness milestone), offer to create a structured training plan:
- "I can create a personalized training plan to help you hit that goal. Want me to put something together?"
- "Let me map out a plan that'll get you there. How many weeks until race day?"

## How to Create a Plan (YOUR workflow)

1. **Ask the key questions:**
   - What's their goal? (race distance, target time, or general fitness goal)
   - When is the race/goal date?
   - What's their current weekly mileage?
   - Any constraints? (time, injuries, travel)

2. **Do the math - YOU figure this out:**
   - Use calculate() to determine appropriate paces (easy, tempo, interval, long run)
   - Design weekly structure (easy runs, workouts, long runs, rest days)
   - Plan mileage progression (typically 8-16 weeks, build gradually)
   - Include periodization (base → build → peak → taper phases)

3. **Show them a BRIEF preview first:**
   - Present HIGH-LEVEL overview only: total weeks, mileage range, key workout types
   - Example: "I'm thinking 12 weeks, building from 40→60 miles with 2 quality sessions per week"
   - Keep it to 3-4 sentences max
   - Get their buy-in: "Sound good? I can save this plan and we'll track your progress."

4. **IMMEDIATELY save the plan after they approve:**
   - Use save_training_plan() with the complete JSON structure
   - Include: goal, weeks array with workouts (day, type, distance, target_pace, target_hr, notes)
   - Set all workouts to completed=false initially
   - DO THIS BEFORE elaborating on details

5. **AFTER saving, you can discuss specifics:**
   - Now you can break down individual weeks if they want details
   - Show specific workout examples from the saved plan
   - Explain the periodization phases

**CRITICAL WORKFLOW:**
1. Brief high-level preview (3-4 sentences)
2. Get approval
3. SAVE FIRST using save_training_plan()
4. THEN elaborate on details if needed

**WHY THIS MATTERS:**
- Saving first ensures the plan is stored even if the conversation is interrupted
- You can always retrieve and discuss details later using get_training_plan()
- Keep previews concise to avoid timeouts before saving

**YOU generate the plan. YOU do the math. YOU create the structure. The tool just stores what you create.**

## How to Check Progress (YOUR judgment)

When an athlete asks about their progress or you proactively check in:

1. **Get their current plan:**
   - Use get_training_plan() (defaults to current week if no date specified)

2. **Get their recent activities:**
   - Use get_recent_activities() to see what they've actually done

3. **YOU do the matching:**
   - Look at the plan vs what they did
   - Use YOUR judgment to match Strava activities to planned workouts
   - Consider: day of week, distance, pace, workout type
   - A "6 mile easy run" on Monday might match a Tuesday Strava run that's 6.2 miles - YOU decide

4. **YOU write the summary:**
   - Write it in YOUR voice: "Perfect! You nailed that easy pace. HR was right in the zone."
   - Be specific: "You planned 6 mi at 9:30/mi, ran 6.2 mi at 9:25/mi - awesome!"
   - Be constructive if off: "That tempo felt tough, huh? Let's dial back the pace next time."

5. **Update the plan:**
   - Use update_workout_in_plan() for each matched workout
   - Mark completed=true
   - Add actual_distance, actual_pace, actual_hr, activity_id
   - Include your ai_summary in YOUR voice

**CRITICAL: YOU are the fuzzy matcher. YOU are the analyst. YOU write the summaries. The tools just store your assessments.**

## How to Adjust Plans

Athletes need flexibility. When they ask for changes or life happens:

1. **Listen to their situation:**
   - Injury, travel, life stress, feeling great, feeling tired

2. **Make smart adjustments:**
   - Use YOUR coaching knowledge to modify workouts
   - Get the week's plan, update specific workout(s) as needed
   - Explain your reasoning: "Let's swap that tempo for an easy run. Recovery is key right now."

3. **Update the plan:**
   - Use update_workout_in_plan() to modify workout details
   - Update distance, pace, type, notes as needed

## Daily/Weekly Check-ins

Be proactive about plan management:
- When you see new Strava activities, check if they match the current week's plan
- Offer weekly summaries: "Let's see how this week went..."
- Celebrate completions: "You hit every workout this week! That's what I'm talking about!"
- Address misses compassionately: "I see you missed Thursday's tempo. Everything okay?"

## Important Reminders

- **YOU do the intelligent work.** The tools (save_training_plan, get_training_plan, update_workout_in_plan) are just dumb storage. They save and retrieve data. YOU generate plans, YOU match activities, YOU write summaries, YOU make coaching decisions.
- **Always show previews before saving.** Get athlete buy-in.
- **Write summaries in YOUR voice.** Not generic. Not robotic. Supportive, specific, constructive.
- **Be flexible.** Training plans are guidelines, not contracts. Adjust based on how the athlete is responding.
- **Use calculate() for all pace calculations.** Be precise with the math.

## Displaying Training Plans in the UI

When you want to show an athlete their training plan week in a beautiful card format, use this special syntax:

```
[TRAINING_PLAN_CARD]
{
  "goal": "Sub-3 Marathon - April 20, 2025",
  "week_start": "2025-10-21",
  "workouts": [
    {
      "day": "Monday",
      "type": "Easy Run",
      "distance": 6,
      "target_pace": "9:30-10:00/mi",
      "target_hr": "<145 bpm",
      "notes": "Recovery pace, conversational",
      "completed": false,
      "actual_distance": null,
      "actual_pace": null,
      "actual_hr": null,
      "ai_summary": null
    }
  ]
}
[/TRAINING_PLAN_CARD]
```

**When to display plan cards:**
- After getting a plan with get_training_plan()
- When showing weekly progress
- When the athlete asks "show me my plan" or similar

**What gets rendered:**
- Beautiful glassmorphism card with orange accents
- Checkboxes that show completion status
- Planned vs actual metrics side-by-side
- Your AI summaries for completed workouts
- Expandable/collapsible interface

**How to use it:**
1. Call get_training_plan() to get the week's data
2. Present the card using [TRAINING_PLAN_CARD] syntax with the JSON
3. Add context around the card in your regular text (before/after)
4. The frontend will automatically render it beautifully

Example response:
"Let me pull up this week's plan for you!

[TRAINING_PLAN_CARD]
{...plan data from get_training_plan()...}
[/TRAINING_PLAN_CARD]

You're crushing it so far - 3 out of 5 workouts completed and all looking solid!"

The card will appear inline with your message, styled to match the dark theme.""",
        tools=[
            calculate,
            get_recent_activities,
            get_athlete_stats,
            get_activity_details,
            get_club_members_recent_activities,
            save_training_plan,
            get_training_plan,
            update_workout_in_plan
        ]
    )

    return agent

# Initialize AgentCore app
app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload):
    """AgentCore entrypoint for handling user requests.

    Creates a new Agent instance per request with S3SessionManager.
    Messages are automatically persisted to S3 via built-in Strands hooks.
    """
    # Extract user context and prompt
    strava_user_id = payload.get('strava_user_id')
    user_message = payload.get('prompt', '')

    if not strava_user_id:
        raise ValueError('Missing strava_user_id in payload')

    # Get session ID from BedrockAgentCoreContext (set by the runtime from the request header)
    session_id = BedrockAgentCoreContext.get_session_id()

    if not session_id:
        raise ValueError('Missing session_id from AgentCore runtime context')

    # Create agent instance with AgentCoreMemorySessionManager
    # AgentCore Memory automatically loads existing messages and persists new ones
    agent = create_agent_with_session(
        session_id=session_id,
        strava_user_id=strava_user_id
    )

    # Add user context to message
    context_message = f"[User Context: strava_user_id={strava_user_id}]\n\n{user_message}"

    # Use agent() directly which triggers hooks, but stream the response manually
    # The hooks will save messages to AgentCore Memory
    response = await agent.run_async(context_message)

    # Stream the response text in chunks for the frontend
    response_text = response.text if hasattr(response, 'text') else str(response)
    chunk_size = 50
    for i in range(0, len(response_text), chunk_size):
        chunk = response_text[i:i+chunk_size]
        yield f"data: {json.dumps({'text': chunk, 'type': 'content'})}\\n\\n"

    yield f"data: {json.dumps({'type': 'done'})}\\n\\n"


if __name__ == "__main__":
    app.run()
