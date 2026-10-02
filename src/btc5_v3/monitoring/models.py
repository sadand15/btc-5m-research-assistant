from dataclasses import dataclass
import json
from btc5_v3.encoding import canonical, digest, timestamp

PAGES = ('Overview', 'System Health', 'Risk', 'Permissions', 'Reservations', 'Positions',
         'Executions', 'Ledger', 'Timeline', 'Diagnostics', 'Provenance')


@dataclass(frozen=True)
class ViewFilter:
    as_of: int
    start_at: int | None = None
    end_at: int | None = None
    market_id: str = ''
    candidate_id: str = ''
    permission: str = ''
    reason: str = ''
    reservation_id: str = ''
    execution_id: str = ''
    position_status: str = ''
    health_state: str = ''
    risk_guard: str = ''
    category: str = ''
    page: int = 0
    page_size: int = 50

    def __post_init__(self):
        if not timestamp(self.as_of): raise ValueError('invalid as-of time')
        for at in (self.start_at, self.end_at):
            if at is not None and not timestamp(at): raise ValueError('invalid range')
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError('invalid range order')
        if type(self.page) is not int or not 0 <= self.page <= 100000:
            raise ValueError('invalid page')
        if type(self.page_size) is not int or not 1 <= self.page_size <= 200:
            raise ValueError('invalid page size')
        for field in ('market_id','candidate_id','permission','reason','reservation_id','execution_id',
                      'position_status','health_state','risk_guard','category'):
            v=getattr(self,field)
            if not isinstance(v,str) or len(v)>256: raise ValueError('invalid filter')


@dataclass(frozen=True)
class MonitoringView:
    payload_json: str

    def data(self): return json.loads(self.payload_json)

    @property
    def hash(self): return digest(self.data())

    @classmethod
    def create(cls, data):
        from btc5_v3.monitoring.diagnostics import redact
        return cls(canonical(redact(data)))
