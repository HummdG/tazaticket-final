"""
Pair-based chat memory manager backed by DynamoDB.
Keeps last 15 pairs in context, batches pairs for DynamoDB writes,
and manages session lifecycle with idle timeouts.
"""

import time
import uuid
import json
from typing import List, Dict, Any, Optional
import boto3
import threading

from .memory_utils import (
    Message, Pair, ThreadState,
    CHAT_HISTORY_TABLE, AWS_REGION, SESSION_IDLE_SECONDS, CONTEXT_PAIRS, BATCH_PAIRS, MAX_RAM_PAIRS,
    get_now_iso, get_next_seq_from_dynamodb, get_next_turn_from_dynamodb,
    read_pairs_from_dynamodb, load_conversation_state_from_dynamodb
)


class MemoryManager:
    """
    Pair-aware chat memory manager with DynamoDB persistence.
    Manages context window, batch buffer, and session lifecycle.
    """
    
    def __init__(self):
        self.dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)
        self.threads: Dict[str, ThreadState] = {}
        self._global_lock = threading.Lock()

        self.table_name = CHAT_HISTORY_TABLE
        
        print(f"[MemoryManager] Initialized with table: {CHAT_HISTORY_TABLE}, region: {AWS_REGION}")
        print(f"[MemoryManager] Config - Context pairs: {CONTEXT_PAIRS}, Batch pairs: {BATCH_PAIRS}, Max RAM pairs: {MAX_RAM_PAIRS}")
        
        # Register shutdown hook to flush all conversations
        import atexit
        atexit.register(self._shutdown_hook)
    
    def _get_thread_state(self, thread_id: str) -> ThreadState:
        """Get or create thread state"""
        with self._global_lock:
            if thread_id not in self.threads:
                print(f"[MemoryManager] Creating new thread state for {thread_id}")
                self.threads[thread_id] = ThreadState(
                    thread_id=thread_id,
                    session_id=str(uuid.uuid4()),
                    last_activity_at=time.time()
                )
            return self.threads[thread_id]
    
    def _mark_activity(self, thread_state: ThreadState) -> None:
        """Update last activity timestamp"""
        thread_state.last_activity_at = time.time()
    
    def _is_session_idle(self, thread_state: ThreadState) -> bool:
        """Check if session has been idle for too long"""
        idle_time = time.time() - thread_state.last_activity_at
        is_idle = idle_time > SESSION_IDLE_SECONDS
        if is_idle:
            print(f"[MemoryManager] Session {thread_state.thread_id} is idle ({idle_time:.0f}s > {SESSION_IDLE_SECONDS}s)")
        return is_idle
    
    def _evict_oldest_pair_to_batch(self, thread_state: ThreadState) -> None:
        """Move oldest pair from context to batch buffer"""
        if thread_state.context_pairs:
            oldest_pair = thread_state.context_pairs.pop(0)
            thread_state.batch_pairs.append(oldest_pair)
            print(f"[MemoryManager] Evicted oldest pair (turn {oldest_pair.turn}) to batch for thread {thread_state.thread_id}")
    
    def _check_and_flush_batch(self, thread_state: ThreadState) -> None:
        """Flush batch buffer if it reaches the limit"""
        if len(thread_state.batch_pairs) >= BATCH_PAIRS:
            print(f"[MemoryManager] Batch limit reached ({len(thread_state.batch_pairs)} pairs), flushing for thread {thread_state.thread_id}")
            self._batch_write_pairs(thread_state.thread_id, thread_state.batch_pairs, thread_state.session_id)
            thread_state.batch_pairs.clear()
            print(f"[MemoryManager] Batch cleared for thread {thread_state.thread_id}")
    
    def _enforce_ram_limit(self, thread_state: ThreadState) -> None:
        """Ensure total RAM pairs don't exceed limit"""
        total_pairs = len(thread_state.context_pairs) + len(thread_state.batch_pairs)
        if total_pairs > MAX_RAM_PAIRS:
            print(f"[MemoryManager] RAM limit exceeded ({total_pairs} > {MAX_RAM_PAIRS}), flushing batch early for thread {thread_state.thread_id}")
            # Flush batch early to stay within limit
            self._batch_write_pairs(thread_state.thread_id, thread_state.batch_pairs, thread_state.session_id)
            thread_state.batch_pairs.clear()
    
    def _reserve_seq_block(self, thread_id: str, count: int) -> int:
        """
        Atomically increments the per-thread counter by `count` and returns the
        starting seq for this block (inclusive). Requires a META row at seq=0.
        """
        if count <= 0:
            return 0
        # ensure meta row exists
        try:
            self.dynamodb.put_item(
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
        except self.dynamodb.exceptions.ConditionalCheckFailedException:
            pass  # already there

        resp = self.dynamodb.update_item(
            TableName=self.table_name,
            Key={"thread_id": {"S": thread_id}, "seq": {"N": "0"}},
            UpdateExpression="ADD next_seq :inc",
            ExpressionAttributeValues={":inc": {"N": str(count)}},
            ReturnValues="UPDATED_NEW",
        )
        end_seq = int(resp["Attributes"]["next_seq"]["N"])
        start_seq = end_seq - count + 1
        return start_seq

    def _assign_seqs_for_flush(self, thread_id: str, pairs: list) -> None:
        """
        Ensures every message in every pair has a unique seq. Mutates pairs in place.
        Expects each pair like: {"turn": int, "user": {...}, "assistant": {...}}
        Each inner dict can have 'seq' (int) already; only missing ones are assigned.
        """
        # gather messages that need seq
        missing = []
        for p in pairs:
            if p and p.user_message and not isinstance(p.user_message.seq, int):
                missing.append(p.user_message)
            if p and p.assistant_message and not isinstance(p.assistant_message.seq, int):
                missing.append(p.assistant_message)
        if not missing:
            return
        start = self._reserve_seq_block(thread_id, len(missing))
        for i, msg in enumerate(missing):
            msg.seq = start + i

    def _batch_write_pairs(self, thread_id: str, pairs: list, session_id: str) -> None:
        if not pairs:
            return

        # ensure any missing seqs get unique values
        self._assign_seqs_for_flush(thread_id, pairs)

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
        while i < len(items):
            chunk = [{"PutRequest": {"Item": it}} for it in items[i:i+CHUNK]]
            backoff = 0.5
            while True:
                resp = self.dynamodb.batch_write_item(RequestItems={self.table_name: chunk})
                un = resp.get("UnprocessedItems", {}).get(self.table_name, [])
                if not un:
                    break
                chunk = un
                time.sleep(min(backoff, 4.0))
                backoff *= 2
            i += CHUNK


    def on_session_start(self, thread_id: str) -> None:
        """Initialize session, handle idle timeout, and load context"""
        print(f"[MemoryManager] Starting session for thread {thread_id}")
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            # Check if session has been idle
            if self._is_session_idle(thread_state):
                print(f"[MemoryManager] Session idle, starting fresh for thread {thread_id}")
                # Flush all remaining pairs and start new session
                self.flush_all(thread_id)
                thread_state.session_id = str(uuid.uuid4())
                thread_state.context_pairs.clear()
                thread_state.batch_pairs.clear()
                thread_state.open_pair = None
            
            # Load conversation state from DynamoDB into context
            if not thread_state.context_pairs:
                print(f"[MemoryManager] Loading conversation state from DynamoDB for thread {thread_id}")
                pairs = load_conversation_state_from_dynamodb(self.dynamodb, thread_id)
                thread_state.context_pairs = pairs
                
                # Update next_seq and next_turn based on loaded data
                if pairs:
                    max_turn = max(p.turn for p in pairs)
                    max_seq = 0
                    for p in pairs:
                        if p.user_message and isinstance(p.user_message.seq, int):
                            max_seq = max(max_seq, p.user_message.seq)
                        if p.assistant_message and isinstance(p.assistant_message.seq, int):
                            max_seq = max(max_seq, p.assistant_message.seq)
                    thread_state.next_turn = max_turn + 1
                    thread_state.next_seq = max_seq + 1
                    print(f"[MemoryManager] Updated counters: next_seq={thread_state.next_seq}, next_turn={thread_state.next_turn}")
                else:
                    print(f"[MemoryManager] No existing conversation found for thread {thread_id}")
            
            self._mark_activity(thread_state)
            print(f"[MemoryManager] Session started for thread {thread_id} with {len(thread_state.context_pairs)} pairs in context")
    
    def on_session_end(self, thread_id: str) -> None:
        """End session and flush all remaining pairs"""
        print(f"[MemoryManager] Ending session for thread {thread_id}")
        self.flush_all(thread_id)
    
    def add_user_message(self, thread_id: str, content: str) -> None:
        """Add user message and start a new pair"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            self._mark_activity(thread_state)
            
            # Get sequence and turn numbers
            seq = thread_state.next_seq
            thread_state.next_seq += 1
            
            turn = thread_state.next_turn
            
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
            print(f"[MemoryManager] Added user message for thread {thread_id}, turn {turn}, seq {seq}")
    
    def add_assistant_message(self, thread_id: str, content: str) -> None:
        """Add assistant message and close the current pair"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            self._mark_activity(thread_state)
            
            if not thread_state.open_pair:
                raise ValueError("No open pair to close with assistant message")
            
            # Get sequence number
            seq = thread_state.next_seq
            thread_state.next_seq += 1
            
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
            thread_state.next_turn += 1
            
            # Add to context
            thread_state.context_pairs.append(completed_pair)
            print(f"[MemoryManager] Completed pair for thread {thread_id}, turn {completed_pair.turn}")
            print(f"[MemoryManager] Context now has {len(thread_state.context_pairs)} pairs")
            
            # Evict oldest pair if context exceeds limit
            if len(thread_state.context_pairs) > CONTEXT_PAIRS:
                self._evict_oldest_pair_to_batch(thread_state)
            
            # Check if batch needs flushing
            self._check_and_flush_batch(thread_state)
            
            # Enforce RAM limit
            self._enforce_ram_limit(thread_state)
    
    def get_context_for_llm(self, thread_id: str) -> List[Dict[str, str]]:
        """Get flattened context for LLM (last 15 pairs)"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
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
    
    def flush_batch(self, thread_id: str) -> None:
        """Flush batch buffer to DynamoDB"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            if thread_state.batch_pairs:
                print(f"[MemoryManager] Manually flushing {len(thread_state.batch_pairs)} pairs from batch for thread {thread_id}")
                self._batch_write_pairs(thread_id, thread_state.batch_pairs, thread_state.session_id)
                thread_state.batch_pairs.clear()
            else:
                print(f"[MemoryManager] No pairs in batch to flush for thread {thread_id}")
    
    def flush_all(self, thread_id: str) -> None:
        """Flush all pairs (context + batch) to DynamoDB"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            # Collect all pairs to flush
            all_pairs = thread_state.context_pairs.copy()
            all_pairs.extend(thread_state.batch_pairs)
            
            # Add open pair if it exists and is complete
            if thread_state.open_pair and thread_state.open_pair.is_complete:
                all_pairs.append(thread_state.open_pair)
            
            # Flush to DynamoDB
            if all_pairs:
                print(f"[MemoryManager] Flushing all {len(all_pairs)} pairs for thread {thread_id}")
                self._batch_write_pairs(thread_id, all_pairs, thread_state.session_id)
            else:
                print(f"[MemoryManager] No pairs to flush for thread {thread_id}")
            
            # Clear all RAM state
            context_count = len(thread_state.context_pairs)
            batch_count = len(thread_state.batch_pairs)
            thread_state.context_pairs.clear()
            thread_state.batch_pairs.clear()
            thread_state.open_pair = None
            print(f"[MemoryManager] Cleared RAM state: {context_count} context + {batch_count} batch pairs for thread {thread_id}")
    
    def prime_inmemorysaver(self, thread_id: str, graph) -> None:
        """
        Prime InMemorySaver with last 15 pairs converted to LangChain messages.
        This ensures the graph state has consistent recent history after restarts.
        
        Note: This is a best-effort operation. If it fails, the system continues to work
        but InMemorySaver won't have the historical context until the first new interaction.
        """
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
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
    
    def _shutdown_hook(self):
        """Save conversations to DynamoDB on shutdown"""
        try:
            start_time = time.time()
            timeout_seconds = 30

            # Snapshot thread ids OUTSIDE any long operation
            with self._global_lock:
                thread_ids = list(self.threads.keys())

            print(f"[MemoryManager] Shutdown: Flushing {len(thread_ids)} active threads")

            # Flush each thread WITHOUT holding the global lock
            for i, thread_id in enumerate(thread_ids, 1):
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    print(f"[MemoryManager] Shutdown timeout reached after {elapsed:.1f}s, stopping flush")
                    break
                try:
                    self.flush_all(thread_id)
                    if i % 10 == 0:  # Log progress every 10 threads
                        print(f"[MemoryManager] Shutdown: Flushed {i}/{len(thread_ids)} threads")
                except Exception as e:
                    print(f"[MemoryManager] Error saving thread {thread_id} during shutdown: {e}")

            print(f"[MemoryManager] Shutdown complete in {time.time() - start_time:.1f}s")

        except Exception as e:
            print(f"[MemoryManager] Critical error during shutdown: {e}")


# Global instance
memory_manager = MemoryManager()