from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class TransactionInput(BaseModel):
    description: str
    amount: float
    currency: str = "USD"
    date: Optional[str] = None
    category: Optional[str] = None


class CurrencyConversionRequest(BaseModel):
    amount: float = Field(ge=0)
    from_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    to_currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


class FinancialRequest(BaseModel):
    income: float = 0.0
    currency: str = "USD"
    location: Optional[str] = None
    goal_name: Optional[str] = None
    goal_amount: float = 0.0
    goal_saved: float = 0.0
    transactions: List[TransactionInput] = Field(default_factory=list)
    session_id: Optional[str] = None


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None
    income: Optional[float] = None
    currency: str = "USD"
    location: Optional[str] = None
    transactions: List[TransactionInput] = Field(default_factory=list)
    goals: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None


class MessageResponse(BaseModel):
    reply: str
    session_id: str
    data: Dict[str, Any] = Field(default_factory=dict)


class AdminUserStatusUpdate(BaseModel):
    enabled: bool


class AdminUserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    username: Optional[str] = Field(default=None, min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    connection: str = Field(min_length=1, max_length=128)


class AdminUserPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class HistoricalPermissionsUpdate(BaseModel):
    can_edit_previous_month: bool
    can_delete_previous_month: bool
    can_clear_previous_month: bool
