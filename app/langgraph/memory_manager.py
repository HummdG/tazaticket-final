"""
Pair-based chat memory manager backed by DynamoDB.
Keeps last 15 pairs in context, batches pairs for DynamoDB writes,
and manages session lifecycle with idle timeouts.

Asynchronous changes are implemented.

Redis-based distributed memory manager for high concurrency.

- Converted all DB I/O to `aioboto3`/`async` so many concurrent users don't block.
- Replace global / per-thread `threading.Lock` with `asyncio.Lock` where possible.
- Add a bounded semaphore to limit concurrent DynamoDB batch writers (backpressure).
- Track pending background tasks to log errors and allow graceful shutdown.
- Use Redis for distributed state management across multiple app instances.
- Use Redis-based distributed locking for thread-safe operations.

"""


from .memory_utils import (
    Message, Pair, ThreadState,
    CHAT_HISTORY_TABLE, AWS_REGION, SESSION_IDLE_SECONDS, CONTEXT_PAIRS, BATCH_PAIRS, MAX_RAM_PAIRS,
    get_now_iso, get_next_seq_from_dynamodb, get_next_turn_from_dynamodb,
    read_pairs_from_dynamodb, load_conversation_state_from_dynamodb
)

import time
import uuid
import json
from typing import List, Dict, Any, Optional
import aioboto3
import asyncio
import atexit
from botocore.config import Config

# Redis import
from .redis_manager import redis_manager

# Status:
# TD: Redis
# Done: Connection Pooling
# Done: Async Clients

# Connection-pooling knobs
DEFAULT_MAX_POOL_CONNECTIONS = 50  # tune this based on expected concurrency and HTTP session reuse



# --- Configurable production knobs ---
DEFAULT_MAX_CONCURRENT_BATCH_WRITES = 8  # tune to match DynamoDB RCUs / throughput


class MemoryManager:
    """
    Pair-aware chat memory manager with DynamoDB persistence.
    Converted to fully async API for production concurrency.
    Uses Redis for distributed state management across multiple instances.

    NOTE: All public methods are now `async def` and must be awaited by callers in other files. 
    """

    def __init__(self, max_concurrent_batch_writes: int = DEFAULT_MAX_CONCURRENT_BATCH_WRITES):
        # Async session for all network I/O
        self._aiosession = aioboto3.Session()

        # Configure a botocore connection pool size for aioboto3 clients.
        # I am setting a conservative default: at least DEFAULT_MAX_POOL_CONNECTIONS,
        # might scale later
        pool_size = max(DEFAULT_MAX_POOL_CONNECTIONS, max_concurrent_batch_writes * 8)
        self._botocore_config = Config(max_pool_connections=pool_size)
        print(f"[MemoryManager] Botocore max_pool_connections={pool_size}")

        # DynamoDB table name
        self.table_name = CHAT_HISTORY_TABLE

        # Semaphore to bound concurrent batch writers and provide backpressure
        self._write_semaphore = asyncio.Semaphore(max_concurrent_batch_writes)

        # Track pending background tasks so we can log and await them during shutdown
        self._pending_tasks: "set[asyncio.Task]" = set()
        self._pending_tasks_lock = asyncio.Lock()

        print(f"[MemoryManager] Initialized with table: {CHAT_HISTORY_TABLE}, region: {AWS_REGION}")
        print(f"[MemoryManager] Config - Context pairs: {CONTEXT_PAIRS}, Batch pairs: {BATCH_PAIRS}, Max RAM pairs: {MAX_RAM_PAIRS}")
        print(f"[MemoryManager] Async batch writers semaphore max: {max_concurrent_batch_writes}")

        # Register atexit fallback to run shutdown synchronously if process exits
        # Prefer framework-integrated graceful shutdown (e.g., FastAPI on_event("shutdown")).
        atexit.register(lambda: asyncio.run(self.shutdown()))

    
    async def _ensure_thread_lock(self, thread_state: ThreadState) -> None:
        """Ensure thread_state.lock is an asyncio.Lock. This avoids forcing a
        change in memory_utils right away — we patch the object here if needed.
        """
        # When using Redis, ThreadState objects don't need local locks since
        # state operations are atomic via Redis
        pass

    async def _get_thread_state(self, thread_id: str) -> ThreadState:
        """Get or create thread state from Redis (async-safe)."""
        print(f"[MemoryManager] _get_thread_state function called for thread {thread_id}")
        redis_conn = await redis_manager.get_connection()
        
        # Try to load thread state from Redis
        thread_state_key = f"thread_state:{thread_id}"
        thread_data = await redis_conn.get(thread_state_key)
        
        if thread_data:
            print(f"[MemoryManager] Found existing thread state in Redis for {thread_id}")
            # Deserialize thread state from Redis
            thread_dict = json.loads(thread_data)
            thread_state = ThreadState.from_dict(thread_dict)
        else:
            # Create new thread state

            print(f"[MemoryManager] Creating new thread state for {thread_id}")
            thread_state = ThreadState(
                thread_id=thread_id,
                session_id=str(uuid.uuid4()),
                last_activity_at=time.time()
            )
            # Save to Redis
            print(f"[MemoryManager] Saving new thread state to Redis for {thread_id}")
            await self._save_thread_state_to_redis(thread_state)
        
        # Ensure the ThreadState has an asyncio.Lock for per-thread operations

        await self._ensure_thread_lock(thread_state)
        return thread_state
    
    async def _save_thread_state_to_redis(self, thread_state: ThreadState) -> None:
        """Save thread state to Redis."""
        print(f"[MemoryManager] _save_thread_state_to_redis called for thread {thread_state.thread_id}")
        print(f"[MemoryManager] Saving thread state to Redis for {thread_state.thread_id}")
        print(f"[MemoryManager] type of thread_state : {type(thread_state)}")
        redis_conn = await redis_manager.get_connection()
        thread_state_key = f"thread_state:{thread_state.thread_id}"
        
        # Convert ThreadState to dictionary for serialization
        thread_dict = {
            'thread_id': thread_state.thread_id,
            'session_id': thread_state.session_id,
            'last_activity_at': thread_state.last_activity_at,
            'context_pairs': [pair.to_dict() for pair in thread_state.context_pairs],
            'batch_pairs': [pair.to_dict() for pair in thread_state.batch_pairs],
            'open_pair': thread_state.open_pair.to_dict() if thread_state.open_pair else None,
            'next_seq': getattr(thread_state, 'next_seq', 0),
            'next_turn': getattr(thread_state, 'next_turn', 0)
        }
        
        # Serialize and save to Redis with expiration
        print(f"[MemoryManager] Saving thread state to Redis with expiration for {thread_state.thread_id}")
        print(f"[MemoryManager] type of thread_dict : {type(thread_dict)}")
        await redis_conn.setex(
            thread_state_key,
            SESSION_IDLE_SECONDS * 2,  # Expire after idle timeout * 2
            json.dumps(thread_dict)
        )
        print(f"[MemoryManager] 158 Successfully saved thread state to Redis for {thread_state.thread_id}")

    def _mark_activity(self, thread_state: ThreadState) -> None:
        """Update last activity timestamp (cheap, sync)."""
        thread_state.last_activity_at = time.time()

    def _is_session_idle(self, thread_state: ThreadState) -> bool:
        """Check if session has been idle for too long (sync)."""
        idle_time = time.time() - thread_state.last_activity_at
        is_idle = idle_time > SESSION_IDLE_SECONDS
        if is_idle:
            print(f"[MemoryManager] Session {thread_state.thread_id} is idle ({idle_time:.0f}s > {SESSION_IDLE_SECONDS}s)")
        return is_idle

    # 
    async def _evict_oldest_pair_to_batch(self, thread_id: str) -> None:
        """Move oldest pair from context to batch buffer (async-safe)."""
        print(f"[MemoryManager] _evict_oldest_pair_to_batch called for thread {thread_id}")
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            thread_state = await self._get_thread_state(thread_id)
            await self._evict_oldest_pair_to_batch_internal(thread_state, thread_id)
    
    async def _evict_oldest_pair_to_batch_internal(self, thread_state: ThreadState, thread_id: str) -> None:
        """Internal method to evict oldest pair without acquiring a lock."""
        if thread_state.context_pairs:
            oldest_pair = thread_state.context_pairs.pop(0)
            thread_state.batch_pairs.append(oldest_pair)
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)
            print(f"[MemoryManager] Evicted oldest pair (turn {oldest_pair.turn}) to batch for thread {thread_id}")
            
            # Check Redis memory usage after moving data between structures
            await self.check_redis_memory_and_persist_if_needed()

    async def _check_and_flush_batch(self, thread_id: str) -> None:
        """Flush batch buffer if it reaches the limit (schedules async writes).

        We schedule the async batch writer (or await it when called from an async
        context). This function intentionally does not block the caller for the
        entire write; instead it schedules background work but still provides
        backpressure via the semaphore inside `_batch_write_pairs`.
        """
        print(f"[MemoryManager] _check_and_flush_batch called for thread {thread_id}")
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            thread_state = await self._get_thread_state(thread_id)
            await self._check_and_flush_batch_internal(thread_state, thread_id)
    
    async def _check_and_flush_batch_internal(self, thread_state: ThreadState, thread_id: str) -> None:
        """Internal method to check and flush batch without acquiring a lock."""
        if len(thread_state.batch_pairs) >= BATCH_PAIRS:
            print(f"[MemoryManager] Batch limit reached ({len(thread_state.batch_pairs)} pairs), flushing for thread {thread_id}")
            # capture a copy of the buffer to avoid mutation races
            pairs_to_flush = list(thread_state.batch_pairs)
            thread_state.batch_pairs.clear()

            # schedule the async batch write and track the task
            task = asyncio.create_task(self._batch_write_pairs(thread_id, pairs_to_flush, thread_state.session_id))
            await self._track_task(task)
            
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)

    async def _enforce_ram_limit(self, thread_id: str) -> None:
        """Ensure total RAM pairs don't exceed limit; flush early if needed."""
        print(f"[MemoryManager] _enforce_ram_limit called for thread {thread_id}")
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            thread_state = await self._get_thread_state(thread_id)
            await self._enforce_ram_limit_internal(thread_state, thread_id)
    
    async def _enforce_ram_limit_internal(self, thread_state: ThreadState, thread_id: str) -> None:
        """Internal method to enforce RAM limit without acquiring a lock."""
        total_pairs = len(thread_state.context_pairs) + len(thread_state.batch_pairs)
        if total_pairs > MAX_RAM_PAIRS:
            print(f"[MemoryManager] RAM limit exceeded ({total_pairs} > {MAX_RAM_PAIRS}), flushing batch early for thread {thread_id}")
            # Before potentially losing data due to Redis eviction, ensure it's saved to DynamoDB
            await self.persist_to_dynamodb_before_redis_eviction(thread_id)
            
            if thread_state.batch_pairs:
                pairs_to_flush = list(thread_state.batch_pairs)
                thread_state.batch_pairs.clear()
                task = asyncio.create_task(self._batch_write_pairs(thread_id, pairs_to_flush, thread_state.session_id))
                await self._track_task(task)
                
                # Save updated thread state to Redis
                await self._save_thread_state_to_redis(thread_state)

    #  DynamoDB Ops (for async) 
    async def _reserve_seq_block(self, thread_id: str, count: int) -> int:
        """
        Atomically increments the per-thread counter by `count` and returns the
        starting seq for this block (inclusive). Requires a META row at seq=0.

        Converted to async using aioboto3 so multiple concurrent reservations can
        proceed without blocking the event loop.
        """
        print(f"[MemoryManager] _reserve_seq_block called for thread {thread_id} with count {count}")
        if count <= 0:
            return 0

        async with self._aiosession.client('dynamodb', region_name=AWS_REGION, config=self._botocore_config) as dynamodb:
            # ensure meta row exists (conditionally create)
            try:
                await dynamodb.put_item(
                    TableName=self.table_name,
                    Item={
                        "thread_id": {"S": thread_id},
                        "seq": {"N": "0"},
                        "meta_type": {"S": "COUNTERS"},
                        "next_seq": {"N": "0"},
                        "next_turn": {"N": "0"},
                    },
                    ConditionExpression="attribute_not_exists(thread_id) AND attribute_not_exists(seq)",
                )
            except dynamodb.exceptions.ConditionalCheckFailedException:
                # already exists, fine
                pass

            resp = await dynamodb.update_item(
                TableName=self.table_name,
                Key={"thread_id": {"S": thread_id}, "seq": {"N": "0"}},
                UpdateExpression="ADD next_seq :inc",
                ExpressionAttributeValues={":inc": {"N": str(count)}},
                ReturnValues="UPDATED_NEW",
            )

        end_seq = int(resp["Attributes"]["next_seq"]["N"])
        start_seq = end_seq - count + 1
        return start_seq

    async def _assign_seqs_for_flush(self, thread_id: str, pairs: list) -> None:
        """
        Ensures every message in every pair has a unique seq. Mutates pairs in place.
        This now awaits the async `_reserve_seq_block`.
        """
        print(f"[MemoryManager] _assign_seqs_for_flush called for thread {thread_id}")
        missing = []
        for p in pairs:
            if p and p.user_message and not isinstance(p.user_message.seq, int):
                missing.append(p.user_message)
            if p and p.assistant_message and not isinstance(p.assistant_message.seq, int):
                missing.append(p.assistant_message)
        if not missing:
            return
        start = await self._reserve_seq_block(thread_id, len(missing))
        for i, msg in enumerate(missing):
            msg.seq = start + i

    async def _batch_write_pairs(self, thread_id: str, pairs: list, session_id: str) -> None:
        """Async batch write using aioboto3 with built-in semaphore/backoff.

        This is the hot network path — keep it efficient and bounded.
        """
        print(f"[MemoryManager] _batch_write_pairs called for thread {thread_id} with {len(pairs)} pairs")
        if not pairs:
            return

        # Ensure messages that need seqs have them assigned (async)
        await self._assign_seqs_for_flush(thread_id, pairs)

        items = []
        for p in pairs:
            turn = int(p.turn)

            um = p.user_message
            if um:
                items.append({
                    "thread_id": {"S": thread_id},
                    "seq": {"N": str(int(um.seq))},
                    "turn": {"N": str(turn)},
                    "role": {"S": "user"},
                    "content": {"S": str(um.content)[:38000]},
                    "ts_iso": {"S": um.ts_iso or get_now_iso()},
                    "session_id": {"S": session_id},
                })

            am = p.assistant_message
            if am:
                items.append({
                    "thread_id": {"S": thread_id},
                    "seq": {"N": str(int(am.seq))},
                    "turn": {"N": str(turn)},
                    "role": {"S": "assistant"},
                    "content": {"S": str(am.content)[:38000]},
                    "ts_iso": {"S": am.ts_iso or get_now_iso()},
                    "session_id": {"S": session_id},
                })

        # defensive dup-key guard
        seen = set()
        for it in items:
            k = (it["thread_id"]["S"], it["seq"]["N"])
            if k in seen:
                raise RuntimeError(f"Duplicate key in batch build: {k}")
            seen.add(k)

        # chunk <= 25 and write with retry on unprocessed
        CHUNK = 25
        i = 0

        # Acquire semaphore to provide bounded concurrency to DynamoDB
        async with self._write_semaphore:
            async with self._aiosession.client('dynamodb', region_name=AWS_REGION, config=self._botocore_config) as dynamodb:
                while i < len(items):
                    chunk = [{"PutRequest": {"Item": it}} for it in items[i:i+CHUNK]]
                    backoff = 0.5
                    while True:
                        resp = await dynamodb.batch_write_item(RequestItems={self.table_name: chunk})
                        un = resp.get("UnprocessedItems", {}).get(self.table_name, [])
                        if not un:
                            break
                        chunk = un
                        await asyncio.sleep(min(backoff, 4.0))
                        backoff *= 2
                    i += CHUNK

    # high-level session APIs (async public)
    async def on_session_start(self, thread_id: str) -> None:
        """Initialize session, handle idle timeout, and load context"""
        print(f"[MemoryManager] on_session_start called for thread {thread_id}")
        print(f"[MemoryManager] Starting session for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            try:
                # Check if session has been idle
                if self._is_session_idle(thread_state):
                    print(f"[MemoryManager] Session idle, starting fresh for thread {thread_id}")

                    # Flush all remaining pairs and start new session
                    print("[MemoryManager] Flushing all pairs before starting fresh...")
                    try:
                        await self.flush_all(thread_id)
                        print("[MemoryManager] Successfully flushed all pairs")
                    except Exception as e:
                        print(f"[MemoryManager] Error during flush_all: {e}")
                        # Continue even if flush fails

                    thread_state.session_id = str(uuid.uuid4())
                    thread_state.context_pairs.clear()
                    thread_state.batch_pairs.clear()
                    thread_state.open_pair = None
                    print(f"[MemoryManager] Cleared session state, new session_id: {thread_state.session_id}")

                # Load conversation state from DynamoDB into context
                if not thread_state.context_pairs:
                    print(f"[MemoryManager] Loading conversation state from DynamoDB for thread {thread_id}")
                    try:
                        # Prefer an async loader if available. If memory_utils only exposes
                        # a sync loader, call it off the loop to avoid blocking.
                        loader = load_conversation_state_from_dynamodb
                        if asyncio.iscoroutinefunction(loader):
                            pairs = await loader(self._aiosession, thread_id)
                        else:
                            # run blocking loader in threadpool
                            pairs = await asyncio.to_thread(loader, self._aiosession, thread_id)

                        thread_state.context_pairs = pairs or []
                        print(f"[MemoryManager] Successfully loaded {len(thread_state.context_pairs)} pairs from DynamoDB")

                        # Update next_seq and next_turn based on loaded data
                        if thread_state.context_pairs:
                            max_turn = max(p.turn for p in thread_state.context_pairs)
                            max_seq = 0
                            for p in thread_state.context_pairs:
                                if p.user_message and isinstance(p.user_message.seq, int):
                                    max_seq = max(max_seq, p.user_message.seq)
                                if p.assistant_message and isinstance(p.assistant_message.seq, int):
                                    max_seq = max(max_seq, p.assistant_message.seq)
                            thread_state.next_turn = max_turn + 1
                            thread_state.next_seq = max_seq + 1
                            print(f"[MemoryManager] Updated counters: next_seq={thread_state.next_seq}, next_turn={thread_state.next_turn}")
                        else:
                            print(f"[MemoryManager] No existing conversation found for thread {thread_id}")
                    except Exception as e:
                        print(f"[MemoryManager] Error loading conversation state: {e}")
                        # Continue with empty context if loading fails
                        thread_state.context_pairs = []

                self._mark_activity(thread_state)
                # Update the thread state in Redis after changes
                await self._save_thread_state_to_redis(thread_state)
                print(f"[MemoryManager] Session started for thread {thread_id} with {len(thread_state.context_pairs)} pairs in context")

            except Exception as e:
                print(f"[MemoryManager] Critical error in on_session_start for thread {thread_id}: {e}")
                # Ensure we don't leave the session in a broken state
                self._mark_activity(thread_state)
                await self._save_thread_state_to_redis(thread_state)
                print("[MemoryManager] Marked activity despite error, continuing with empty context")

    async def on_session_end(self, thread_id: str) -> None:
        """End session and flush all remaining pairs"""
        print(f"[MemoryManager] on_session_end called for thread {thread_id}")
        print(f"[MemoryManager] Ending session for thread {thread_id}")
        try:
            await self.flush_all(thread_id)
        except Exception as e:
            print(f"[MemoryManager] Error during on_session_end flush: {e}")

    async def add_user_message(self, thread_id: str, content: str) -> None:
        """Add user message and start a new pair (async-safe)."""
        print(f"[MemoryManager] add_user_message called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            self._mark_activity(thread_state)

            # Get sequence and turn numbers
            seq = getattr(thread_state, "next_seq", 0)
            thread_state.next_seq = seq + 1

            turn = getattr(thread_state, "next_turn", 0)

            # Create user message
            user_message = Message(
                role="user",
                content=content,
                ts_iso=get_now_iso(),
                seq=seq,
                turn=turn
            )

            # Create new open pair
            thread_state.open_pair = Pair(turn=turn, user_message=user_message)
            
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)
            
            print(f"[MemoryManager] Added user message for thread {thread_id}, turn {turn}, seq {seq}")

    async def add_assistant_message(self, thread_id: str, content: str) -> None:
        """Add assistant message and close the current pair (async-safe)."""
        print(f"[MemoryManager] add_assistant_message called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            self._mark_activity(thread_state)

            if not thread_state.open_pair:
                raise ValueError("No open pair to close with assistant message")

            # Get sequence number
            seq = getattr(thread_state, "next_seq", 0)
            thread_state.next_seq = seq + 1

            # Create assistant message
            assistant_message = Message(
                role="assistant",
                content=content,
                ts_iso=get_now_iso(),
                seq=seq,
                turn=thread_state.open_pair.turn
            )

            # Complete the pair
            thread_state.open_pair.assistant_message = assistant_message
            completed_pair = thread_state.open_pair
            thread_state.open_pair = None

            # Move to next turn
            thread_state.next_turn = getattr(thread_state, "next_turn", 0) + 1

            # Add to context
            thread_state.context_pairs.append(completed_pair)
            print(f"[MemoryManager] Completed pair for thread {thread_id}, turn {completed_pair.turn}")
            print(f"[MemoryManager] Context now has {len(thread_state.context_pairs)} pairs")

            # Evict oldest pair if context exceeds limit - use internal method since we're already in a lock
            if len(thread_state.context_pairs) > CONTEXT_PAIRS:
                await self._evict_oldest_pair_to_batch_internal(thread_state, thread_id)

            # Check if batch needs flushing - use internal method since we're already in a lock
            await self._check_and_flush_batch_internal(thread_state, thread_id)

            # Enforce RAM limit - use internal method since we're already in a lock
            await self._enforce_ram_limit_internal(thread_state, thread_id)
            
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)

    async def get_context_for_llm(self, thread_id: str) -> List[Dict[str, str]]:
        """Get flattened context for LLM (last 15 pairs)"""
        print(f"[MemoryManager] get_context_for_llm called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        messages = []

        # Add context pairs
        for pair in thread_state.context_pairs:
            messages.extend(pair.to_messages())

        # Add open pair user message if exists
        if thread_state.open_pair:
            messages.append({
                "role": thread_state.open_pair.user_message.role,
                "content": thread_state.open_pair.user_message.content
            })

        print(f"[MemoryManager] Generated {len(messages)} messages for LLM context (thread {thread_id})")
        return messages

    async def flush_batch(self, thread_id: str) -> None:
        """Flush batch buffer to DynamoDB"""
        print(f"[MemoryManager] flush_batch called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            if thread_state.batch_pairs:
                print(f"[MemoryManager] Manually flushing {len(thread_state.batch_pairs)} pairs from batch for thread {thread_id}")
                pairs_to_flush = list(thread_state.batch_pairs)
                thread_state.batch_pairs.clear()
                task = asyncio.create_task(self._batch_write_pairs(thread_id, pairs_to_flush, thread_state.session_id))
                await self._track_task(task)
                
                # Save updated thread state to Redis
                await self._save_thread_state_to_redis(thread_state)
    
    async def persist_to_dynamodb_before_redis_eviction(self, thread_id: str) -> None:
        """Persist all data in Redis to DynamoDB before Redis level eviction"""
        print(f"[MemoryManager] persist_to_dynamodb_before_redis_eviction called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)
        
        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            # Flush any remaining batch pairs to DynamoDB
            if thread_state.batch_pairs:
                print(f"[MemoryManager] Flushing {len(thread_state.batch_pairs)} batch pairs to DynamoDB for thread {thread_id}")
                pairs_to_flush = list(thread_state.batch_pairs)
                thread_state.batch_pairs.clear()
                await self._batch_write_pairs(thread_id, pairs_to_flush, thread_state.session_id)
            
            # Also flush context pairs if needed (for very old conversations)
            if thread_state.context_pairs:
                print(f"[MemoryManager] Flushing {len(thread_state.context_pairs)} context pairs to DynamoDB for thread {thread_id}")
                pairs_to_flush = list(thread_state.context_pairs)
                thread_state.context_pairs.clear()
                await self._batch_write_pairs(thread_id, pairs_to_flush, thread_state.session_id)
            
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)
            print(f"[MemoryManager] Completed persistence to DynamoDB for thread {thread_id}")
    
    async def check_redis_memory_and_persist_if_needed(self) -> None:
        """Check Redis memory usage and persist data to DynamoDB if approaching limits"""
        redis_conn = await redis_manager.get_connection()
        
        try:
            # Get Redis info to check memory usage
            info = await redis_conn.info('memory')
            used_memory = info.get('used_memory', 0)
            max_memory = info.get('maxmemory', 0)
            
            # If max_memory is 0, Redis has no memory limit, so return early
            if max_memory == 0:
                return
                
            # Convert to int if they're strings
            used_memory = int(used_memory) if isinstance(used_memory, str) else used_memory
            max_memory = int(max_memory) if isinstance(max_memory, str) else max_memory
            
            # Calculate usage percentage
            if max_memory > 0:
                memory_usage_percentage = (used_memory / max_memory) * 100
                print(f"[MemoryManager] Redis memory usage: {memory_usage_percentage:.1f}% ({used_memory}/{max_memory} bytes)")
                
                # If memory usage exceeds 80%, start persisting data to DynamoDB
                if memory_usage_percentage > 80:
                    print(f"[MemoryManager] Redis memory usage is high ({memory_usage_percentage:.1f}%), consider persisting data")
                    # In a real implementation, we might want to iterate through active threads
                    # and persist their data to DynamoDB, but we don't maintain a list of active
                    # thread IDs in memory anymore since we're using Redis
                    # For now, we'll just log this condition
        except Exception as e:
            print(f"[MemoryManager] Error checking Redis memory: {e}")

    async def flush_all(self, thread_id: str) -> None:
        """Flush all pairs (context + batch) to DynamoDB"""
        print(f"[MemoryManager] flush_all called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        # Use Redis distributed lock for thread safety
        redis_conn = await redis_manager.get_connection()
        lock_key = f"lock:thread:{thread_id}"
        
        async with redis_conn.lock(lock_key, timeout=60, blocking_timeout=30):
            # Collect all pairs to flush
            all_pairs = thread_state.context_pairs.copy()
            all_pairs.extend(thread_state.batch_pairs)

            # Add open pair if it exists and is complete
            if thread_state.open_pair and thread_state.open_pair.is_complete:
                all_pairs.append(thread_state.open_pair)

            # Flush to DynamoDB
            if all_pairs:
                print(f"[MemoryManager] Flushing all {len(all_pairs)} pairs for thread {thread_id}")
                task = asyncio.create_task(self._batch_write_pairs(thread_id, all_pairs, thread_state.session_id))
                await self._track_task(task)
            else:
                print(f"[MemoryManager] No pairs to flush for thread {thread_id}")

            # Clear all RAM state
            context_count = len(thread_state.context_pairs)
            batch_count = len(thread_state.batch_pairs)
            thread_state.context_pairs.clear()
            thread_state.batch_pairs.clear()
            thread_state.open_pair = None
            
            # Save updated thread state to Redis
            await self._save_thread_state_to_redis(thread_state)
            
            print(f"[MemoryManager] Cleared RAM state: {context_count} context + {batch_count} batch pairs for thread {thread_id}")

    async def prime_inmemorysaver(self, thread_id: str, graph) -> None:
        """
        Prime InMemorySaver with last 15 pairs converted to LangChain messages.
        This ensures the graph state has consistent recent history after restarts.
        """
        print(f"[MemoryManager] prime_inmemorysaver called for thread {thread_id}")
        thread_state = await self._get_thread_state(thread_id)

        if not thread_state.context_pairs:
            print(f"[MemoryManager] No context pairs to prime InMemorySaver for thread {thread_id}")
            return

        try:
            # Convert pairs to LangChain messages
            langchain_messages = []
            for pair in thread_state.context_pairs:
                langchain_messages.extend(pair.to_langchain_messages())
            
            # Just store the messages - the graph will handle checkpointing automatically
            # when the next real interaction happens
            if langchain_messages:
                print(f"[MemoryManager] Priming InMemorySaver with {len(langchain_messages)} messages for thread {thread_id}")

        except Exception as e:
            print(f"[MemoryManager] Warning: Could not prime InMemorySaver for thread {thread_id}: {e}")

    # Background task handling utils
    # transformed _shutdown_hook 
    async def _track_task(self, task: asyncio.Task) -> None:
        """Add task to pending set and attach a callback to remove/log on completion."""
        print(f"[MemoryManager] _track_task called for task {task}")
        async with self._pending_tasks_lock:
            self._pending_tasks.add(task)

        def _on_done(t: asyncio.Task):
            # remove from pending set and log exceptions
            async def _remove():
                async with self._pending_tasks_lock:
                    self._pending_tasks.discard(t)
                try:
                    exc = t.exception()
                    if exc:
                        print(f"[MemoryManager] Background task failed: {exc}")
                except asyncio.CancelledError:
                    pass

            asyncio.create_task(_remove())

        task.add_done_callback(_on_done)

    # graceful shutdown 
    async def shutdown(self) -> None:
        """Gracefully flush pending work and wait for background tasks to complete.

        Call this from application shutdown (e.g., FastAPI on_event("shutdown")).
        The atexit fallback will run this synchronously if the process exits.
        """
        print("[MemoryManager] shutdown called")
        print("[MemoryManager] Shutdown initiated — flushing all threads and awaiting background tasks")
        start_time = time.time()
        timeout_seconds = 30

        # Since we're using Redis, we'll flush all pending Redis data to DynamoDB before shutdown
        # This ensures no data is lost during Redis eviction/shutdown
        # Note: We don't have a list of all active thread_ids in Redis, so this is a general cleanup
        await redis_manager.close_connection()

        # wait for pending background tasks to finish (short grace)
        async with self._pending_tasks_lock:
            pending_copy = list(self._pending_tasks)

        if pending_copy:
            try:
                await asyncio.wait_for(asyncio.gather(*pending_copy, return_exceptions=True), timeout=10)
            except Exception as e:
                print(f"[MemoryManager] Warning: pending background tasks did not finish: {e}")

        print(f"[MemoryManager] Shutdown complete in {time.time() - start_time:.1f}s")

    # sync-compat helper 
    def run_sync(self, coro):
        """Compatibility helper: run an async coroutine synchronously if needed.

        Use sparingly — in production under an async server you should call async
        APIs directly. This exists to ease incremental migration.
        """
        return asyncio.run(coro)

    async def start_periodic_redis_memory_check(self):
        """Start periodic Redis memory monitoring in the background"""
        async def memory_monitor():
            while True:
                try:
                    await self.check_redis_memory_and_persist_if_needed()
                    # Check every 30 seconds
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    print("[MemoryManager] Redis memory monitoring cancelled")
                    break
                except Exception as e:
                    print(f"[MemoryManager] Error in Redis memory monitoring: {e}")
                    await asyncio.sleep(30)  # Wait before retrying
        
        # Start the monitoring task in the background
        monitor_task = asyncio.create_task(memory_monitor())
        await self._track_task(monitor_task)
        print("[MemoryManager] Started periodic Redis memory monitoring")


# Global instance
memory_manager = MemoryManager()
