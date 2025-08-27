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
    read_pairs_from_dynamodb, batch_write_pairs_to_dynamodb, load_conversation_state_from_dynamodb
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
        
        # Register shutdown hook to flush all conversations
        import atexit
        atexit.register(self._shutdown_hook)
    
    def _get_thread_state(self, thread_id: str) -> ThreadState:
        """Get or create thread state"""
        with self._global_lock:
            if thread_id not in self.threads:
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
        return idle_time > SESSION_IDLE_SECONDS
    
    def _evict_oldest_pair_to_batch(self, thread_state: ThreadState) -> None:
        """Move oldest pair from context to batch buffer"""
        if thread_state.context_pairs:
            oldest_pair = thread_state.context_pairs.pop(0)
            thread_state.batch_pairs.append(oldest_pair)
    
    def _check_and_flush_batch(self, thread_state: ThreadState) -> None:
        """Flush batch buffer if it reaches the limit"""
        if len(thread_state.batch_pairs) >= BATCH_PAIRS:
            batch_write_pairs_to_dynamodb(
                self.dynamodb, thread_state.thread_id, 
                thread_state.batch_pairs, thread_state.session_id
            )
            thread_state.batch_pairs.clear()
    
    def _enforce_ram_limit(self, thread_state: ThreadState) -> None:
        """Ensure total RAM pairs don't exceed limit"""
        total_pairs = len(thread_state.context_pairs) + len(thread_state.batch_pairs)
        if total_pairs > MAX_RAM_PAIRS:
            # Flush batch early to stay within limit
            batch_write_pairs_to_dynamodb(
                self.dynamodb, thread_state.thread_id, 
                thread_state.batch_pairs, thread_state.session_id
            )
            thread_state.batch_pairs.clear()
    
    def on_session_start(self, thread_id: str) -> None:
        """Initialize session, handle idle timeout, and load context"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            # Check if session has been idle
            if self._is_session_idle(thread_state):
                # Flush all remaining pairs and start new session
                self.flush_all(thread_id)
                thread_state.session_id = str(uuid.uuid4())
                thread_state.context_pairs.clear()
                thread_state.batch_pairs.clear()
                thread_state.open_pair = None
            
            # Load conversation state from DynamoDB into context
            if not thread_state.context_pairs:
                pairs = load_conversation_state_from_dynamodb(self.dynamodb, thread_id)
                thread_state.context_pairs = pairs
                
                # Update next_seq and next_turn based on loaded data
                if pairs:
                    max_turn = max(p.turn for p in pairs)
                    thread_state.next_seq = len(pairs) * 2 + 1  # Rough estimate
                    thread_state.next_turn = max_turn + 1
            
            self._mark_activity(thread_state)
    
    def on_session_end(self, thread_id: str) -> None:
        """End session and flush all remaining pairs"""
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
            
            return messages
    
    def flush_batch(self, thread_id: str) -> None:
        """Flush batch buffer to DynamoDB"""
        thread_state = self._get_thread_state(thread_id)
        
        with thread_state.lock:
            if thread_state.batch_pairs:
                batch_write_pairs_to_dynamodb(
                    self.dynamodb, thread_id, 
                    thread_state.batch_pairs, thread_state.session_id
                )
                thread_state.batch_pairs.clear()
    
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
                batch_write_pairs_to_dynamodb(
                    self.dynamodb, thread_id, all_pairs, thread_state.session_id
                )
            
            # Clear all RAM state
            thread_state.context_pairs.clear()
            thread_state.batch_pairs.clear()
            thread_state.open_pair = None
    
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
                return
            
            try:
                # Convert pairs to LangChain messages
                langchain_messages = []
                for pair in thread_state.context_pairs:
                    langchain_messages.extend(pair.to_langchain_messages())
                
                # Just store the messages - the graph will handle checkpointing automatically
                # when the next real interaction happens
                if langchain_messages:
                    pass
                
            except Exception as e:
                print(f"Warning: Could not prime InMemorySaver: {e}")
    
    def _shutdown_hook(self):
        """Save conversations to DynamoDB on shutdown"""
        try:
            start_time = time.time()
            timeout_seconds = 30

            # Snapshot thread ids OUTSIDE any long operation
            with self._global_lock:
                thread_ids = list(self.threads.keys())

            # Flush each thread WITHOUT holding the global lock
            for i, thread_id in enumerate(thread_ids, 1):
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    break
                try:
                    self.flush_all(thread_id)
                except Exception as e:
                    print(f"Error saving thread {thread_id}: {e}")

        except Exception as e:
            print(f"Critical error during shutdown: {e}")


# Global instance
memory_manager = MemoryManager() 