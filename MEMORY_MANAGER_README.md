# Chat Memory Manager for LangGraph Flight Bot

This document describes the pair-based chat memory system that provides persistent conversation history backed by DynamoDB while preserving LangGraph's InMemorySaver for checkpointing.

## Overview

The Memory Manager implements a two-layer architecture:

- **LangGraph Layer**: InMemorySaver continues to handle checkpointing for graph state persistence
- **Chat History Layer**: MemoryManager provides conversation-aware memory with pair-based organization, context windowing, and DynamoDB persistence

## Key Concepts

### Messages and Pairs

- **Message**: A single utterance (user or assistant)
- **Pair/Turn**: A [user, assistant] message pair that belongs together
- **Open Pair**: A user message waiting for an assistant reply
- **Complete Pair**: A pair with both user and assistant messages

### Memory Architecture

- **Context Window (RAM)**: Last 15 pairs (up to 30 messages) passed to the LLM
- **Batch Buffer (RAM)**: Up to 10 pairs waiting to be written to DynamoDB
- **DynamoDB**: Persistent storage for conversation history
- **Hard Cap**: Maximum 20 pairs in RAM (context + batch) to prevent memory issues

## Configuration

Set these environment variables:

```bash
# Required
CHAT_HISTORY_TABLE=your_dynamodb_table_name
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# Optional (with defaults)
SESSION_IDLE_SECONDS=21600     # 6 hours
CONTEXT_PAIRS=15               # Pairs in context window
BATCH_PAIRS=10                 # Pairs in batch buffer
MAX_RAM_PAIRS=20               # Hard limit for RAM usage
```

### DynamoDB Table Schema

The table should already exist with this schema:

```
Primary Key:
- thread_id (String) - Partition key
- seq (Number) - Sort key (strictly increasing)

Attributes:
- role (String) - "user" or "assistant"
- content (String) - Message content
- ts_iso (String) - ISO timestamp
- session_id (String) - Session identifier
- turn (Number) - Pair index
- meta (Map) - Optional metadata
- ttl (Number) - Optional TTL for automatic cleanup
```

## Integration

### graph_config.py

The integration is already implemented in `graph_config.py`. Here's how it works:

```python
from app.langgraph.memory_manager import memory_manager

def invoke_graph(graph, user_message: str, thread_id: str = "default"):
    # 1. Initialize session and handle idle timeout
    memory_manager.on_session_start(thread_id)

    # 2. Add user message (starts new pair)
    memory_manager.add_user_message(thread_id, user_message)

    # 3. Get context for LLM (flattened pairs)
    context_messages = memory_manager.get_context_for_llm(thread_id)

    # 4. Convert to LangChain messages and invoke graph
    langchain_messages = [...]  # Convert context_messages
    state = graph.invoke({"messages": langchain_messages}, ...)

    # 5. Extract response and close pair
    assistant_text = extract_last_ai_text(state)
    if assistant_text:
        memory_manager.add_assistant_message(thread_id, assistant_text)

    return state
```

### main.py

No changes needed in `main.py`. The integration happens transparently in `invoke_graph()`:

```python
# This call now includes memory management
state = invoke_graph(graph, Body, thread_id)
```

## API Reference

### Session Management

#### `on_session_start(thread_id: str) -> None`

- Initializes or resumes a conversation session
- Handles idle timeout (>6h) by flushing old data and starting fresh
- Loads last 15 pairs from DynamoDB into RAM context
- Updates activity timestamp

```python
# Called automatically by invoke_graph()
memory_manager.on_session_start(thread_id)
```

#### `on_session_end(thread_id: str) -> None`

- Ends a session and flushes all remaining pairs to DynamoDB
- Clears RAM state

```python
# Call when conversation definitively ends
memory_manager.on_session_end(thread_id)
```

### Message Management

#### `add_user_message(thread_id: str, content: str) -> None`

- Adds a user message and starts a new pair
- Assigns sequence number and turn number
- Updates activity timestamp

#### `add_assistant_message(thread_id: str, content: str) -> None`

- Adds assistant message and closes the current pair
- Moves completed pair to context window
- Triggers eviction if context > 15 pairs
- Triggers batch flush if batch = 10 pairs
- Enforces RAM hard cap

### Context Retrieval

#### `get_context_for_llm(thread_id: str) -> list[dict]`

- Returns flattened context (last 15 pairs) for LLM
- Includes open pair user message if exists
- Format: `[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]`

```python
context = memory_manager.get_context_for_llm(thread_id)
# Returns up to 31 messages (15 complete pairs + 1 open user message)
```

### Persistence Operations

#### `flush_batch(thread_id: str) -> None`

- Manually flush batch buffer to DynamoDB
- Automatically called when batch reaches 10 pairs

#### `flush_all(thread_id: str) -> None`

- Flush all pairs (context + batch) to DynamoDB
- Clears all RAM state
- Called on session end or idle timeout

## Behavioral Rules

### Eviction and Batching

1. **Pair Completion**: Eviction only happens after assistant reply closes a pair
2. **Context Limit**: If context > 15 pairs, oldest pair moves to batch buffer
3. **Batch Flush**: When batch = 10 pairs, batch-write to DynamoDB and clear buffer
4. **RAM Limit**: If context + batch > 20 pairs, flush batch early

### Session Lifecycle

1. **Activity Tracking**: Every `add_*` call updates `last_activity_at`
2. **Idle Detection**: >6h idle triggers `flush_all()` and new session
3. **Restart Recovery**: `on_session_start()` loads last 15 pairs from DynamoDB
4. **Graph Consistency**: InMemorySaver automatically maintains checkpointing when graph is invoked

### Error Handling

- **Idempotency**: (thread_id, seq) provides unique identification
- **Retry Logic**: Batch writes retry unprocessed items with exponential backoff
- **Graceful Degradation**: Failures in memory operations don't crash the main flow

## Data Flow Example

```
User: "Book a flight to NYC"
├─ on_session_start(thread_id)
│  ├─ Check idle timeout
│  └─ Load last 15 pairs from DynamoDB
├─ add_user_message(thread_id, "Book a flight to NYC")
│  └─ Creates open pair with user message
├─ get_context_for_llm(thread_id)
│  └─ Returns [context_pairs + open_user_message]
├─ LLM processes with full context (InMemorySaver handles checkpointing)
├─ add_assistant_message(thread_id, "I can help with that...")
│  ├─ Closes pair
│  ├─ Adds to context
│  ├─ Checks eviction (context > 15?)
│  ├─ Checks batch flush (batch = 10?)
│  └─ Enforces RAM limit
└─ Return response
```

## Testing

Run the comprehensive test suite:

```bash
# Install test dependencies
pip install pytest moto

# Run all tests
pytest tests/test_memory_manager.py -v

# Run specific test categories
pytest tests/test_memory_manager.py::TestWindowingAndBatching -v
pytest tests/test_memory_manager.py::TestSessionManagement -v
pytest tests/test_memory_manager.py::TestLLMContract -v
```

### Test Categories

- **Basic Operations**: Message/pair creation, state management
- **Windowing & Batching**: Context limits, batch flushing, RAM enforcement
- **Session Management**: Idle timeout, session lifecycle, crash recovery
- **LLM Contract**: Message limits, ordering, context consistency
- **DynamoDB Operations**: Counter management, read/write operations
- **Concurrency**: Thread safety, concurrent access
- **End-to-End**: Complete conversation flows with all features

## Architecture Benefits

### Separation of Concerns

- **InMemorySaver**: Handles LangGraph's internal checkpointing needs
- **MemoryManager**: Handles conversation-aware chat history and persistence

### Performance Optimization

- **Context Windowing**: Limits LLM input to recent relevant history
- **Batch Writing**: Reduces DynamoDB API calls and costs
- **RAM Management**: Prevents memory bloat in long conversations

### Reliability Features

- **Idle Timeout**: Prevents stale sessions from consuming resources
- **Crash Recovery**: Reconstructs state from DynamoDB after restarts
- **Atomic Counters**: Ensures sequence integrity across restarts
- **Retry Logic**: Handles transient DynamoDB failures

### Scalability

- **Thread Safety**: Supports concurrent conversations
- **DynamoDB Backend**: Scales to handle many concurrent users
- **Memory Bounded**: Fixed RAM usage per conversation thread

## Troubleshooting

### Common Issues

**Memory not persisting between restarts**

- Ensure DynamoDB credentials are configured
- Verify that `on_session_start()` is loading context from DynamoDB
- Check that context is being passed correctly to the graph

**Context not loading**

- Verify DynamoDB table exists and has correct schema
- Check AWS permissions for table access

**Messages out of order**

- Sequence counters ensure proper ordering
- If issues persist, check for concurrent access without proper locking

**High DynamoDB costs**

- Batch writes minimize API calls (20 items per batch)
- Consider adding TTL to auto-delete old messages
- Monitor and adjust `CONTEXT_PAIRS` if needed

### Monitoring

Key metrics to monitor:

- Average pairs per session
- Batch flush frequency
- Session idle timeout frequency
- DynamoDB read/write capacity usage
- Memory manager operation latency

### Environment Variables Debug

```python
# Add to memory_manager.py for debugging
import os
print(f"CHAT_HISTORY_TABLE: {os.getenv('CHAT_HISTORY_TABLE')}")
print(f"CONTEXT_PAIRS: {CONTEXT_PAIRS}")
print(f"BATCH_PAIRS: {BATCH_PAIRS}")
print(f"SESSION_IDLE_SECONDS: {SESSION_IDLE_SECONDS}")
```

## Future Enhancements

Potential improvements for future versions:

1. **Message Summarization**: Compress very old context into summaries
2. **Selective Loading**: Load context based on conversation topics/intents
3. **Analytics Integration**: Track conversation patterns and effectiveness
4. **Multi-Modal Support**: Handle images, documents, etc. in message pairs
5. **Conversation Branching**: Support multiple conversation branches per thread
