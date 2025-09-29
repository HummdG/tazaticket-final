"""
Test suite for async memory manager implementation with aioboto3
"""
import asyncio
import unittest
from unittest.mock import Mock, AsyncMock, patch
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app.langgraph.memory_manager import MemoryManager
from app.langgraph.memory_utils import Pair, Message, get_now_iso


class TestAsyncMemoryManager(unittest.TestCase):
    """Test cases for async memory manager implementation"""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.memory_manager = MemoryManager()
        # Mock the aioboto3 session
        self.memory_manager.session = Mock()

    def test_init(self):
        """Test that MemoryManager initializes correctly"""
        self.assertIsInstance(self.memory_manager, MemoryManager)
        self.assertIsNotNone(self.memory_manager.session)
        self.assertEqual(self.memory_manager.table_name, os.getenv("CHAT_HISTORY_TABLE"))

    async def test_reserve_seq_block(self):
        """Test _reserve_seq_block async method"""
        # Mock the DynamoDB client
        mock_client = AsyncMock()
        self.memory_manager.session.client.return_value.__aenter__.return_value = mock_client
        
        # Mock the response
        mock_client.update_item.return_value = {
            "Attributes": {"next_seq": {"N": "5"}}
        }
        
        # Test the method
        result = await self.memory_manager._reserve_seq_block("test_thread", 3)
        self.assertEqual(result, 3)  # 5 - 3 + 1 = 3
        
        # Verify the client was called correctly
        self.memory_manager.session.client.assert_called_with('dynamodb', region_name=os.getenv("AWS_REGION"))

    async def test_assign_seqs_for_flush(self):
        """Test _assign_seqs_for_flush async method"""
        # Mock the _reserve_seq_block method
        with patch.object(self.memory_manager, '_reserve_seq_block', new=AsyncMock(return_value=10)):
            # Create test pairs with missing seq numbers
            user_message = Message(
                role="user",
                content="test message",
                ts_iso=get_now_iso(),
                seq=None,  # Missing seq
                turn=1
            )
            pair = Pair(turn=1, user_message=user_message)
            pairs = [pair]
            
            # Test the method
            await self.memory_manager._assign_seqs_for_flush("test_thread", pairs)
            
            # Verify seq was assigned
            self.assertEqual(user_message.seq, 10)

    async def test_batch_write_pairs_empty(self):
        """Test _batch_write_pairs with empty pairs list"""
        result = await self.memory_manager._batch_write_pairs("test_thread", [], "test_session")
        self.assertIsNone(result)  # Should return None

    async def test_check_and_flush_batch_no_flush(self):
        """Test _check_and_flush_batch when batch is not full"""
        from app.langgraph.memory_utils import ThreadState
        import threading
        
        thread_state = ThreadState(
            thread_id="test_thread",
            session_id="test_session",
            last_activity_at=1000.0
        )
        
        # Add fewer pairs than BATCH_PAIRS threshold
        result = await self.memory_manager._check_and_flush_batch(thread_state)
        self.assertIsNone(result)  # Should return None without flushing

    async def test_enforce_ram_limit_no_flush(self):
        """Test _enforce_ram_limit when under limit"""
        from app.langgraph.memory_utils import ThreadState
        import threading
        
        thread_state = ThreadState(
            thread_id="test_thread",
            session_id="test_session",
            last_activity_at=1000.0
        )
        
        # Set limit higher than current pairs
        with patch('app.langgraph.memory_manager.MAX_RAM_PAIRS', 10):
            result = await self.memory_manager._enforce_ram_limit(thread_state)
            self.assertIsNone(result)  # Should return None without flushing

    def test_add_user_message(self):
        """Test add_user_message (synchronous method)"""
        # Test the synchronous method
        self.memory_manager.add_user_message("test_thread", "test message")
        
        # Verify thread state was created
        thread_state = self.memory_manager._get_thread_state("test_thread")
        self.assertIsNotNone(thread_state.open_pair)
        self.assertEqual(thread_state.open_pair.user_message.content, "test message")

    async def test_add_assistant_message(self):
        """Test add_assistant_message async method"""
        # First add a user message
        self.memory_manager.add_user_message("test_thread", "test user message")
        
        # Mock the async helper methods
        with patch.object(self.memory_manager, '_check_and_flush_batch', new=AsyncMock()), \
             patch.object(self.memory_manager, '_enforce_ram_limit', new=AsyncMock()):
            
            # Test adding assistant message
            await self.memory_manager.add_assistant_message("test_thread", "test assistant message")
            
            # Verify pair was completed
            thread_state = self.memory_manager._get_thread_state("test_thread")
            self.assertIsNone(thread_state.open_pair)
            self.assertEqual(len(thread_state.context_pairs), 1)
            self.assertEqual(thread_state.context_pairs[0].assistant_message.content, "test assistant message")

    async def test_flush_batch_empty(self):
        """Test flush_batch with empty batch"""
        # Test flushing an empty batch
        await self.memory_manager.flush_batch("test_thread")
        # Should complete without error

    async def test_flush_all_empty(self):
        """Test flush_all with empty state"""
        # Test flushing with no data
        await self.memory_manager.flush_all("test_thread")
        # Should complete without error

    async def test_on_session_start_idle(self):
        """Test on_session_start with idle session"""
        from app.langgraph.memory_utils import ThreadState
        import threading
        
        # Create an idle thread state
        thread_state = ThreadState(
            thread_id="test_thread",
            session_id="test_session",
            last_activity_at=1000.0  # Far in the past
        )
        
        with patch.object(self.memory_manager, '_get_thread_state', return_value=thread_state), \
             patch.object(self.memory_manager, '_is_session_idle', return_value=True), \
             patch.object(self.memory_manager, 'flush_all', new=AsyncMock()):
            
            # Mock the DynamoDB client for load_conversation_state_from_dynamodb
            mock_client = AsyncMock()
            self.memory_manager.session.client.return_value.__aenter__.return_value = mock_client
            mock_client.get_item.return_value = {'Item': None}
            
            # Test the method
            await self.memory_manager.on_session_start("test_thread")
            
            # Verify flush_all was called
            self.memory_manager.flush_all.assert_called_once_with("test_thread")

    async def test_on_session_end(self):
        """Test on_session_end async method"""
        with patch.object(self.memory_manager, 'flush_all', new=AsyncMock()):
            # Test the method
            await self.memory_manager.on_session_end("test_thread")
            
            # Verify flush_all was called
            self.memory_manager.flush_all.assert_called_once_with("test_thread")


class TestAsyncMemoryUtils(unittest.TestCase):
    """Test cases for async memory utilities"""

    async def test_get_next_seq_from_dynamodb(self):
        """Test get_next_seq_from_dynamodb async function"""
        from app.langgraph.memory_utils import get_next_seq_from_dynamodb
        
        # Mock the DynamoDB client
        mock_client = AsyncMock()
        mock_client.update_item.return_value = {
            'Attributes': {'next_seq': {'N': '5'}}
        }
        
        # Test the function
        result = await get_next_seq_from_dynamodb(mock_client, "test_thread")
        self.assertEqual(result, 5)

    async def test_get_next_turn_from_dynamodb(self):
        """Test get_next_turn_from_dynamodb async function"""
        from app.langgraph.memory_utils import get_next_turn_from_dynamodb
        
        # Mock the DynamoDB client
        mock_client = AsyncMock()
        mock_client.update_item.return_value = {
            'Attributes': {'next_turn': {'N': '3'}}
        }
        
        # Test the function
        result = await get_next_turn_from_dynamodb(mock_client, "test_thread")
        self.assertEqual(result, 3)

    async def test_read_pairs_from_dynamodb(self):
        """Test read_pairs_from_dynamodb async function"""
        from app.langgraph.memory_utils import read_pairs_from_dynamodb
        
        # Mock the DynamoDB client
        mock_client = AsyncMock()
        mock_client.query.return_value = {
            'Items': []
        }
        
        # Test the function
        result = await read_pairs_from_dynamodb(mock_client, "test_thread", 5)
        self.assertIsInstance(result, list)

    async def test_load_conversation_state_from_dynamodb(self):
        """Test load_conversation_state_from_dynamodb async function"""
        from app.langgraph.memory_utils import load_conversation_state_from_dynamodb
        
        # Mock the DynamoDB client
        mock_client = AsyncMock()
        mock_client.get_item.return_value = {
            'Item': None  # No conversation state item
        }
        
        with patch('app.langgraph.memory_utils.read_pairs_from_dynamodb', new=AsyncMock(return_value=[])):
            # Test the function
            result = await load_conversation_state_from_dynamodb(mock_client, "test_thread")
            self.assertIsInstance(result, list)


def run_async_test(coro):
    """Helper function to run async tests"""
    return asyncio.run(coro)


if __name__ == '__main__':
    # Run the tests
    unittest.main()