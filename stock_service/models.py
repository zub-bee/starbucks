from pydantic import BaseModel


class ComponentRequirement(BaseModel):
    component_id: str
    quantity_needed: int


class ValidateRequest(BaseModel):
    store_id: str
    components: list[ComponentRequirement]


class ComponentResult(BaseModel):
    component_id: str
    component_name: str
    required: int
    available: int
    sufficient: bool


class ValidateResponse(BaseModel):
    store_id: str
    store_open: bool
    valid: bool
    components: list[ComponentResult]
    rejection_reason: str | None = None


class ReserveRequest(BaseModel):
    order_id: str
    store_id: str
    components: list[ComponentRequirement]


class ReserveResponse(BaseModel):
    order_id: str
    success: bool


class StockItem(BaseModel):
    component_id: str
    component_name: str
    component_type: str
    quantity_on_hand: int
    reserved_quantity: int
    available_quantity: int
    last_updated_at: str
