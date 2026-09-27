from html import escape
from typing import Optional

from ui.product_assets import normalize_product_key


def product_badge_label(value: Optional[str]) -> str:
    return normalize_product_key(value)


def product_badge_html(value: Optional[str]) -> str:
    label = product_badge_label(value)
    if not label:
        return ""
    return f"<span class='product-badge'>{escape(label)}</span>"
