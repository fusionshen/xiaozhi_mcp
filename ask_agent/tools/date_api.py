import dateparser

async def parse_date(date_str: str):
    if not date_str:
        return None
    dt = dateparser.parse(date_str, languages=["zh"])
    if dt:
        return dt.strftime("%Y-%m-%d")
    return None
