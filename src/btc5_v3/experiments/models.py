from dataclasses import dataclass
import re
from btc5_v3.encoding import identifier, timestamp


@dataclass(frozen=True)
class Experiment:
    id: str
    git_commit: str
    data_version: str
    seed: int
    created_at: int
    config_hash: str
    schema_version: int = 1
    model_version: str = 'not_applicable'

    def __post_init__(self):
        identifier(self.id); identifier(self.data_version)
        if not re.fullmatch(r'[0-9a-f]{40}', self.git_commit):
            raise ValueError('exact git commit required')
        if not re.fullmatch(r'[0-9a-f]{64}', self.config_hash):
            raise ValueError('config hash required')
        if not timestamp(self.created_at) or type(self.seed) is not int or not 0<=self.seed<2**32:
            raise ValueError('invalid experiment metadata')
        if self.schema_version != 1 or self.model_version != 'not_applicable':
            raise ValueError('M1 does not run models')
