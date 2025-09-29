"""
Memory manager utility functions for DynamoDB operations and message handling.

Async support is added: 
- Converted I/O OPs to aioboto3 so the event loop is not blocked by network calls.
- Keeping dataclass shapes intact; ThreadState.lock uses an asyncio.Lock by default
- Use botocore Config with a configurable connection pool for connection reuse.
"""

import os
import time
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv
import aioboto3
from botocore.exceptions import ClientError
from botocore.config import Config
import asyncio
import threading
from langchain_core.messages import HumanMessage, AIMessage

load_dotenv()
# Configuration from environment
CHAT_HISTORY_TABLE = os.getenv("CHAT_HISTORY_TABLE")
AWS_REGION = os.getenv("AWS_REGION")
SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_SECONDS"))  # e.g. 6 hours
CONTEXT_PAIRS = int(os.getenv("CONTEXT_PAIRS"))
BATCH_PAIRS = int(os.getenv("BATCH_PAIRS"))
MAX_RAM_PAIRS = int(os.getenv("MAX_RAM_PAIRS"))

# Connection pooling default (tweak during load tests)
DEFAULT_MAX_POOL_CONNECTIONS = 50


@dataclass
class Message:
    """Represents a single chat message"""
    role: str  # 'user' or 'assistant'
    content: str
    ts_iso: str
    seq: int
    turn: int  # pair index
    meta: Optional[Dict[str, Any]] = None
    
    def to_dict(self):
        """Convert Message to dictionary for serialization"""
        return {
            'role': self.role,
            'content': self.content,
            'ts_iso': self.ts_iso,
            'seq': self.seq,
            'turn': self.turn,
            'meta': self.meta
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create Message from dictionary"""
        return cls(**data)


@dataclass
class Pair:
    """Represents a user-assistant message pair"""
    turn: int
    user_message: Message
    assistant_message: Optional[Message] = None

    @property
    def is_complete(self) -> bool:
        """Check if pair has both user and assistant messages"""
        return self.assistant_message is not None

    def to_messages(self) -> List[Dict[str, str]]:
        """Convert pair to list of message dicts for LLM"""
        messages = [{"role": self.user_message.role, "content": self.user_message.content}]
        if self.assistant_message:
            messages.append({"role": self.assistant_message.role, "content": self.assistant_message.content})
        return messages

    def to_langchain_messages(self) -> List[Any]:
        """Convert pair to LangChain message objects"""
        messages = [HumanMessage(content=self.user_message.content)]
        if self.assistant_message:
            messages.append(AIMessage(content=self.assistant_message.content))
        return messages

    def to_dict(self):
        """Convert Pair to dictionary for serialization"""
        return {
            'turn': self.turn,
            'user_message': self.user_message.to_dict(),
            'assistant_message': self.assistant_message.to_dict() if self.assistant_message else None
        }

    @classmethod
    def from_dict(cls, data):
        """Create Pair from dictionary"""
        user_msg = Message.from_dict(data['user_message'])
        assistant_msg = Message.from_dict(data['assistant_message']) if data['assistant_message'] else None
        return cls(
            turn=data['turn'],
            user_message=user_msg,
            assistant_message=assistant_msg
        )


@dataclass
class ThreadState:
    """State for a conversation thread"""
    thread_id: str
    session_id: str
    last_activity_at: float
    next_seq: int = 1
    next_turn: int = 1
    context_pairs: List[Pair] = field(default_factory=list)
    batch_pairs: List[Pair] = field(default_factory=list)
    open_pair: Optional[Pair] = None
    # default to asyncio.Lock for async-safe usage in MemoryManager
    # lock: asyncio.Lock = field(default_factory=lambda: asyncio.Lock())
    #  MEmoryManager already has an async function:  _ensure_thread_lock() that converts lock to asyncio.Lock()
    lock: threading.Lock = field(default_factory=threading.Lock)
    
    def to_dict(self):
        """Convert ThreadState to dictionary for serialization"""
        return {
            'thread_id': self.thread_id,
            'session_id': self.session_id,
            'last_activity_at': self.last_activity_at,
            'next_seq': self.next_seq,
            'next_turn': self.next_turn,
            'context_pairs': [pair.to_dict() for pair in self.context_pairs],
            'batch_pairs': [pair.to_dict() for pair in self.batch_pairs],
            'open_pair': self.open_pair.to_dict() if self.open_pair else None
        }

    @classmethod
    def from_dict(cls, data):
        """Create ThreadState from dictionary"""
        context_pairs = [Pair.from_dict(pair_data) for pair_data in data['context_pairs']]
        batch_pairs = [Pair.from_dict(pair_data) for pair_data in data['batch_pairs']]
        open_pair = Pair.from_dict(data['open_pair']) if data['open_pair'] else None
        
        # Create ThreadState instance
        thread_state = cls(
            thread_id=data['thread_id'],
            session_id=data['session_id'],
            last_activity_at=data['last_activity_at'],
            next_seq=data['next_seq'],
            next_turn=data['next_turn'],
            context_pairs=context_pairs,
            batch_pairs=batch_pairs,
            open_pair=open_pair
        )
        
        # Set the lock to asyncio.Lock for compatibility with async MemoryManager
        thread_state.lock = asyncio.Lock()
        return thread_state


def get_now_iso() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


# --- Helper to decide client vs session usage ---
async def _use_client(context, func, *args, **kwargs):
    """Helper: if `context` looks like an aioboto3 Session, open a client and run
    the coroutine `func(client, *args, **kwargs)`. If `context` is already a
    client, call func directly.

    This keeps the utilities flexible: callers may pass either an aioboto3.Session
    or an already-open aioboto3 client.
    """
    # If context has 'client' attribute, assume it's a Session
    if hasattr(context, 'client') and callable(getattr(context, 'client')):
        # treat as Session
        # configure a default pool for short-lived clients
        botocore_cfg = Config(max_pool_connections=DEFAULT_MAX_POOL_CONNECTIONS)
        async with context.client('dynamodb', region_name=AWS_REGION, config=botocore_cfg) as client:
            return await func(client, *args, **kwargs)
    else:
        # assume it's already a client
        return await func(context, *args, **kwargs)


async def get_next_seq_from_dynamodb(dynamodb_context, thread_id: str) -> int:
    """Get next sequence number atomically from DynamoDB (async).

    `dynamodb_context` can be an aioboto3.Session or an aioboto3 client.
    """

    async def _op(client):
        try:
            response = await client.update_item(
                TableName=CHAT_HISTORY_TABLE,
                Key={
                    'thread_id': {'S': thread_id},
                    'seq': {'N': '0'}  # Meta row for counters
                },
                UpdateExpression='ADD next_seq :one',
                ExpressionAttributeValues={':one': {'N': '1'}},
                ReturnValues='UPDATED_NEW'
            )
            next_seq = int(response['Attributes']['next_seq']['N'])
            print(f"[MemoryManager] Got next sequence {next_seq} for thread {thread_id}")
            return next_seq
        except ClientError as e:
            # If meta row doesn't exist, initialize it (race-safe via ConditionalExpression)
            print(f"[MemoryManager] Creating new counter row for thread {thread_id}")
             # If meta row doesn't exist, initialize it
            try:
                await client.put_item(
                    TableName=CHAT_HISTORY_TABLE,
                    Item={
                        'thread_id': {'S': thread_id},
                        'seq': {'N': '0'},
                        'next_seq': {'N': '1'},
                        'next_turn': {'N': '1'},
                        'role': {'S': 'META'},
                        'content': {'S': 'Counter row'},
                        'ts_iso': {'S': get_now_iso()}
                    },
                    ConditionExpression='attribute_not_exists(thread_id)'
                )
                print(f"[MemoryManager] Created new counter row for thread {thread_id}")
                return 1
            except ClientError:
                # Race condition - try again
                return await get_next_seq_from_dynamodb(dynamodb_context, thread_id)

    return await _use_client(dynamodb_context, _op)


async def get_next_turn_from_dynamodb(dynamodb_context, thread_id: str) -> int:
    """Get next turn number atomically from DynamoDB (async)."""

    async def _op(client):
        try:
            response = await client.update_item(
                TableName=CHAT_HISTORY_TABLE,
                Key={
                    'thread_id': {'S': thread_id},
                    'seq': {'N': '0'}  # Meta row for counters
                },
                UpdateExpression='ADD next_turn :one',
                ExpressionAttributeValues={':one': {'N': '1'}},
                ReturnValues='UPDATED_NEW'
            )
            next_turn = int(response['Attributes']['next_turn']['N'])
            print(f"[MemoryManager] Got next turn {next_turn} for thread {thread_id}")
            return next_turn
        except ClientError:
            # Meta row should exist from get_next_seq
            return await get_next_turn_from_dynamodb(dynamodb_context, thread_id)

    return await _use_client(dynamodb_context, _op)


async def read_pairs_from_dynamodb(dynamodb_context, thread_id: str, n: int) -> List[Pair]:
    """Read last n complete pairs from DynamoDB (async)."""

    async def _op(client):
        try:
            print(f"[MemoryManager] Reading last {n} pairs from DynamoDB for thread {thread_id}")
            # Query in reverse order to get most recent messages
            response = await client.query(
                TableName=CHAT_HISTORY_TABLE,
                KeyConditionExpression='thread_id = :tid AND seq > :zero',
                ExpressionAttributeValues={
                    ':tid': {'S': thread_id},
                    ':zero': {'N': '0'}
                },
                ScanIndexForward=False,
                Limit=n * 2 + 10
            )

            items = response.get('Items', [])
            print(f"[MemoryManager] Retrieved {len(items)} items from DynamoDB")
            # Group messages by turn to form pairs
            messages_by_turn: Dict[int, Dict[str, Message]] = {}
            for item in items:
                role = item['role']['S']
                if role == 'META':
                    continue
                turn = int(item['turn']['N'])
                message = Message(
                    role=role,
                    content=item['content']['S'],
                    ts_iso=item['ts_iso']['S'],
                    seq=int(item['seq']['N']),
                    turn=turn,
                    meta=item.get('meta', {}).get('M', {}) if 'meta' in item else None
                )
                if turn not in messages_by_turn:
                    messages_by_turn[turn] = {}
                messages_by_turn[turn][role] = message
        # Convert to pairs and sort by turn (chronological order)
            pairs = []
            for turn in sorted(messages_by_turn.keys(), reverse=True):
                turn_messages = messages_by_turn[turn]
                if 'user' in turn_messages:
                    pair = Pair(
                        turn=turn,
                        user_message=turn_messages['user'],
                        assistant_message=turn_messages.get('assistant')
                    )
                    if pair.is_complete:
                        pairs.append(pair)

            final_pairs = list(reversed(pairs[:n]))
            print(f"[MemoryManager] Loaded {len(final_pairs)} complete pairs for thread {thread_id}")
            return final_pairs

        except ClientError as e:
            print(f"[MemoryManager] Error reading pairs from DynamoDB for thread {thread_id}: {e}")
            return []

    return await _use_client(dynamodb_context, _op)


async def load_conversation_state_from_dynamodb(dynamodb_context, thread_id: str) -> List[Pair]:
    """Load conversation state from DynamoDB (async). Tries new format first."""

    async def _op(client):
        try:
            print(f"[MemoryManager] Loading conversation state for thread {thread_id}")
            response = await client.get_item(
                TableName=CHAT_HISTORY_TABLE,
                Key={
                    'thread_id': {'S': thread_id},
                    'seq': {'N': '-1'}  # Conversation state stored at seq=-1
                }
            )
            if 'Item' in response and response['Item']:
                item = response['Item']
                messages_json = item.get('messages', {}).get('S', '[]')
                messages = json.loads(messages_json)

                pairs = []
                current_pair = None
                for msg in messages:
                    if msg['role'] == 'user':
                        user_message = Message(
                            role=msg['role'],
                            content=msg['content'],
                            ts_iso=msg['ts_iso'],
                            seq=1,
                            turn=msg['turn']
                        )
                        current_pair = Pair(turn=msg['turn'], user_message=user_message)
                    elif msg['role'] == 'assistant' and current_pair:
                        assistant_message = Message(
                            role=msg['role'],
                            content=msg['content'],
                            ts_iso=msg['ts_iso'],
                            seq=2,
                            turn=msg['turn']
                        )
                        current_pair.assistant_message = assistant_message
                        pairs.append(current_pair)
                        current_pair = None

                if current_pair:
                    pairs.append(current_pair)

                print(f"[MemoryManager] Loaded {len(pairs)} pairs from conversation state")
                return pairs

            else:
                print(f"[MemoryManager] No conversation state found, falling back to reading individual messages")
                try:
                    return await read_pairs_from_dynamodb(dynamodb_context, thread_id, CONTEXT_PAIRS)
                except Exception as fallback_error:
                    print(f"[MemoryManager] Fallback read_pairs_from_dynamodb also failed: {fallback_error}")
                    return []

        except Exception as e:
            print(f"[MemoryManager] Error loading conversation state for thread {thread_id}: {e}")
            try:
                return await read_pairs_from_dynamodb(dynamodb_context, thread_id, CONTEXT_PAIRS)
            except Exception:
                return []

    return await _use_client(dynamodb_context, _op)

# ---- Safe sync wrappers (deprecated; migration helpers) ----

def _run_awaitable_safely(awaitable):
    """
    Run awaitable synchronously for legacy sync callers.

    IMPORTANT: This should NOT be called from inside an already-running event loop
    (for example, inside FastAPI request code). If a running loop is detected we
    raise a clear RuntimeError that tells the caller what to do.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # no running loop in this thread -> safe to run
        return asyncio.run(awaitable)
    else:
        # there is a running loop in THIS thread (likely ASGI). Fail fast with guidance.
        raise RuntimeError(
            "Sync wrapper cannot be called from inside an active asyncio event loop. "
            "If you're inside async code, use `await get_next_seq_from_dynamodb(...)` instead. "
            "If you must call from sync code, run this in a separate thread or use "
            "`memory_manager.run_sync(...)` from a dedicated thread (but prefer migrating to async)."
        )

def get_next_seq_from_dynamodb_sync(dynamodb_session, thread_id: str) -> int:
    return _run_awaitable_safely(get_next_seq_from_dynamodb(dynamodb_session, thread_id))

def get_next_turn_from_dynamodb_sync(dynamodb_session, thread_id: str) -> int:
    return _run_awaitable_safely(get_next_turn_from_dynamodb(dynamodb_session, thread_id))

def read_pairs_from_dynamodb_sync(dynamodb_session, thread_id: str, n: int) -> List[Pair]:
    return _run_awaitable_safely(read_pairs_from_dynamodb(dynamodb_session, thread_id, n))

def load_conversation_state_from_dynamodb_sync(dynamodb_session, thread_id: str) -> List[Pair]:
    return _run_awaitable_safely(load_conversation_state_from_dynamodb(dynamodb_session, thread_id))
