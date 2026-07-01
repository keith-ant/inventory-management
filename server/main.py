from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str
    category: Optional[str] = None
    unit_cost: Optional[float] = None

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class RestockRecommendation(BaseModel):
    item_sku: str
    item_name: str
    category: str
    trend: str
    shortfall: int
    quantity: int
    unit_cost: float
    line_total: float
    lead_time_days: int
    partial: bool = False

class RestockRecommendationResponse(BaseModel):
    budget: float
    total_cost: float
    remaining_budget: float
    recommendations: List[RestockRecommendation]
    skipped_items: int

class RestockOrderItemRequest(BaseModel):
    sku: str
    quantity: int

class CreateRestockOrderRequest(BaseModel):
    budget: Optional[float] = None
    items: List[RestockOrderItemRequest]

class RestockOrderItem(BaseModel):
    sku: str
    name: str
    category: str
    quantity: int
    unit_cost: float
    line_total: float
    lead_time_days: int

class RestockOrder(BaseModel):
    id: str
    order_number: str
    status: str
    order_date: str
    expected_delivery: str
    lead_time_days: int
    total_value: float
    budget: Optional[float] = None
    items: List[RestockOrderItem]

# Supplier delivery lead times by category (days). Unlisted categories fall
# back to DEFAULT_LEAD_TIME_DAYS.
CATEGORY_LEAD_TIMES = {
    "Circuit Boards": 14,
    "Controllers": 12,
    "Power Supplies": 10,
    "Sensors": 7,
    "Actuators": 5,
    "Mechanical Components": 5,
    "Motors": 21,
    "Filtration": 4,
}
DEFAULT_LEAD_TIME_DAYS = 7

# Trend weights for restock urgency scoring
TREND_WEIGHTS = {"increasing": 1.5, "stable": 1.0, "decreasing": 0.5}

# Submitted restocking orders (in-memory, resets on server restart)
restock_orders: list = []

def lead_time_for_category(category: str) -> int:
    return CATEGORY_LEAD_TIMES.get(category, DEFAULT_LEAD_TIME_DAYS)

def build_restock_candidates() -> list:
    """Join demand forecasts with inventory stock levels and rank by urgency.

    Shortfall is forecasted demand minus on-hand stock; forecast SKUs absent
    from inventory are treated as zero stock (they need a full restock).
    """
    inventory_by_sku = {item["sku"]: item for item in inventory_items}
    candidates = []
    for forecast in demand_forecasts:
        unit_cost = forecast.get("unit_cost")
        if not unit_cost:
            continue
        on_hand = inventory_by_sku.get(forecast["item_sku"], {}).get("quantity_on_hand", 0)
        shortfall = forecast["forecasted_demand"] - on_hand
        if shortfall <= 0:
            continue
        urgency = shortfall * TREND_WEIGHTS.get(forecast["trend"], 1.0)
        candidates.append({
            "item_sku": forecast["item_sku"],
            "item_name": forecast["item_name"],
            "category": forecast.get("category") or "Uncategorized",
            "trend": forecast["trend"],
            "shortfall": shortfall,
            "unit_cost": unit_cost,
            "urgency": urgency,
        })
    candidates.sort(key=lambda c: c["urgency"], reverse=True)
    return candidates

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/restock/recommendations", response_model=RestockRecommendationResponse)
def get_restock_recommendations(budget: float):
    """Recommend items to restock within a budget.

    Candidates are ranked by urgency (demand shortfall weighted by trend) and
    added greedily until the budget is exhausted. If the next item's full
    shortfall doesn't fit, a partial quantity is recommended.
    """
    if budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be greater than zero")

    remaining = budget
    recommendations = []
    skipped = 0

    for candidate in build_restock_candidates():
        full_cost = candidate["shortfall"] * candidate["unit_cost"]
        if full_cost <= remaining:
            quantity, partial = candidate["shortfall"], False
        else:
            quantity, partial = int(remaining // candidate["unit_cost"]), True
            if quantity < 1:
                skipped += 1
                continue
        line_total = round(quantity * candidate["unit_cost"], 2)
        remaining -= line_total
        recommendations.append({
            "item_sku": candidate["item_sku"],
            "item_name": candidate["item_name"],
            "category": candidate["category"],
            "trend": candidate["trend"],
            "shortfall": candidate["shortfall"],
            "quantity": quantity,
            "unit_cost": candidate["unit_cost"],
            "line_total": line_total,
            "lead_time_days": lead_time_for_category(candidate["category"]),
            "partial": partial,
        })

    total_cost = round(sum(r["line_total"] for r in recommendations), 2)
    return {
        "budget": budget,
        "total_cost": total_cost,
        "remaining_budget": round(budget - total_cost, 2),
        "recommendations": recommendations,
        "skipped_items": skipped,
    }

@app.post("/api/restock-orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order. Costs and lead times are resolved
    server-side from the demand forecast data, not trusted from the client."""
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    forecasts_by_sku = {f["item_sku"]: f for f in demand_forecasts}
    order_items = []
    for item in request.items:
        forecast = forecasts_by_sku.get(item.sku)
        if not forecast or not forecast.get("unit_cost"):
            raise HTTPException(status_code=400, detail=f"Unknown restock item SKU: {item.sku}")
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail=f"Quantity for {item.sku} must be at least 1")
        category = forecast.get("category") or "Uncategorized"
        order_items.append({
            "sku": item.sku,
            "name": forecast["item_name"],
            "category": category,
            "quantity": item.quantity,
            "unit_cost": forecast["unit_cost"],
            "line_total": round(item.quantity * forecast["unit_cost"], 2),
            "lead_time_days": lead_time_for_category(category),
        })

    # The order arrives when its slowest item does
    lead_time_days = max(i["lead_time_days"] for i in order_items)
    now = datetime.now()
    order = {
        "id": str(len(restock_orders) + 1),
        "order_number": f"RST-{now.year}-{len(restock_orders) + 1:04d}",
        "status": "Submitted",
        "order_date": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "expected_delivery": (now + timedelta(days=lead_time_days)).strftime("%Y-%m-%dT%H:%M:%S"),
        "lead_time_days": lead_time_days,
        "total_value": round(sum(i["line_total"] for i in order_items), 2),
        "budget": request.budget,
        "items": order_items,
    }
    restock_orders.append(order)
    return order

@app.get("/api/restock-orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Get all submitted restocking orders (newest first)"""
    return list(reversed(restock_orders))

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
