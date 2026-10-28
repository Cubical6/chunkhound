"""Public shop API, including an intentional re-export."""

from .orders import place_order

__all__ = ["place_order"]
