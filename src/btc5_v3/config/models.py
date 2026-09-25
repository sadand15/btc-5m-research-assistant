from dataclasses import asdict, dataclass
from pathlib import Path
import os
import subprocess

from btc5_v3.encoding import digest, identifier


@dataclass(frozen=True)
class ValidatorConfig:
    market_id: str
    feed: str
    rule_hash: str
    outcome_mapping: str = 'YES_UP'
    market_type: str = 'CRYPTO_UP_DOWN'
    clock_skew_tolerance_ms: int = 0
    max_levels: int = 1000
    schema_version: int = 1

    def __post_init__(self):
        for value in (self.market_id, self.feed, self.rule_hash):
            identifier(value)
        if self.outcome_mapping not in ('YES_UP', 'YES_DOWN'):
            raise ValueError('unsupported outcome mapping')
        if self.market_type != 'CRYPTO_UP_DOWN' or self.schema_version != 1:
            raise ValueError('unsupported schema/market type')
        if type(self.clock_skew_tolerance_ms) is not int or not 0 <= self.clock_skew_tolerance_ms <= 60000:
            raise ValueError('invalid clock tolerance')
        if type(self.max_levels) is not int or not 1 <= self.max_levels <= 1000:
            raise ValueError('invalid depth limit')

    @property
    def hash(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class StorageConfig:
    project_root: Path
    database: Path | None = None
    protected_databases: tuple[Path, ...] = ()

    def resolved_path(self) -> Path:
        root = Path(self.project_root).resolve()
        allowed = root / 'runtime' / 'v3'
        requested = Path(self.database) if self.database is not None else allowed / 'research.sqlite'
        if not requested.is_absolute():
            requested = root / requested
        # Reject reparse-point aliases before creating directories/opening SQLite.
        for part in (allowed, requested):
            for candidate in (part, *part.parents):
                if candidate == root:
                    break
                if candidate.is_symlink() or getattr(candidate, 'is_junction', lambda: False)():
                    raise ValueError('database path alias rejected')
        resolved = requested.resolve()
        if not resolved.is_relative_to(allowed) or resolved == allowed:
            raise ValueError('database must remain inside isolated runtime/v3')
        protected = [root / 'runtime/research.sqlite', *map(Path, self.protected_databases)]
        # Linked worktrees share Git objects, not their original runtime database.
        if (root / '.git').exists():
            result = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=root,
                                    capture_output=True, text=True, check=True)
            common = Path(result.stdout.strip())
            if not common.is_absolute():
                common = root / common
            protected.append(common.resolve().parent / 'runtime/research.sqlite')
        for database in protected:
            for candidate in (database, Path(str(database)+'-wal'), Path(str(database)+'-shm')):
                if resolved == candidate.resolve() or (resolved.exists() and candidate.exists() and os.path.samefile(resolved, candidate)):
                    raise ValueError('V2 database collision rejected')
        if resolved.exists() and resolved.stat().st_nlink > 1:
            raise ValueError('hardlinked database rejected')
        return resolved
