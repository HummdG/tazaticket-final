"""
Test suite for async memory manager implementation
"""
import pytest
import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

class TestAsyncMemoryManager:
    """Test cases for async memory manager implementation"""

    @pytest.fixture(autouse=True)
    def setup_memory_manager(self):
        """Set up memory manager for testing"""
        # Import after path modification
        from app.langgraph.memory_manager import MemoryManager
        self.memory_manager = MemoryManager()
        # Mock the aioboto3 session
        self.memory_manager.session = AsyncMock()
        yield
        # Cleanup if needed

    def test_imports_work(self):
        """Test that we can import the memory manager"""
        from app.langgraph.memory_manager import MemoryManager
        assert MemoryManager is not None

    def test_memory_manager_initialization(self):
        """Test that MemoryManager initializes correctly"""
        from app.langgraph.memory_manager import MemoryManager
        mm = MemoryManager()
        assert mm is not None
        assert hasattr(mm, 'session')

    @pytest.mark.asyncio
    async def test_async_method_signatures(self):
        """Test that async methods are properly defined"""
        import inspect
        
        # List of methods that should be async
        async_methods = [
            '_reserve_seq_block',
            '_assign_seqs_for_flush',
            '_batch_write_pairs',
            '_check_and_flush_batch',
            '_enforce_ram_limit',
            'flush_batch',
            'flush_all',
            'add_assistant_message',
            'on_session_start',
            'on_session_end',
        ]
        
        for method_name in async_methods:
            method = getattr(self.memory_manager, method_name)
            assert inspect.iscoroutinefunction(method), f"{method_name} should be async"

    @pytest.mark.asyncio
    async def test_utility_function_signatures(self):
        """Test that utility functions are properly defined as async"""
        import inspect
        from app.langgraph.memory_utils import (
            get_next_seq_from_dynamodb,
            get_next_turn_from_dynamodb,
            read_pairs_from_dynamodb,
            load_conversation_state_from_dynamodb
        )
        
        async_functions = [
            get_next_seq_from_dynamodb,
            get_next_turn_from_dynamodb,
            read_pairs_from_dynamodb,
            load_conversation_state_from_dynamodb,
        ]
        
        for func in async_functions:
            assert inspect.iscoroutinefunction(func), f"{func.__name__} should be async"

    def test_synchronous_methods_still_work(self):
        """Test that synchronous methods still work"""
        # These methods should remain synchronous
        sync_methods = [
            '__init__',
            '_get_thread_state',
            '_mark_activity',
            '_is_session_idle',
            '_evict_oldest_pair_to_batch',
            'add_user_message',
            'get_context_for_llm',
            'prime_inmemorysaver',
            '_shutdown_hook',
        ]
        
        for method_name in sync_methods:
            # Just check that they exist
            assert hasattr(self.memory_manager, method_name)

    @pytest.mark.asyncio
    async def test_batch_write_pairs_is_async(self):
        """Test _batch_write_pairs method signature"""
        import inspect
        assert inspect.iscoroutinefunction(self.memory_manager._batch_write_pairs)

    @pytest.mark.asyncio
    async def test_on_session_start_is_async(self):
        """Test on_session_start method signature"""
        import inspect
        assert inspect.iscoroutinefunction(self.memory_manager.on_session_start)

    @pytest.mark.asyncio
    async def test_add_assistant_message_is_async(self):
        """Test add_assistant_message method signature"""
        import inspect
        assert inspect.iscoroutinefunction(self.memory_manager.add_assistant_message)


class TestAsyncMemoryUtils:
    """Test cases for async memory utilities"""

    def test_imports_work(self):
        """Test that we can import the memory utilities"""
        from app.langgraph.memory_utils import (
            get_next_seq_from_dynamodb,
            get_next_turn_from_dynamodb,
            read_pairs_from_dynamodb,
            load_conversation_state_from_dynamodb
        )
        assert get_next_seq_from_dynamodb is not None
        assert get_next_turn_from_dynamodb is not None
        assert read_pairs_from_dynamodb is not None
        assert load_conversation_state_from_dynamodb is not None

    @pytest.mark.asyncio
    async def test_async_utility_functions(self):
        """Test that utility functions are async"""
        import inspect
        from app.langgraph.memory_utils import (
            get_next_seq_from_dynamodb,
            get_next_turn_from_dynamodb,
            read_pairs_from_dynamodb,
            load_conversation_state_from_dynamodb
        )
        
        functions = [
            get_next_seq_from_dynamodb,
            get_next_turn_from_dynamodb,
            read_pairs_from_dynamodb,
            load_conversation_state_from_dynamodb,
        ]
        
        for func in functions:
            assert inspect.iscoroutinefunction(func), f"{func.__name__} should be async"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])