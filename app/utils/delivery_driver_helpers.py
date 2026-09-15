"""
Shared logic for "what should a driver see as their next route" — used by
both the worker home hero and the My Routes list, so the two pages never
disagree about which route is front-and-center.
"""
from datetime import date as date_type
from typing import List, Optional

from app.models.delivery import DeliveryRoute

ACTIVE_STATUSES = ("draft", "assigned", "in_progress")


def next_driver_route(routes: List[DeliveryRoute]) -> Optional[DeliveryRoute]:
    """The route a driver should see front-and-center: an in-progress route
    takes priority, otherwise the soonest not-yet-started route — regardless
    of whether that's today or a future date."""
    active = [r for r in routes if r.status in ACTIVE_STATUSES]
    if not active:
        return None
    in_progress = [r for r in active if r.status == "in_progress"]
    if in_progress:
        return in_progress[0]
    return min(active, key=lambda r: r.date)


def route_date_label(route_date: date_type, today: date_type) -> str:
    delta = (route_date - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return route_date.strftime("%A, %b %d")


def pending_maps_stops(route: DeliveryRoute) -> list:
    """Remaining stops with an address, in delivery order, for a one-tap
    Google Maps launch."""
    return [
        {"name": rs.stop.name, "address": rs.stop.address}
        for rs in route.route_stops
        if rs.status == "pending" and rs.stop.address
    ]
