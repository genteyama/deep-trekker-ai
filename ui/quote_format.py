def display_number(value, empty: str = "値なし") -> str:
    if value is None:
        return empty
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}"


def display_percent(value, empty: str = "未設定") -> str:
    if value is None:
        return empty
    return f"{value:.2%}"


def display_yen(value, empty: str = "未設定") -> str:
    if value is None:
        return empty
    return f"¥{int(round(value)):,}"


def is_unset(value) -> bool:
    return value is None
