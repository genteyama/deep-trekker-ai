from datetime import datetime, timezone

from models import (
    DestinationRegion,
    RecordStatus,
    ShippingScopeType,
    ShippingType,
    UpdateCategory,
    YesNoUnknown,
)

DEALER_UPDATE_TITLE = "Deep Trekker Dealer Update: September Edition"
DEALER_UPDATE_DATE = datetime(2026, 9, 18, tzinfo=timezone.utc)
DEALER_UPDATE_REFERENCE = "dealer-update-2026-09"

STANDARD_SHIPPING_RATES = (
    {
        "shipping_type": ShippingType.LARGE_BOX,
        "destination_region": DestinationRegion.USA,
        "rate_usd": 732.15,
        "title": "Large Box Shipping to USA",
    },
    {
        "shipping_type": ShippingType.LARGE_BOX,
        "destination_region": DestinationRegion.EUROPE_UK,
        "rate_usd": 1748.15,
        "title": "Large Box to Europe & UK",
    },
    {
        "shipping_type": ShippingType.LARGE_BOX,
        "destination_region": DestinationRegion.GLOBAL,
        "rate_usd": 2922.15,
        "title": "Large Box Shipping Globally",
    },
    {
        "shipping_type": ShippingType.SMALL_BOX,
        "destination_region": DestinationRegion.USA,
        "rate_usd": 152.00,
        "title": "Small Box Shipping to USA",
    },
    {
        "shipping_type": ShippingType.SMALL_BOX,
        "destination_region": DestinationRegion.EUROPE_UK,
        "rate_usd": 690.00,
        "title": "Small Box to Europe & UK",
    },
    {
        "shipping_type": ShippingType.SMALL_BOX,
        "destination_region": DestinationRegion.GLOBAL,
        "rate_usd": 1356.00,
        "title": "Small Box Shipping Globally",
    },
    {
        "shipping_type": ShippingType.PIPE_TREKKER,
        "destination_region": DestinationRegion.USA,
        "rate_usd": 2244.15,
        "title": "Pipe Trekker Shipping to USA",
    },
    {
        "shipping_type": ShippingType.PIPE_TREKKER,
        "destination_region": DestinationRegion.EUROPE_UK,
        "rate_usd": 4668.15,
        "title": "Pipe Trekker to Europe & UK",
    },
    {
        "shipping_type": ShippingType.PIPE_TREKKER,
        "destination_region": DestinationRegion.GLOBAL,
        "rate_usd": 8828.15,
        "title": "Pipe Trekker Shipping Globally",
    },
)

LEAD_TIMES = (
    {"product": "DTG3", "new_value": "6", "unit": "weeks"},
    {"product": "PHOTON", "new_value": "9", "unit": "weeks"},
    {"product": "PIVOT", "new_value": "10", "unit": "weeks"},
    {"product": "REVOLUTION", "new_value": "15", "unit": "weeks"},
    {"product": "A-200", "new_value": "6", "unit": "weeks"},
    {"product": "VAC", "new_value": "20", "unit": "weeks"},
)

PRODUCT_SPECS = (
    {
        "product": "SPECTRA",
        "title": "SPECTRA forward speed",
        "summary": "Forward speed announced in the September Dealer Update.",
        "new_value": "3.5",
        "unit": "knots",
    },
    {
        "product": "SPECTRA",
        "title": "SPECTRA lateral speed",
        "summary": "Lateral speed announced in the September Dealer Update.",
        "new_value": "2.3",
        "unit": "knots",
    },
    {
        "product": "SPECTRA",
        "title": "SPECTRA first units estimate",
        "summary": "Production estimate from the September Dealer Update. Not a confirmed TechnicalFact.",
        "new_value": "February 2027",
        "unit": None,
        "is_time_sensitive": True,
    },
)

SHIPPING_NOTES = (
    "Dealer Update explains Dangerous Goods classifications and freight cost increases. "
    "The email does not say these rates apply to every Non-DG part. "
    "dangerous_goods remains UNKNOWN."
)

MATCH_HINTS = (
    "deep trekker dealer update: september edition",
    "september edition",
    "732.15",
    "2922.15",
    "1356.00",
    "8828.15",
)

DEFAULT_SHIPPING_FLAGS = {
    "dangerous_goods": YesNoUnknown.UNKNOWN,
    "battery_included": YesNoUnknown.UNKNOWN,
    "scope_type": ShippingScopeType.STANDARD,
    "status": RecordStatus.CANDIDATE,
    "category": UpdateCategory.SHIPPING,
    "target_master": "ShippingRule",
}
