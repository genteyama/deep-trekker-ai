from models import PriceBookImportResult, SkuSourceStatus


def summarize_price_book_import(result: PriceBookImportResult) -> dict:
    priced = 0
    unpriced = 0
    obsolete = 0
    for item in result.items:
        if item.msrp_usd is not None or item.dealer_price_usd is not None:
            priced += 1
        else:
            unpriced += 1
        if item.source_status == SkuSourceStatus.OBSOLETE:
            obsolete += 1
    unique = {item.sku for item in result.items}
    unique_active = {
        item.sku
        for item in result.items
        if item.source_status != SkuSourceStatus.OBSOLETE
    }
    unique_obsolete = {
        item.sku
        for item in result.items
        if item.source_status == SkuSourceStatus.OBSOLETE
    }
    return {
        "occurrences": len(result.items),
        "unique_skus": len(unique),
        "priced_rows": priced,
        "unpriced_rows": unpriced,
        "obsolete_rows": obsolete,
        "obsolete_only_skus": len(unique_obsolete - unique_active),
        "candidates": len(result.candidates),
    }
