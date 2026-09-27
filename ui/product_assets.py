from html import escape
from pathlib import Path
from typing import Optional
import base64

PRODUCTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "products"

PRODUCT_IMAGE_FILES = {
    "PHOTON": "photon.png",
    "PIVOT": "pivot.png",
    "REVOLUTION": "revolution.png",
    "SPECTRA": "spectra.png",
    "PIPETREKKER": "pipetrekker.png",
    "PIPE TREKKER": "pipetrekker.png",
    "A-200S": "a200s.png",
    "MAG": "mag.png",
}


def normalize_product_key(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace("_", "-")


def product_image_path(value: Optional[str]) -> Optional[Path]:
    key = normalize_product_key(value)
    filename = PRODUCT_IMAGE_FILES.get(key)
    if not filename:
        return None
    path = PRODUCTS_DIR / filename
    return path if path.exists() else None


def product_image_data_uri(value: Optional[str]) -> Optional[str]:
    path = product_image_path(value)
    if path is None:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    return f"data:image/{mime};base64,{encoded}"


def product_image_html(value: Optional[str], *, css_class: str = "portal-product-image", alt: Optional[str] = None) -> str:
    uri = product_image_data_uri(value)
    if not uri:
        return ""
    label = escape(alt or normalize_product_key(value) or "product")
    return f"<img class='{css_class}' src='{uri}' alt='{label}' />"
