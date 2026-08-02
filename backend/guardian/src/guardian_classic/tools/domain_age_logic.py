from datetime import datetime, timezone
import whois

def get_domain_age_days(domain: str) -> int | None:
    """Zwraca wiek domeny w dniach albo None, jeśli nie udało się ustalić."""

    try: 
        result = whois.whois(domain)
    except Exception:
        return None 
    
    creation = result.creation_date

    if isinstance(creation, list):
        creation = creation[0] if creation else None

    if not isinstance(creation, datetime):
        return None
    
    if creation.tzinfo is None:
        creation = creation.replace(tzinfo=timezone.utc)

    return (datetime.now(timezone.utc) - creation).days