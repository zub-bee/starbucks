from enum import Enum
from pydantic import BaseModel


class OrderStatus(str, Enum):
    ACCEPTED = "accepted"
    IN_PREPARATION = "in_preparation"
    READY = "ready"
    REJECTED = "rejected"


class ComponentRequirement(BaseModel):
    component_id: str
    quantity_needed: int


class OrderItem(BaseModel):
    drink_name: str
    components: list[ComponentRequirement]


class CreateOrderRequest(BaseModel):
    store_id: str
    customer_name: str
    items: list[OrderItem]


class Order(BaseModel):
    order_id: str
    store_id: str
    customer_name: str
    status: OrderStatus
    created_at: str
    rejection_reason: str | None = None


class QueueEntry(BaseModel):
    position: int
    order_id: str
    store_id: str
    customer_name: str
    added_at: str
