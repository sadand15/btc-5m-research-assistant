"""Safe diagnostics: no exception text or transport payload is exposed."""
import re
from decimal import Decimal

SENSITIVE = re.compile(r'(?i)authorization|cookie|password|passwd|secret|api.?key|token|credential|private.?key|wallet.?key|wallet.?seed|mnemonic|seed.?phrase|passphrase')
CREDENTIAL = re.compile(r'(?i)(?:pred_sk_[a-z0-9]+|gh[pousr]_[a-z0-9_]+|github_pat_[a-z0-9_]+|(?:AKIA|ASIA)[A-Z0-9]{16}|https?://[^\s/:@]+:[^\s/@]+@[^\s]+|bearer\s+[^\s,;]+|eyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+|-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*|(?:api.?key|token|secret|password|authorization|cookie)\s*[:=]\s*[^\s,;]+)')


def redact(value, depth=0):
    if depth>24: return '[REDACTED_DEPTH_LIMIT]'
    if isinstance(value,dict):
        return {CREDENTIAL.sub('[REDACTED]',str(k))[:256]: '[REDACTED]' if SENSITIVE.search(str(k))
                else redact(v,depth+1) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [redact(v,depth+1) for v in value]
    if isinstance(value,str): return CREDENTIAL.sub('[REDACTED]',value)[:50000]
    if isinstance(value,Decimal): return value if value.is_finite() else None
    if value is None or isinstance(value,(bool,int)): return value
    if isinstance(value,float):
        import math
        return value if math.isfinite(value) else None
    return '[UNSUPPORTED]'


def diagnostic(kind, source, identity, *, at=None, severity='ERROR'):
    return dict(type=kind, source=source, record_id=redact(identity), timestamp=at, severity=severity,
                description={'CORRUPTED':'Stored content, identity or hash failed integrity checks.',
                    'MISMATCH':'Recorded monetary or inventory values do not reconcile.',
                    'INCOMPLETE':'Required archive evidence is missing or exceeds the read budget.',
                    'UNKNOWN_ENUM':'Unrecognized recorded status; no healthy state inferred.',
                    'INVALID_REFERENCE':'A source reference is missing or inconsistent.',
                    'MALFORMED_HEALTH':'Health evidence is malformed or not causally available.',
                    'UNAVAILABLE':'Supported read-only research evidence is unavailable.',
                    'MISSING_PROVENANCE':'Required provenance is absent or unverifiable.'}.get(kind,'Observation could not be verified.'))
