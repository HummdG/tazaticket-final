"""
Memory manager utility functions for DynamoDB operations and message handling.
"""

import os
import time
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import threading
from langchain_core.messages import HumanMessage, AIMessage

load_dotenv()
# Configuration from environment
CHAT_HISTORY_TABLE = os.getenv("CHAT_HISTORY_TABLE")
AWS_REGION = os.getenv("AWS_REGION")
SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_SECONDS")) # 6 hours
CONTEXT_PAIRS = int(os.getenv("CONTEXT_PAIRS"))
BATCH_PAIRS = int(os.getenv("BATCH_PAIRS"))
MAX_RAM_PAIRS = int(os.getenv("MAX_RAM_PAIRS"))


@dataclass
class Message:
    """Represents a single chat message"""
    role: str  # 'user' or 'assistant'
    content: str
    ts_iso: str
    seq: int
    turn: int  # pair index
    meta: Optional[Dict[str, Any]] = None


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
    lock: threading.Lock = field(default_factory=threading.Lock)


def get_now_iso() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


def get_next_seq_from_dynamodb(dynamodb_client, thread_id: str) -> int:
    """Get next sequence number atomically from DynamoDB"""
    try:
        response = dynamodb_client.update_item(
            TableName=CHAT_HISTORY_TABLE,
            Key={
                'thread_id': {'S': thread_id},
                'seq': {'N': '0'}  # Meta row for counters
            },
            UpdateExpression='ADD next_seq :one',
            ExpressionAttributeValues={':one': {'N': '1'}},
            ReturnValues='UPDATED_NEW'
        )
        return int(response['Attributes']['next_seq']['N'])
    except ClientError:
        # If meta row doesn't exist, initialize it
        try:
            dynamodb_client.put_item(
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
            return 1
        except ClientError:
            # Race condition - try again
            return get_next_seq_from_dynamodb(dynamodb_client, thread_id)


def get_next_turn_from_dynamodb(dynamodb_client, thread_id: str) -> int:
    """Get next turn number atomically from DynamoDB"""
    try:
        response = dynamodb_client.update_item(
            TableName=CHAT_HISTORY_TABLE,
            Key={
                'thread_id': {'S': thread_id},
                'seq': {'N': '0'}  # Meta row for counters
            },
            UpdateExpression='ADD next_turn :one',
            ExpressionAttributeValues={':one': {'N': '1'}},
            ReturnValues='UPDATED_NEW'
        )
        return int(response['Attributes']['next_turn']['N'])
    except ClientError:
        # Meta row should exist from get_next_seq
        return get_next_turn_from_dynamodb(dynamodb_client, thread_id)


def read_pairs_from_dynamodb(dynamodb_client, thread_id: str, n: int) -> List[Pair]:
    """Read last n complete pairs from DynamoDB"""
    try:
        # Query in reverse order to get most recent messages
        response = dynamodb_client.query(
            TableName=CHAT_HISTORY_TABLE,
            KeyConditionExpression='thread_id = :tid AND seq > :zero',
            ExpressionAttributeValues={
                ':tid': {'S': thread_id},
                ':zero': {'N': '0'}  # Skip meta row
            },
            ScanIndexForward=False,  # Reverse order (newest first)
            Limit=n * 2 + 10  # Get enough messages to form n pairs
        )
        
        # Group messages by turn to form pairs
        messages_by_turn: Dict[int, Dict[str, Message]] = {}
        
        for item in response['Items']:
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
        for turn in sorted(messages_by_turn.keys(), reverse=True):  # Newest first
            turn_messages = messages_by_turn[turn]
            if 'user' in turn_messages:
                pair = Pair(
                    turn=turn,
                    user_message=turn_messages['user'],
                    assistant_message=turn_messages.get('assistant')
                )
                # Only include complete pairs
                if pair.is_complete:
                    pairs.append(pair)
        
        # Return last n complete pairs in chronological order
        return list(reversed(pairs[:n]))
        
    except ClientError as e:
        print(f"Error reading pairs from DynamoDB: {e}")
        return []


def batch_write_pairs_to_dynamodb(dynamodb_client, thread_id: str, pairs: List[Pair], session_id: str) -> None:
    """Write pairs to DynamoDB in batch"""
    if not pairs:
        return
    
    # Prepare batch write items
    items = []
    for pair in pairs:
        # User message
        user_item = {
            'thread_id': {'S': thread_id},
            'seq': {'N': str(pair.user_message.seq)},
            'role': {'S': pair.user_message.role},
            'content': {'S': pair.user_message.content},
            'ts_iso': {'S': pair.user_message.ts_iso},
            'session_id': {'S': session_id},
            'turn': {'N': str(pair.user_message.turn)}
        }
        if pair.user_message.meta:
            user_item['meta'] = {'M': pair.user_message.meta}
        
        items.append({'PutRequest': {'Item': user_item}})
        
        # Assistant message (if exists)
        if pair.assistant_message:
            assistant_item = {
                'thread_id': {'S': thread_id},
                'seq': {'N': str(pair.assistant_message.seq)},
                'role': {'S': pair.assistant_message.role},
                'content': {'S': pair.assistant_message.content},
                'ts_iso': {'S': pair.assistant_message.ts_iso},
                'session_id': {'S': session_id},
                'turn': {'N': str(pair.assistant_message.turn)}
            }
            if pair.assistant_message.meta:
                assistant_item['meta'] = {'M': pair.assistant_message.meta}
            
            items.append({'PutRequest': {'Item': assistant_item}})
    
    # Batch write with retry for unprocessed items
    unprocessed_items = items
    retry_count = 0
    max_retries = 3
    
    while unprocessed_items and retry_count < max_retries:
        try:
            response = dynamodb_client.batch_write_item(
                RequestItems={CHAT_HISTORY_TABLE: unprocessed_items}
            )
            unprocessed_items = response.get('UnprocessedItems', {}).get(CHAT_HISTORY_TABLE, [])
            
            if unprocessed_items:
                retry_count += 1
                if retry_count < max_retries:
                    sleep_time = min(2 ** retry_count, 8)  # Cap at 8 seconds
                    time.sleep(sleep_time)
            else:
                return  # Exit successfully
                
        except ClientError as e:
            print(f"Error batch writing to DynamoDB: {e}")
            retry_count += 1
            if retry_count < max_retries:
                sleep_time = min(2 ** retry_count, 8)  # Cap at 8 seconds
                time.sleep(sleep_time)
            else:
                raise
    
    # If we exit the loop due to unprocessed items, warn but don't crash
    if unprocessed_items:
        print(f"Warning: {len(unprocessed_items)} items could not be written after {max_retries} retries")


def load_conversation_state_from_dynamodb(dynamodb_client, thread_id: str) -> List[Pair]:
    """Load conversation state from DynamoDB (try new format first, fall back to old format)"""
    try:
        # First, try to get the new conversation state item
        response = dynamodb_client.get_item(
            TableName=CHAT_HISTORY_TABLE,
            Key={
                'thread_id': {'S': thread_id},
                'seq': {'N': '-1'}  # Conversation state is always at seq=-1
            }
        )
        
        if 'Item' in response:
            item = response['Item']
            
            # Parse the messages JSON
            messages_json = item.get('messages', {}).get('S', '[]')
            messages = json.loads(messages_json)
            
            # Convert messages back to pairs
            pairs = []
            current_pair = None
            
            for msg in messages:
                if msg['role'] == 'user':
                    # Start new pair
                    user_message = Message(
                        role=msg['role'],
                        content=msg['content'],
                        ts_iso=msg['ts_iso'],
                        seq=1,  # We'll renumber these
                        turn=msg['turn']
                    )
                    current_pair = Pair(turn=msg['turn'], user_message=user_message)
                    
                elif msg['role'] == 'assistant' and current_pair:
                    # Complete the pair
                    assistant_message = Message(
                        role=msg['role'],
                        content=msg['content'],
                        ts_iso=msg['ts_iso'],
                        seq=2,  # We'll renumber these
                        turn=msg['turn']
                    )
                    current_pair.assistant_message = assistant_message
                    pairs.append(current_pair)
                    current_pair = None
            
            # If there's an incomplete pair, we'll handle it separately
            if current_pair:
                pairs.append(current_pair)
            
            return pairs
        
        else:
            # Fall back to old format - query individual messages
            return read_pairs_from_dynamodb(dynamodb_client, thread_id, CONTEXT_PAIRS)
        
    except Exception as e:
        print(f"Error loading conversation state: {e}")
        # Fall back to old format on any error
        try:
            return read_pairs_from_dynamodb(dynamodb_client, thread_id, CONTEXT_PAIRS)
        except:
            return [] 