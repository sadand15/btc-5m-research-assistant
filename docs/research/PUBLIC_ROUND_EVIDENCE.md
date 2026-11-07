# Public round evidence audit — 2026-11-07

Status: **NOT_READY / NOT_EVALUATED**. This is public-source investigation,
not model validation, a study, or an approved venue adapter. No frozen model,
old sealed evidence, production collector or deployment was changed.

## Source evidence

The [Predict.fun audit entry](https://docs.predict.fun/developers/audits) links
the [Cyfrin CRE integration attestation](https://github.com/Cyfrin/cyfrin-audit-reports/blob/main/reports/2026-04-25-cyfrin-predict-cre-integration-v2.1.pdf).
The downloaded PDF SHA256 matches the publisher's accompanying checksum:
`9400c904337009327c7578e609beb1832b1ebbb6f48e4c3006ef4a89d92b0250`.
PDF page 4 identifies reviewed commit `0a580a178f1b2aefb2f8d6e9f14e57babfa86159`
and fix commit `e21160d6dc3a835b3f6b04438530d9fbb2215985` of
`PredictDotFun/prediction-market`. The fixed adapter source URL returned HTTP 404
without authentication. This does not establish why it is unavailable, nor
prove the deployed bytecode matches either commit. The published PDF is an
attestation; it does not contain the full findings or a deployment registry.

The [candidate address's indexed ABI](https://bscscan.com/address/0x77620FAb2969dF2D5696F1f081940E416Cf17cA5#code)
describes the two event layouts below. Direct explorer access returned 403;
therefore indexed ABI metadata is provisional, not independently pinned source.
Their Keccak signatures were cross-checked using public RPC `web3_sha3` and
match the topics in the previously identified receipt:

| Event signature | Topic0 |
|---|---|
| `ChainlinkUpDownAdapter__RoundStartPriceSet(bytes32,uint32,uint32,int192)` | `0xe89432ca865d9fe64c45661232e27514f35299be7d69f2703a7b73e617a8f8ca` |
| `ChainlinkUpDownAdapter__RoundCreated(bytes32,uint32,uint32,bytes32)` | `0x678643534cc22e42cd6eb75c34df1efd42e6af33f80d5939d6cafc4e8fb7d485` |

For each layout, the indexed fields are feed ID and interval; the two data
words are start timestamp and raw signed price or question ID respectively.
Matching a signature proves layout consistency, not source authenticity.

## Bounded public receipt observation

On 2026-11-07, one read-only `eth_getTransactionReceipt` request fetched the
same candidate transaction from `https://bsc-dataseed.bnbchain.org/`:
`0xac2eecefd4342b33b52557fd4c796c97893266e75d535aae09b851871131d4d2`.
No credentials, wallet or funds interfaces were used.

Raw response SHA256:
`fd874869da117bccf4197d591f34c637ba46a9762370d3f18b62587ecabd7fe6`.
The local ignored artifacts are `runtime/public-contract-audit/candidate-receipt.json`
and `candidate-decoded.json`. The latter records retrieval time and endpoint;
retrieval time is **not** historical availability time.

Block: `102497187`; block hash:
`0x48801b75e194a46ed16cca37923c5306e153c35c31c35950b4b376aedbd53861`.
Under the provisional layouts:

- Log 70: interval 300 seconds, start timestamp `1780680900`, raw price
  `60876995000000000000000`. Units/decimals remain unverified; no currency
  price is inferred.
- Log 72: interval 300 seconds, start timestamp `1780767300`, question ID
  `0xeb6c6a77f62ad365bd0303872fb76b101bdee4457a9beb93e0b892af2f1f40fc`.
- Both contain candidate feed ID
  `0x0003ef42b4d20a19409a187c39670a6f5be7ce17fc78c290d25eb45bbf769d37`.
- These start timestamps differ by 86400 seconds. Adjacency in one receipt
  does not establish that they describe the same round. Other logs remain
  explicitly unclassified; no payout/outcome is inferred or joined.

Historical `eth_call` to the candidate `CTF()` and `prices(bytes32,uint32)` at
this block failed with `missing trie node`. No latest-state substitution was
made. A receipt's successful status is not proof of chain finality or venue
market binding.

## Feed semantics still unresolved

The [official BTC/USDT product page](https://data.chain.link/streams/btc-usdt)
identifies a Binance Top-of-Book product but its indexed feed ID is abbreviated.
That abbreviation cannot prove equality with the full candidate ID.
The [public Discovery endpoint documentation](https://docs.chain.link/data-streams/reference/data-streams-api/discovery-endpoint)
allows unauthenticated metadata lookup. The bounded BTC/USDT live-stream GET
returned 403 here; this is an access failure, not proof the feed does not exist.

The [general Top-of-Book guide](https://docs.chain.link/data-streams/concepts/crypto-top-of-book-and-mark-price)
currently describes a v11 perpetual-market schema, while Predict.fun's
[price-market guide](https://docs.predict.fun/developers/chainlink-price-markets)
describes v3 reports. Do not apply the generic v11 schema to this v3 candidate,
or infer spot/perpetual instrument identity from the word Binance. The full
feed metadata and version-specific definition are still needed. In all cases,
order-book reference prices cannot simply be substituted for spot candle trades.

## Offline decoder and limits

`btc5_v3.decision_assistant.round_receipt.decode_candidate_receipt` is a pure
structural parser. It requires an explicit candidate address, successful receipt,
matching log/transaction/block identities, non-removed logs, unique log indices,
canonical integer encoding, and exact known event layouts. It preserves raw
price integers and explicitly lists unclassified log indices. It neither
changes source records nor makes a network request. The original raw receipt
must remain alongside any decoded view.

Every parsed result remains NOT_READY. The parser does not establish inclusion,
finality, asset identity, decimals, token mapping, outcome, native settlement
time, historical feature availability, or predictor validation. It is deliberately
not connected to the live evaluation path or approval registry.

## Remaining blockers and next useful work

1. Obtain fixed official deployment/ABI provenance and verify code identity.
2. Verify full feed ID, source instrument, schema, price units and timestamp rules.
3. Join round/question/condition/token/market using explicit verified relationships,
   including actual authoritative payouts and emergency resolution provenance.
4. Obtain sufficient intracycle historical inputs and their availability semantics;
   endpoint records alone do not establish these features.
5. Validate a predictor on this exact target and untouched validation periods.
6. Bind that predictor to current market quotes, fees, depth and expiry before UI
   selection becomes evaluated. Current Binance-only predictions remain separate.

The public chain route has yielded a usable structural parser and a concrete
negative example for adjacency-based joins, but has not removed these blockers.

## Local verification

- New synthetic parser suite: 23 passed.
- Full regression: 1244 passed, 2 skipped (81.86 seconds).
- Index credential scan: 288 files, zero findings.
- Protected baseline: 95 file hashes unchanged; main and frozen tag unchanged.
- This report and decoder do not claim remote CI success for the new commit;
  the configured Windows/Linux workflow will evaluate it after push.
