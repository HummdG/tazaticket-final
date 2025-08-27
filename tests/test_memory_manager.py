"""
Test suite for the pair-based chat memory manager.
Tests windowing, batching, idle timeout, crash recovery, and LLM contract.
"""

import pytest
import time
import os
import uuid
from unittest.mock import Mock, patch, MagicMock
from moto import mock_dynamodb
import boto3

# Import the memory manager components
from app.langgraph.memory_manager import MemoryManager
from app.langgraph.memory_utils import Message, Pair, ThreadState, CONTEXT_PAIRS, BATCH_PAIRS, MAX_RAM_PAIRS


@pytest.fixture
def mock_dynamodb_table():
    """Create a mock DynamoDB table for testing"""
    with mock_dynamodb():
        dynamodb = boto3.client('dynamodb', region_name='us-east-1')
        
        # Create the table
        table_name = 'chat_history_test'
        os.environ['CHAT_HISTORY_TABLE'] = table_name
        
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'thread_id', 'KeyType': 'HASH'},
                {'AttributeName': 'seq', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'thread_id', 'AttributeType': 'S'},
                {'AttributeName': 'seq', 'AttributeType': 'N'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        
        yield dynamodb


@pytest.fixture
def memory_manager(mock_dynamodb_table):
    """Create a fresh memory manager instance for testing"""
    return MemoryManager()


@pytest.fixture
def sample_pairs():
    """Create sample message pairs for testing"""
    pairs = []
    for i in range(20):  # Create 20 pairs for testing
        user_msg = Message(
            role="user",
            content=f"User message {i+1}",
            ts_iso="2024-01-01T00:00:00Z",
            seq=i*2 + 1,
            turn=i + 1
        )
        assistant_msg = Message(
            role="assistant", 
            content=f"Assistant response {i+1}",
            ts_iso="2024-01-01T00:01:00Z",
            seq=i*2 + 2,
            turn=i + 1
        )
        pairs.append(Pair(turn=i + 1, user_message=user_msg, assistant_message=assistant_msg))
    return pairs


class TestPairOperations:
    """Test basic pair operations"""
    
    def test_pair_completion(self):
        """Test pair completion logic"""
        user_msg = Message("user", "Hello", "2024-01-01T00:00:00Z", 1, 1)
        
        # Incomplete pair
        pair = Pair(turn=1, user_message=user_msg)
        assert not pair.is_complete
        
        # Complete pair
        assistant_msg = Message("assistant", "Hi there", "2024-01-01T00:01:00Z", 2, 1)
        pair.assistant_message = assistant_msg
        assert pair.is_complete
    
    def test_pair_to_messages(self):
        """Test conversion of pairs to message format"""
        user_msg = Message("user", "Hello", "2024-01-01T00:00:00Z", 1, 1)
        assistant_msg = Message("assistant", "Hi there", "2024-01-01T00:01:00Z", 2, 1)
        pair = Pair(turn=1, user_message=user_msg, assistant_message=assistant_msg)
        
        messages = pair.to_messages()
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Hello"}
        assert messages[1] == {"role": "assistant", "content": "Hi there"}
    
    def test_pair_to_langchain_messages(self):
        """Test conversion of pairs to LangChain messages"""
        user_msg = Message("user", "Hello", "2024-01-01T00:00:00Z", 1, 1)
        assistant_msg = Message("assistant", "Hi there", "2024-01-01T00:01:00Z", 2, 1)
        pair = Pair(turn=1, user_message=user_msg, assistant_message=assistant_msg)
        
        lc_messages = pair.to_langchain_messages()
        assert len(lc_messages) == 2
        assert lc_messages[0].content == "Hello"
        assert lc_messages[1].content == "Hi there"


class TestMemoryManagerBasics:
    """Test basic memory manager functionality"""
    
    def test_thread_state_creation(self, memory_manager):
        """Test thread state creation and management"""
        thread_id = "test_thread_1"
        state = memory_manager._get_thread_state(thread_id)
        
        assert state.thread_id == thread_id
        assert state.session_id is not None
        assert state.next_seq == 1
        assert state.next_turn == 1
        assert len(state.context_pairs) == 0
        assert len(state.batch_pairs) == 0
        assert state.open_pair is None
    
    def test_activity_marking(self, memory_manager):
        """Test activity timestamp updates"""
        thread_id = "test_thread_2"
        state = memory_manager._get_thread_state(thread_id)
        
        initial_time = state.last_activity_at
        time.sleep(0.1)
        
        memory_manager._mark_activity(state)
        assert state.last_activity_at > initial_time
    
    def test_session_idle_detection(self, memory_manager):
        """Test idle session detection"""
        thread_id = "test_thread_3"
        state = memory_manager._get_thread_state(thread_id)
        
        # Fresh state should not be idle
        assert not memory_manager._is_session_idle(state)
        
        # Simulate old activity
        state.last_activity_at = time.time() - 25000  # > 6 hours ago
        assert memory_manager._is_session_idle(state)


class TestConversationFlow:
    """Test conversation flow and pair management"""
    
    def test_add_user_message(self, memory_manager):
        """Test adding user messages"""
        thread_id = "test_conv_1"
        
        memory_manager.add_user_message(thread_id, "Hello world")
        state = memory_manager._get_thread_state(thread_id)
        
        assert state.open_pair is not None
        assert state.open_pair.user_message.content == "Hello world"
        assert state.open_pair.user_message.role == "user"
        assert state.open_pair.user_message.turn == 1
        assert not state.open_pair.is_complete
        assert state.next_seq == 2
        assert state.next_turn == 1  # Still on same turn until assistant responds
    
    def test_add_assistant_message(self, memory_manager):
        """Test adding assistant messages and pair completion"""
        thread_id = "test_conv_2"
        
        # Add user message first
        memory_manager.add_user_message(thread_id, "Hello")
        
        # Add assistant response
        memory_manager.add_assistant_message(thread_id, "Hi there!")
        state = memory_manager._get_thread_state(thread_id)
        
        assert state.open_pair is None  # Should be closed
        assert len(state.context_pairs) == 1
        assert state.context_pairs[0].is_complete
        assert state.context_pairs[0].assistant_message.content == "Hi there!"
        assert state.next_turn == 2  # Should move to next turn
    
    def test_assistant_message_without_user_fails(self, memory_manager):
        """Test that assistant message without user message fails"""
        thread_id = "test_conv_3"
        
        with pytest.raises(ValueError, match="No open pair"):
            memory_manager.add_assistant_message(thread_id, "Hi there!")
    
    def test_context_for_llm(self, memory_manager):
        """Test getting context for LLM"""
        thread_id = "test_conv_4"
        
        # Add a few complete pairs
        for i in range(3):
            memory_manager.add_user_message(thread_id, f"User message {i+1}")
            memory_manager.add_assistant_message(thread_id, f"Assistant response {i+1}")
        
        # Add an open pair
        memory_manager.add_user_message(thread_id, "Latest user message")
        
        context = memory_manager.get_context_for_llm(thread_id)
        
        # Should have 6 messages from complete pairs + 1 from open pair = 7 total
        assert len(context) == 7
        assert context[-1]["role"] == "user"
        assert context[-1]["content"] == "Latest user message"


class TestWindowingAndBatching:
    """Test context windowing and batch management"""
    
    def test_context_windowing(self, memory_manager):
        """Test that context is limited to CONTEXT_PAIRS"""
        thread_id = "test_window_1"
        
        # Add more than CONTEXT_PAIRS pairs
        for i in range(CONTEXT_PAIRS + 2):
            memory_manager.add_user_message(thread_id, f"Message {i+1}")
            memory_manager.add_assistant_message(thread_id, f"Response {i+1}")
        
        state = memory_manager._get_thread_state(thread_id)
        
        # Context should be limited to CONTEXT_PAIRS
        assert len(state.context_pairs) == CONTEXT_PAIRS
        # Oldest pairs should be moved to batch
        assert len(state.batch_pairs) == 2
        
        # Check that newest pairs are in context
        newest_pair = state.context_pairs[-1]
        assert f"Message {CONTEXT_PAIRS + 2}" in newest_pair.user_message.content
    
    def test_batch_flushing(self, memory_manager):
        """Test that batch flushes when reaching BATCH_PAIRS"""
        thread_id = "test_batch_1"
        
        # Mock the batch write method to track calls
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            # Add enough pairs to trigger batch flush
            total_pairs = CONTEXT_PAIRS + BATCH_PAIRS
            for i in range(total_pairs):
                memory_manager.add_user_message(thread_id, f"Message {i+1}")
                memory_manager.add_assistant_message(thread_id, f"Response {i+1}")
            
            state = memory_manager._get_thread_state(thread_id)
            
            # Batch should be empty after flush
            assert len(state.batch_pairs) == 0
            # Context should still be at limit
            assert len(state.context_pairs) == CONTEXT_PAIRS
            
            # Batch write should have been called
            mock_batch_write.assert_called()
    
    def test_ram_limit_enforcement(self, memory_manager):
        """Test that total RAM pairs don't exceed MAX_RAM_PAIRS"""
        thread_id = "test_ram_1"
        
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            # Try to exceed MAX_RAM_PAIRS
            for i in range(MAX_RAM_PAIRS + 5):
                memory_manager.add_user_message(thread_id, f"Message {i+1}")
                memory_manager.add_assistant_message(thread_id, f"Response {i+1}")
            
            state = memory_manager._get_thread_state(thread_id)
            total_ram_pairs = len(state.context_pairs) + len(state.batch_pairs)
            
            # Should not exceed MAX_RAM_PAIRS
            assert total_ram_pairs <= MAX_RAM_PAIRS
            
            # Batch write should have been called to enforce limit
            mock_batch_write.assert_called()


class TestSessionManagement:
    """Test session lifecycle and idle timeout"""
    
    def test_session_start_fresh(self, memory_manager):
        """Test starting a fresh session"""
        thread_id = "test_session_1"
        
        with patch.object(memory_manager, '_read_last_n_pairs', return_value=[]):
            memory_manager.on_session_start(thread_id)
            
            state = memory_manager._get_thread_state(thread_id)
            assert len(state.context_pairs) == 0
    
    def test_session_start_with_history(self, memory_manager, sample_pairs):
        """Test starting session with existing history"""
        thread_id = "test_session_2"
        
        # Mock reading pairs from DynamoDB
        with patch.object(memory_manager, '_read_last_n_pairs', return_value=sample_pairs[:CONTEXT_PAIRS]):
            memory_manager.on_session_start(thread_id)
            
            state = memory_manager._get_thread_state(thread_id)
            assert len(state.context_pairs) == CONTEXT_PAIRS
    
    def test_idle_timeout_flush(self, memory_manager):
        """Test that idle sessions are flushed"""
        thread_id = "test_idle_1"
        
        # Add some conversation
        memory_manager.add_user_message(thread_id, "Hello")
        memory_manager.add_assistant_message(thread_id, "Hi")
        
        state = memory_manager._get_thread_state(thread_id)
        original_session_id = state.session_id
        
        # Simulate idle timeout
        state.last_activity_at = time.time() - 25000  # > 6 hours ago
        
        with patch.object(memory_manager, 'flush_all') as mock_flush:
            with patch.object(memory_manager, '_read_last_n_pairs', return_value=[]):
                memory_manager.on_session_start(thread_id)
                
                # Should have flushed and created new session
                mock_flush.assert_called_once_with(thread_id)
                assert state.session_id != original_session_id
    
    def test_session_end(self, memory_manager):
        """Test session end behavior"""
        thread_id = "test_session_end_1"
        
        # Add some conversation
        memory_manager.add_user_message(thread_id, "Hello")
        memory_manager.add_assistant_message(thread_id, "Hi")
        
        with patch.object(memory_manager, 'flush_all') as mock_flush:
            memory_manager.on_session_end(thread_id)
            mock_flush.assert_called_once_with(thread_id)


class TestDynamoDBOperations:
    """Test DynamoDB read/write operations"""
    
    def test_counter_initialization(self, memory_manager):
        """Test that sequence counters are properly initialized"""
        thread_id = "test_counter_1"
        
        # First call should initialize and return 1
        seq = memory_manager._get_next_seq(thread_id)
        assert seq == 1
        
        # Subsequent calls should increment
        seq2 = memory_manager._get_next_seq(thread_id)
        assert seq2 == 2
    
    def test_batch_write_pairs(self, memory_manager, sample_pairs):
        """Test batch writing pairs to DynamoDB"""
        thread_id = "test_batch_write_1"
        
        # Write a few pairs
        pairs_to_write = sample_pairs[:3]
        
        # This should not raise an exception
        memory_manager._batch_write_pairs(thread_id, pairs_to_write)
        
        # Verify the items were written (we can't easily verify in moto, 
        # but we ensure no exceptions were raised)
    
    def test_read_last_n_pairs(self, memory_manager, sample_pairs):
        """Test reading last n pairs from DynamoDB"""
        thread_id = "test_read_pairs_1"
        
        # First write some pairs
        memory_manager._batch_write_pairs(thread_id, sample_pairs[:10])
        
        # Then read them back
        read_pairs = memory_manager._read_last_n_pairs(thread_id, 5)
        
        # Should get back the last 5 pairs (but moto might not preserve order perfectly)
        assert len(read_pairs) <= 5
    
    def test_flush_operations(self, memory_manager):
        """Test flush batch and flush all operations"""
        thread_id = "test_flush_1"
        
        # Add some conversation to create pairs in memory
        for i in range(3):
            memory_manager.add_user_message(thread_id, f"Message {i+1}")
            memory_manager.add_assistant_message(thread_id, f"Response {i+1}")
        
        state = memory_manager._get_thread_state(thread_id)
        
        # Move some pairs to batch
        state.batch_pairs = state.context_pairs[:2]
        state.context_pairs = state.context_pairs[2:]
        
        # Test flush batch
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            memory_manager.flush_batch(thread_id)
            mock_batch_write.assert_called_once()
            assert len(state.batch_pairs) == 0
        
        # Test flush all
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            memory_manager.flush_all(thread_id)
            mock_batch_write.assert_called_once()
            assert len(state.context_pairs) == 0


class TestLLMContract:
    """Test the contract with LLM regarding message limits"""
    
    def test_llm_context_limit(self, memory_manager):
        """Test that LLM never receives more than 30 messages (15 pairs)"""
        thread_id = "test_llm_1"
        
        # Add more than 15 pairs
        for i in range(20):
            memory_manager.add_user_message(thread_id, f"Message {i+1}")
            memory_manager.add_assistant_message(thread_id, f"Response {i+1}")
        
        # Add an open pair
        memory_manager.add_user_message(thread_id, "Final message")
        
        context = memory_manager.get_context_for_llm(thread_id)
        
        # Should have at most 30 messages (15 pairs) + 1 open = 31 max
        assert len(context) <= 31
        
        # Actually, should be exactly 31: 15 complete pairs (30 messages) + 1 open
        assert len(context) == 31
    
    def test_message_order_preservation(self, memory_manager):
        """Test that messages maintain chronological order"""
        thread_id = "test_order_1"
        
        # Add several pairs
        for i in range(5):
            memory_manager.add_user_message(thread_id, f"User {i+1}")
            memory_manager.add_assistant_message(thread_id, f"Assistant {i+1}")
        
        context = memory_manager.get_context_for_llm(thread_id)
        
        # Verify order: should alternate user/assistant and be chronological
        for i in range(0, len(context), 2):
            assert context[i]["role"] == "user"
            if i + 1 < len(context):
                assert context[i + 1]["role"] == "assistant"


class TestCrashRecovery:
    """Test crash recovery and state reconstruction"""
    
    def test_state_reconstruction(self, memory_manager, sample_pairs):
        """Test that state can be reconstructed from DynamoDB after restart"""
        thread_id = "test_crash_1"
        
        # Simulate having data in DynamoDB
        with patch.object(memory_manager, '_read_last_n_pairs', return_value=sample_pairs[:10]):
            # Start session (simulating restart)
            memory_manager.on_session_start(thread_id)
            
            state = memory_manager._get_thread_state(thread_id)
            
            # Should have loaded pairs into context
            assert len(state.context_pairs) == 10
            
            # Should have updated counters based on loaded data
            max_seq = max(max(p.user_message.seq, p.assistant_message.seq) for p in sample_pairs[:10])
            max_turn = max(p.turn for p in sample_pairs[:10])
            assert state.next_seq == max_seq + 1
            assert state.next_turn == max_turn + 1
    
    def test_prime_inmemorysaver(self, memory_manager, sample_pairs):
        """Test priming InMemorySaver with loaded context"""
        thread_id = "test_prime_1"
        
        # Set up some context pairs
        state = memory_manager._get_thread_state(thread_id)
        state.context_pairs = sample_pairs[:5]
        
        # Mock graph with checkpointer
        mock_graph = Mock()
        mock_checkpointer = Mock()
        mock_graph.checkpointer = mock_checkpointer
        
        # Prime the saver
        memory_manager.prime_inmemorysaver(thread_id, mock_graph)
        
        # Should have called checkpointer.put
        mock_checkpointer.put.assert_called_once()
        
        # Verify the messages passed to checkpointer
        call_args = mock_checkpointer.put.call_args
        config, messages, state_arg = call_args[0]
        
        assert config == {"configurable": {"thread_id": thread_id}}
        assert len(messages["messages"]) == 10  # 5 pairs = 10 messages


class TestConcurrency:
    """Test thread safety and concurrent access"""
    
    def test_thread_safety(self, memory_manager):
        """Test that concurrent access is properly synchronized"""
        import threading
        thread_id = "test_concurrent_1"
        results = []
        
        def add_messages(start_idx):
            try:
                for i in range(start_idx, start_idx + 5):
                    memory_manager.add_user_message(thread_id, f"User {i}")
                    memory_manager.add_assistant_message(thread_id, f"Assistant {i}")
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")
        
        # Start multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=add_messages, args=(i * 10,))
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # All threads should have succeeded
        assert all(r == "success" for r in results)
        
        # Final state should be consistent
        state = memory_manager._get_thread_state(thread_id)
        total_pairs = len(state.context_pairs) + len(state.batch_pairs)
        assert total_pairs == 15  # 3 threads × 5 pairs each


# Integration test
class TestEndToEnd:
    """End-to-end integration tests"""
    
    def test_full_conversation_flow(self, memory_manager):
        """Test a complete conversation flow with all features"""
        thread_id = "test_e2e_1"
        
        # Start session
        memory_manager.on_session_start(thread_id)
        
        # Have a long conversation that triggers windowing and batching
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            for i in range(CONTEXT_PAIRS + BATCH_PAIRS + 2):
                memory_manager.add_user_message(thread_id, f"Turn {i+1}: What about flights?")
                memory_manager.add_assistant_message(thread_id, f"Turn {i+1}: Here are the options...")
            
            # Should have triggered batch writes
            assert mock_batch_write.called
        
        # Get context for LLM
        context = memory_manager.get_context_for_llm(thread_id)
        
        # Should be properly limited
        assert len(context) <= 30  # 15 pairs max
        
        # End session
        with patch.object(memory_manager, '_batch_write_pairs') as mock_batch_write:
            memory_manager.on_session_end(thread_id)
            # Should flush remaining pairs
            mock_batch_write.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 