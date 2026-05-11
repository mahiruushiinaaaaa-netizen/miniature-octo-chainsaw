"""
message_protocol.py – Unified message format for AI↔System communication.

Provides standardized message types, serialization, and correlation tracking
for all communication between the AI model and system components.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class MessageType(Enum):
    """Types of messages in the system."""
    QUERY = "query"
    RESPONSE = "response"
    OBSERVATION = "observation"
    ACTION = "action"
    ERROR = "error"
    STATUS = "status"
    HEARTBEAT = "heartbeat"
    DEBUG = "debug"


class Priority(Enum):
    """Message priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class SystemMessage:
    """
    Unified message format for AI↔System communication.
    
    Attributes:
        msg_type: Type of message (query, response, observation, etc.)
        priority: Message priority (affects processing order)
        content: Main message content
        context: Additional context dict
        timestamp: When message was created
        correlation_id: Links related messages together
        metadata: Additional metadata for debugging/monitoring
        sender: Which component sent this message
    """
    msg_type: MessageType
    content: str = ""
    priority: Priority = Priority.NORMAL
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)
    sender: str = "system"
    
    def to_json(self) -> str:
        """Serialize message to JSON."""
        data = asdict(self)
        data['msg_type'] = self.msg_type.value
        data['priority'] = self.priority.name
        return json.dumps(data, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> SystemMessage:
        """Deserialize message from JSON."""
        data = json.loads(json_str)
        data['msg_type'] = MessageType(data['msg_type'])
        data['priority'] = Priority[data['priority']]
        return cls(**data)
    
    def __repr__(self) -> str:
        return (
            f"SystemMessage(type={self.msg_type.value}, "
            f"priority={self.priority.name}, "
            f"sender={self.sender}, "
            f"correlation={self.correlation_id[:8]}...)"
        )


@dataclass
class CommandRequest:
    """Request from AI to execute a system command."""
    tool: str
    args: dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    timeout_seconds: float = 300.0
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), default=str)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandRequest:
        """Deserialize from dict."""
        return cls(**data)


@dataclass
class CommandResponse:
    """Response from system to AI's command."""
    request_id: str
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "request_id": self.request_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), default=str)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandResponse:
        """Deserialize from dict."""
        return cls(**data)
