import ipaddress
import re
from typing import Any

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|token|secret|auth|bearer|card|pan|cvv|fiscal_code|cf|email|"
    r"phone|tax_id|ssn|name|text|raw|content)",
    re.IGNORECASE,
)


def anonymize_ip_address(ip: str | None) -> str | None:
    """Anonimizza un IP (IPv4 /24 o IPv6 /48) in conformità al GDPR."""
    if not ip or not ip.strip():
        return None

    clean_ip = ip.strip().split(",")[0].strip()

    try:
        parsed_ip = ipaddress.ip_address(clean_ip)
        if isinstance(parsed_ip, ipaddress.IPv4Address):
            # Maschera l'ultimo ottetto (/24)
            network = ipaddress.IPv4Network(f"{clean_ip}/24", strict=False)
            return str(network.network_address)
        if isinstance(parsed_ip, ipaddress.IPv6Address):
            # Maschera gli ultimi 80 bit (/48)
            network_v6 = ipaddress.IPv6Network(f"{clean_ip}/48", strict=False)
            return str(network_v6.network_address)
    except ValueError:
        pass

    return "0.0.0.0"


def sanitize_audit_details(
    details: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Rimuove ricorsivamente eventuali dati PII dai dettagli di audit."""
    if details is None:
        return None

    sanitized: dict[str, Any] = {}
    for k, v in details.items():
        if SENSITIVE_KEY_PATTERNS.search(str(k)):
            continue

        if isinstance(v, dict):
            sanitized[k] = sanitize_audit_details(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_audit_details(item) if isinstance(item, dict) else item
                for item in v
                if not (isinstance(item, str) and len(item) > 100)
            ]
        elif isinstance(v, (str, int, float, bool)) or v is None:
            sanitized[k] = v

    return sanitized
