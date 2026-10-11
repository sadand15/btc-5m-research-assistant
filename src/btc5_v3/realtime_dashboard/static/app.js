"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = value; };
  const money = value => Number.isFinite(value) ? value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "—";
  const utc = value => Number.isFinite(value) ? new Date(value).toISOString().replace("T", " ").replace("Z", " UTC") : "—";
  const shortTime = value => Number.isFinite(value) ? new Date(value).toISOString().slice(11, 19) : "—";
  const duration = value => Number.isFinite(value) ? `${Math.max(0, value / 1000).toFixed(1)} 秒` : "—";
  const statusNames = {CONNECTING: "连接中", HEALTHY: "正常", DELAYED: "数据延迟", DISCONNECTED: "连接中断", RECOVERING: "连接恢复中"};
  const reasons = {CONNECTING: "等待首个有效行情响应", STARTING: "行情连接正在建立", OK: "行情连接正常", HEALTHY: "行情连接正常", SOURCE_STALE: "源行情已过期，暂停显示实时价格", STALE_QUOTE: "行情已过期，暂停显示实时价格", TIMEOUT: "行情请求超时，正在退避重试", CONNECTION_FAILED: "行情连接失败，正在退避重试", HTTP_ERROR: "行情服务返回异常，正在重试", RATE_LIMITED: "行情源限流，等待后续重试", RECOVERING: "连接已恢复，等待连续有效行情确认"};
  Object.assign(reasons, {WAITING_FOR_FEED: "等待首个有效行情响应", FRESH_TRADE: "行情连接正常，收到新鲜成交报价", STALE_SOURCE: "源行情已过期，暂停显示实时价格", CLOCK_SKEW: "源时间与本机时钟不一致，已拒绝实时报价", CONNECTION_FAILURE: "行情连接失败，正在退避重试", RATE_LIMIT: "行情源限流，等待退避后重试", FEED_RECOVERED: "行情连接已恢复，继续监控新鲜度", OUT_OF_ORDER_QUOTE: "收到时间乱序报价，已拒绝覆盖有效数据", INTERNAL_FEED_ERROR: "行情处理异常，已暂停实时价格"});
  let state = null, stateAt = 0, requestFailed = false, range = 1, chartPoints = [], chartBounds = null, timer = null;
  const now = () => state ? state.server_at + performance.now() - stateAt : Date.now();
  const link = (id, target) => { if (typeof target === "string" && /^\/(reports|docs)\/[a-zA-Z0-9_/-]+$/.test(target)) $(id).href = target; };
  function renderState() {
    $("demo-banner").hidden = state.mode !== "SYNTHETIC_DEMO";
    text("source", state.source || "Binance Spot");
    const health = state.health || {}, quote = state.quote;
    text("source-time", utc(quote && quote.source_at));
    text("received-time", utc(quote && quote.received_at));
    text("success-time", utc(health.last_success_at));
    text("request-ms", Number.isFinite(health.request_ms) ? `${Math.round(health.request_ms)} ms` : "—");
    text("failure-count", `${health.failures || 0} / ${health.recoveries || 0}`);
    text("retry-time", health.failures ? utc(health.next_retry_at) : "无需重试");
    text("latency", quote ? duration(quote.transport_ms) : "—");
    text("last-known", quote ? `最近有效报价 ${money(quote.price)} USDT · 源时间 ${utc(quote.source_at)}` : "尚无最近有效报价");
    const history = state.history || {}, coverage = Number.isFinite(history.coverage) ? Math.min(1, Math.max(0, history.coverage)) : null;
    text("coverage", coverage === null ? "—" : `${(coverage * 100).toFixed(1)}%`);
    $("coverage-bar").style.width = `${(coverage || 0) * 100}%`;
    for (const id of ["observed", "missing", "expected"]) text(id, Number.isFinite(history[id]) ? history[id].toLocaleString("en-US") : "—");
    text("quality-message", history.status === "ERROR" ? "历史行情请求失败。现存记录仅供历史查看，不能代表实时价格；系统将自动重试。" : history.status === "LOADING" ? "正在加载已收盘分钟 K 线；尚不能判断覆盖情况。" : `${history.missing || 0} 个分钟区间缺失。图表保留缺口，不插值；覆盖率不代表真实市场目标已通过验证。`);
    text("history-badge", {READY: "历史数据完整", PARTIAL: "存在缺失", ERROR: "历史请求异常", LOADING: "加载中"}[history.status] || "待核验");
    text("history-asof", history.as_of ? `更新于 ${utc(history.as_of)}` : "尚未取得历史数据");
    const events = $("events"); events.replaceChildren();
    (state.events || []).slice(0, 2).forEach(event => { const el = document.createElement("div"); el.textContent = `${shortTime(event.at)} UTC · ${statusNames[event.status] || "状态变化"} · ${reasons[event.reason] || "连接状态已更新"}`; events.append(el); });
    if (state.reports) { link("m92-link", state.reports.m92); link("m102-link", state.reports.m102); link("methods-link", state.reports.methods); }
    renderClock(); drawChart();
  }
  function renderClock() {
    const at = now(); text("clock", utc(at).replace(/\.\d{3} UTC$/, " UTC"));
    if (!state) return;
    const quote = state.quote, elapsed = Math.max(0, performance.now() - stateAt);
    const age = quote ? Math.max(quote.source_age_ms + elapsed, at - quote.source_at) : null;
    const receiptAge = quote ? Math.max(quote.receipt_age_ms + elapsed, at - quote.received_at) : null;
    let status = state.health.status;
    if (requestFailed) status = "DISCONNECTED";
    else if (status !== "DISCONNECTED" && quote && (!Number.isFinite(age) || !Number.isFinite(receiptAge) || age > state.stale_after_ms || receiptAge > state.stale_after_ms)) status = "DELAYED";
    const live = !requestFailed && ["HEALTHY", "RECOVERING"].includes(status) && Number.isFinite(state.live_price) && Number.isFinite(age) && Number.isFinite(receiptAge) && age <= state.stale_after_ms && receiptAge <= state.stale_after_ms;
    const prediction=state.binance_direction;
    $("direction-card").hidden=!prediction;
    if(prediction){
      const fresh=live && Number.isFinite(prediction.source_at) && at>=prediction.source_at && at-prediction.source_at<=10000 && at<prediction.cycle_end;
      const tteOk=prediction.cycle_end-at>=30000 && prediction.cycle_end-at<=180000;
      text("direction-signal",fresh&&tteOk?prediction.signal:"WAIT");
      text("direction-probability",fresh&&Number.isFinite(prediction.p_up)?`上涨 ${(100*prediction.p_up).toFixed(1)}% · 下跌或持平 ${(100*prediction.p_non_up).toFixed(1)}%`:"暂无有效概率");
      const explanations={WARMUP:"模型预热中",MODEL_UNAVAILABLE:"尚未加载模型",MODEL_LOAD_FAILED:"模型或运行依赖不可用",MODEL_HASH_MISMATCH:"模型文件校验失败",PUBLIC_FEED_NOT_HEALTHY:"公开行情连接未就绪",OUTSIDE_TRAINED_TIME_SUPPORT:"不在模型训练支持的采样时刻",OUTSIDE_RESEARCH_TTE:"仅在剩余 30–180 秒显示方向信号",PROBABILITY_BELOW_DISPLAY_THRESHOLD:"两侧概率均未达到固定 70% 展示门槛",UP_PROBABILITY_AT_LEAST_70_PERCENT:"模型更倾向本周期上涨",NON_UP_PROBABILITY_AT_LEAST_70_PERCENT:"模型更倾向本周期下跌或持平",CONNECTION_FAILURE:"预测数据连接失败，正在重试",MODEL_INPUT_OR_INFERENCE_FAILURE:"预测输入不完整或推理失败",PREDICTION_STALE_OR_CYCLE_CHANGED:"预测过期或周期已切换"};
      const reason=!live?"PUBLIC_FEED_NOT_HEALTHY":!fresh?(Number.isFinite(prediction.source_at)?"PREDICTION_STALE_OR_CYCLE_CHANGED":prediction.reason):!tteOk?"OUTSIDE_RESEARCH_TTE":prediction.reason;
      text("direction-reason",explanations[reason]||reason);
      text("direction-time",`预测 ${utc(prediction.generated_at)} · 输入 ${utc(prediction.source_at)} · 结束 ${utc(prediction.cycle_end)}`);
      document.querySelector('.research-card h3').textContent="Binance 目标已绑定";
      document.querySelector('.research-card p').textContent="当前方向来自冻结 Binance BTCUSDT 五分钟模型；实时可靠性仍需前瞻验证。";
      document.querySelector('.research-card .tag').textContent="实验预测";
      document.querySelector('.contract-status').textContent="BINANCE_TARGET_MATCH · EXPERIMENTAL_PREDICTION";
    }
    text("health-badge", statusNames[status] || "待核验"); $("health-badge").className = `status ${status.toLowerCase()}`;
    text("live-price", live ? money(state.live_price) : "—"); text("age", duration(age));
    text("price-caption", live ? (state.mode === "SYNTHETIC_DEMO" ? "合成样例价格 · 非真实行情" : "当前公开成交报价 · 自动刷新") : "实时价格暂不可用；最近有效报价单独保留，不作为实时价格。");
    text("health-message", requestFailed ? "本地服务连接中断，自动重试中；已撤下实时价格。" : status === "DELAYED" ? "数据年龄超出有效范围，已撤下实时价格。" : reasons[state.health.reason] || (status === "HEALTHY" ? "行情连接正常，持续检查源时间与接收时间。" : statusNames[status] || "状态待核验"));
    const start = Math.floor(at / 300000) * 300000, end = start + 300000, seconds = Math.max(0, Math.ceil((end - at) / 1000));
    text("countdown", `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`);
    text("cycle-start", utc(start).replace(".000 UTC", "")); text("cycle-end", utc(end).replace(".000 UTC", ""));
    $("cycle-progress").style.width = `${Math.min(100, (at - start) / 3000)}%`;
    const cycle = state.cycle || {}, bound = cycle.start_at === start && cycle.end_at === end;
    text("reference-price", bound ? money(cycle.reference_price) : "—");
    text("reference-time", bound && Number.isFinite(cycle.reference_price) ? `参考时刻 ${utc(cycle.reference_at)} · 接收 ${utc(cycle.reference_received_at)}` : "等待当前周期第一笔成交的开盘参考价，未用旧周期回填。");
  }
  const svgNode = (name, attributes, label) => { const node = document.createElementNS("http://www.w3.org/2000/svg", name); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value); if (label !== undefined) node.textContent = label; return node; };
  function drawChart() {
    const svg = $("chart-svg"); svg.replaceChildren(); $("chart-tooltip").hidden = true;
    const end = now(), start = end - range * 3600000;
    chartPoints = ((state && state.history && state.history.points) || []).filter(p => Number.isFinite(p.at) && Number.isFinite(p.price) && p.at >= start && p.at <= end).sort((a, b) => a.at - b.at);
    const w = 900, h = 300, left = 3, right = 78, top = 14, bottom = 32, pw = w - right - left, ph = h - top - bottom;
    $("chart-empty").hidden = chartPoints.length > 0;
    text("chart-empty", state && state.history.status === "ERROR" ? "历史行情暂不可用，正在自动重试" : "此时间范围暂无有效历史行情");
    text("chart-last", chartPoints.length ? `${money(chartPoints[chartPoints.length - 1].price)}` : "—");
    text("chart-range", `${range === 1 ? "最近 1 小时" : "最近 24 小时"} · ${chartPoints.length} 个分钟收盘点`);
    if (!chartPoints.length) { chartBounds = null; return; }
    let low = Math.min(...chartPoints.map(p => p.price)), high = Math.max(...chartPoints.map(p => p.price));
    const padding = Math.max((high - low) * .15, high * .00005, .01); low -= padding; high += padding;
    const x = at => left + (at - start) / (end - start) * pw, y = price => top + (high - price) / (high - low) * ph;
    chartBounds = {start, end, left, pw, w, x, y};
    for (let i = 0; i <= 4; i++) { const yy = top + ph * i / 4; svg.append(svgNode("line", {x1: left, x2: w - right, y1: yy, y2: yy, stroke: "#e9edf2", "stroke-dasharray": "3 5"})); svg.append(svgNode("text", {x: w - right + 10, y: yy + 4, fill: "#8b99a8", "font-size": 11, "font-family": "Segoe UI, sans-serif"}, money(high - (high - low) * i / 4))); }
    for (let i = 0; i <= 4; i++) { const at = start + (end - start) * i / 4; svg.append(svgNode("text", {x: x(at), y: h - 7, fill: "#8b99a8", "font-size": 11, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle", "font-family": "Segoe UI, sans-serif"}, new Date(at).toISOString().slice(11, 16))); }
    let path = "", last = null;
    chartPoints.forEach(point => { path += `${last !== null && point.at - last <= 61000 && point.at > last ? "L" : "M"}${x(point.at).toFixed(2)},${y(point.price).toFixed(2)} `; last = point.at; });
    svg.append(svgNode("path", {d: path.trim(), fill: "none", stroke: "#497b9c", "stroke-width": 2.25, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke"}));
    chartPoints.forEach((point, i) => {
      const before = chartPoints[i - 1], after = chartPoints[i + 1];
      if ((!before || point.at - before.at > 61000) && (!after || after.at - point.at > 61000)) svg.append(svgNode("circle", {cx: x(point.at), cy: y(point.price), r: 2.5, fill: "#497b9c"}));
    });
    const latest = chartPoints[chartPoints.length - 1]; svg.append(svgNode("circle", {cx: x(latest.at), cy: y(latest.price), r: 3.5, fill: "#497b9c", stroke: "white", "stroke-width": 2}));
  }
  $("chart").addEventListener("pointermove", event => {
    if (!chartBounds || !chartPoints.length) return;
    const rect = $("chart").getBoundingClientRect(), px = event.clientX - rect.left, target = chartBounds.start + (px / rect.width * chartBounds.w - chartBounds.left) / chartBounds.pw * (chartBounds.end - chartBounds.start);
    const point = chartPoints.reduce((a, b) => Math.abs(b.at - target) < Math.abs(a.at - target) ? b : a);
    const tip = $("chart-tooltip"); tip.textContent = `${money(point.price)} USDT\n${utc(point.at)}\n实际分钟收盘点（非插值）`; tip.hidden = false; tip.style.left = `${Math.max(0, Math.min(rect.width - 225, px + 12))}px`; tip.style.top = `${Math.max(0, Math.min(rect.height - 85, event.clientY - rect.top - 75))}px`;
  });
  $("chart").addEventListener("pointerleave", () => { $("chart-tooltip").hidden = true; });
  document.querySelectorAll("[data-range]").forEach(button => button.addEventListener("click", () => { range = Number(button.dataset.range); document.querySelectorAll("[data-range]").forEach(item => { const selected = item === button; item.classList.toggle("selected", selected); item.setAttribute("aria-pressed", String(selected)); }); drawChart(); }));
  let failures = 0, inFlight = false;
  async function poll() {
    if (inFlight) return;
    inFlight = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch("/api/state", {signal: controller.signal, cache: "no-store", credentials: "omit"});
      if (!response.ok) throw new Error("HTTP_STATE_UNAVAILABLE");
      const data = await response.json();
      const finite = Number.isFinite;
      if (!data || !finite(data.server_at) || !data.health || !Object.hasOwn(statusNames, data.health.status) || !["PUBLIC_LIVE", "SYNTHETIC_DEMO"].includes(data.mode) || !data.history || !Array.isArray(data.history.points) || !["READY", "PARTIAL", "ERROR", "LOADING"].includes(data.history.status) || !data.cycle || !finite(data.cycle.start_at) || !finite(data.cycle.end_at) || data.cycle.end_at - data.cycle.start_at !== 300000 || !finite(data.stale_after_ms) || data.stale_after_ms <= 0 || data.stale_after_ms > 15000 || !Array.isArray(data.events)) throw new Error("INVALID_STATE");
      if (state && data.server_at < now() - 2000) throw new Error("REPLAYED_OR_ROLLBACK_STATE");
      if (data.quote !== null && (!data.quote || ![data.quote.price, data.quote.source_at, data.quote.received_at, data.quote.source_age_ms, data.quote.receipt_age_ms, data.quote.transport_ms].every(finite) || data.quote.price <= 0)) throw new Error("INVALID_QUOTE");
      if (data.live_price !== null && (!finite(data.live_price) || !data.quote || data.live_price !== data.quote.price)) throw new Error("INVALID_LIVE_PRICE");
      state = data; stateAt = performance.now(); requestFailed = false; failures = 0; renderState();
    } catch (_) {
      requestFailed = true; failures += 1;
      text("live-price", "—"); text("health-badge", "连接中断"); $("health-badge").className = "status disconnected";
      text("health-message", "本地服务连接中断，正在退避重试；不显示过期价格。");
      text("price-caption", "无法确认实时行情。检查本地 Dashboard 服务与网络连接。");
      if (state) renderClock();
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      const delay = Math.min(30000, 2000 * Math.pow(2, Math.min(failures, 4)));
      text("poll-label", failures ? `${delay / 1000} 秒后重试` : "每 2 秒检查");
      timer = setTimeout(poll, delay);
    }
  }
  window.addEventListener("pagehide", () => clearTimeout(timer));
  window.addEventListener("pageshow", event => { if (event.persisted) { clearTimeout(timer); poll(); } });
  setInterval(renderClock, 250); poll();
})();
