# Publication security audit

This is a release-time audit, not a guarantee about future changes.

- Local source, configuration, logs, SQLite/WAL files, model files and generated data were searched using redacted credential signatures. The first pass covered 450 files and 737,503,079 bytes; no credential signature was found. Compressed market ZIP contents are not decoded by this byte scan; those archives are excluded from Git regardless.
- All 97 pre-existing Git blob objects (including unreachable snapshots) were scanned; no credential signature was found. There were no prior commits or remotes at the start of publication.
- All six locally generated joblib artifacts were inspected. Each includes five absolute local storage paths in its configuration; none is published. The frozen model and its backup are retained unchanged on the observation host.
- Source review confirms the Predict.fun client reads its key from process environment and attaches it only as the market-data request header. No key value is placed in project config or test fixtures. `.env.example` contains an empty variable only.
- Local LAN addresses in reports and the report-generator template were replaced by `PC-LAN-IP`. The public freeze record omits private database and backup paths. Git commits use the existing GitHub noreply identity.
- Tracked and historical blobs are scanned again before upload. No runtime database, full observation series, archive ZIP, model binary or environment file is an intended release asset.

The Predict.fun key previously appeared in a chat message. Rotation is recommended for that exposure even though no project-file or Git-object secret was found. Rotation was not performed during release packaging because the current observation process uses the existing environment credential.

## Maintenance

Run `python scripts/security_scan.py index` and `python scripts/security_scan.py history` before pushing. The scanner reports only file/object identifiers and rule names, never matching values. Review staged paths and sizes as well: scanners are heuristic and do not replace review.

Do not upload environment files, HTTP headers, private keys, local session exports or runtime databases as issue attachments or release assets. Runtime data belongs under ignored `runtime/`; small intentionally public research reports may be committed after review.
