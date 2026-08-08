/**
 * 星云节点可视化引擎 —— Canvas 2D 实现
 * 特性：节点漂浮 + 距离自动连线 + 滚轮缩放 + 拖拽平移 + 点击详情
 */
"use strict";

// ===== 家族颜色配置（浅色系，适配白底） =====
const FAMILY_COLORS = {
  "财务审计": "#6366f1",
  "合规审计": "#0ea5e9",
  "IPO审计": "#8b5cf6",
  "持续审计": "#14b8a6",
  "舞弊审计": "#ef4444",
  "IT审计": "#64748b",
  "税务审计": "#f59e0b",
  "供应链审计": "#22c55e",
  "ESG审计": "#10b981",
  "金融审计": "#3b82f6",
  "内部审计": "#ec4899",
  "跨境审计": "#a855f7",
  "通用审计": "#78716c",
};

// ===== 全局状态 =====
let canvas, ctx;
let auditData = null;
let nodes = [];          // {slug, name, family, status, x, y, vx, vy, radius, baseX, baseY, phase}
let edges = [];          // {from, to} DAG 边
let edgeSet = new Set(); // 快速查找
let selectedNode = null;
let hoveredNode = null;

// 视图变换
let viewX = 0, viewY = 0, viewScale = 1;
let isDragging = false;
let dragStartX = 0, dragStartY = 0;
let viewStartX = 0, viewStartY = 0;
let hasDragged = false;

// 动画
let animTime = 0;

// ===== 初始化 =====
async function init() {
  canvas = document.getElementById("galaxy-canvas");
  ctx = canvas.getContext("2d");

  resizeCanvas();
  window.addEventListener("resize", resizeCanvas);

  // 加载数据（二级兜底：API 接口失败 → 静态 JSON 文件 → 友好提示）
  try {
    const resp = await fetch("/api/audit_data");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    auditData = await resp.json();
  } catch (e) {
    // 回退：直接加载 web/ 目录下同步过来的静态 audit_data.json
    try {
      const resp2 = await fetch("audit_data.json");
      if (!resp2.ok) throw new Error("HTTP " + resp2.status);
      auditData = await resp2.json();
    } catch (e2) {
      const hint = document.getElementById("canvas-hint");
      const detail = (e2 && e2.message) ? e2.message : String(e2);
      hint.style.cssText = "color:#ef4444;font-size:14px;padding:24px;text-align:center;line-height:2;";
      hint.innerHTML =
        "<b>❌ 数据加载失败</b><br>" +
        "错误详情：" + escapeHtml(detail) + "<br><br>" +
        "✅ 请使用以下命令启动平台（不要用 python -m http.server）：<br>" +
        "<code style='background:#1e293b;color:#e2e8f0;padding:4px 8px;border-radius:4px;'>python launch.py</code>";
      return;
    }
  }

  buildNodes();
  buildEdges();
  setupInteraction();
  setupButtons();
  renderSidebar();
  renderLegend();
  animate();
}

// 记录上次布局尺寸，用于检测 resize 是否需要重排节点
let lastLayoutW = 0, lastLayoutH = 0;

function resizeCanvas() {
  const wrapper = document.getElementById("canvas-wrapper");
  const dpr = window.devicePixelRatio || 1;
  // 兜底：DOM 未完成布局时 wrapper.clientWidth 可能为 0，
  // 此时用 window 尺寸兜底，避免 canvas 被设成 0×0 导致节点全堆在原点
  let w = wrapper.clientWidth;
  let h = wrapper.clientHeight;
  if (w < 50) w = Math.max(300, window.innerWidth - 360);
  if (h < 50) h = Math.max(300, window.innerHeight - 120);
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // 尺寸显著变化时重新布局节点（解决 init 时尺寸为 0 的问题）
  if (nodes.length > 0 && (Math.abs(w - lastLayoutW) > 20 || Math.abs(h - lastLayoutH) > 20)) {
    layoutNodes(w, h);
    lastLayoutW = w;
    lastLayoutH = h;
  }
}

// ===== 构建节点（首次：创建节点对象 + 布局） =====
function buildNodes() {
  const modules = auditData.plan.modules;
  modules.forEach((m) => {
    nodes.push({
      slug: m.slug,
      name: m.name,
      family: m.family || "通用审计",
      status: m.status,
      duration: m.duration,
      error: m.error,
      inputs: m.inputs || [],
      outputs: m.outputs || [],
      x: 0, y: 0, baseX: 0, baseY: 0, vx: 0, vy: 0,
      radius: 26,
      phase: Math.random() * Math.PI * 2,
      driftSpeed: 0.3 + Math.random() * 0.4,
      driftAmp: 8 + Math.random() * 12,
    });
  });
  // 用当前 canvas 尺寸布局
  const w = canvas.clientWidth || (window.innerWidth - 360);
  const h = canvas.clientHeight || (window.innerHeight - 120);
  layoutNodes(w, h);
  lastLayoutW = w;
  lastLayoutH = h;
}

// ===== 节点布局：环形分布 + 家族聚拢（可重复调用，resize 时重排） =====
function layoutNodes(w, h) {
  if (nodes.length === 0) return;
  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.max(80, Math.min(cx, cy) * 0.6);
  const n = nodes.length;
  // 先按拓扑顺序环形分布
  nodes.forEach((node, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    const r = radius * (0.7 + ((node.phase % 1) * 0.3));
    node.baseX = cx + Math.cos(angle) * r;
    node.baseY = cy + Math.sin(angle) * r;
  });
  // 按家族轻微聚拢
  const familyGroups = {};
  nodes.forEach(node => {
    if (!familyGroups[node.family]) familyGroups[node.family] = [];
    familyGroups[node.family].push(node);
  });
  const families = Object.keys(familyGroups);
  families.forEach((fam, fi) => {
    const groupAngle = (fi / families.length) * Math.PI * 2;
    const groupCx = cx + Math.cos(groupAngle) * radius * 0.3;
    const groupCy = cy + Math.sin(groupAngle) * radius * 0.3;
    familyGroups[fam].forEach(node => {
      node.baseX = node.baseX * 0.6 + groupCx * 0.4;
      node.baseY = node.baseY * 0.6 + groupCy * 0.4;
      node.x = node.baseX;
      node.y = node.baseY;
    });
  });
}

// ===== 构建边 =====
function buildEdges() {
  edges = (auditData.plan.edges || []).map(([from, to]) => ({ from, to }));
  edgeSet = new Set(edges.map(e => e.from + "|" + e.to));
}

// ===== 交互 =====
function setupInteraction() {
  // 滚轮缩放
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const oldScale = viewScale;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    viewScale = Math.max(0.3, Math.min(3, viewScale * delta));
    // 以鼠标为中心缩放
    const ratio = viewScale / oldScale;
    viewX = mx - (mx - viewX) * ratio;
    viewY = my - (my - viewY) * ratio;
  }, { passive: false });

  // 拖拽平移
  canvas.addEventListener("mousedown", (e) => {
    isDragging = true;
    hasDragged = false;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    viewStartX = viewX;
    viewStartY = viewY;
  });

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    if (isDragging) {
      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasDragged = true;
      viewX = viewStartX + dx;
      viewY = viewStartY + dy;
    } else {
      // 悬停检测
      hoveredNode = findNodeAt(mx, my);
      canvas.style.cursor = hoveredNode ? "pointer" : "grab";
    }
  });

  canvas.addEventListener("mouseup", (e) => {
    if (isDragging && !hasDragged) {
      // 点击节点
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = findNodeAt(mx, my);
      if (node) {
        selectedNode = node;
        renderModuleDetail(node);
      } else {
        selectedNode = null;
        document.getElementById("panel-detail").style.display = "none";
      }
    }
    isDragging = false;
  });

  canvas.addEventListener("mouseleave", () => {
    isDragging = false;
    hoveredNode = null;
  });
}

function setupButtons() {
  document.getElementById("btn-zoom-in").onclick = () => {
    viewScale = Math.min(3, viewScale * 1.2);
  };
  document.getElementById("btn-zoom-out").onclick = () => {
    viewScale = Math.max(0.3, viewScale * 0.83);
  };
  document.getElementById("btn-reset").onclick = () => {
    viewX = 0; viewY = 0; viewScale = 1;
    selectedNode = null;
    document.getElementById("panel-detail").style.display = "none";
  };
}

// 屏幕坐标 → 世界坐标
function screenToWorld(sx, sy) {
  return {
    x: (sx - viewX) / viewScale,
    y: (sy - viewY) / viewScale,
  };
}

function findNodeAt(sx, sy) {
  const w = screenToWorld(sx, sy);
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const dx = w.x - n.x;
    const dy = w.y - n.y;
    if (dx * dx + dy * dy < (n.radius + 4) * (n.radius + 4)) {
      return n;
    }
  }
  return null;
}

// ===== 动画循环 =====
function animate() {
  animTime += 0.016;

  // 更新节点漂浮位置
  nodes.forEach(n => {
    // 正弦漂浮
    const targetX = n.baseX + Math.sin(animTime * n.driftSpeed + n.phase) * n.driftAmp;
    const targetY = n.baseY + Math.cos(animTime * n.driftSpeed * 0.8 + n.phase) * n.driftAmp;
    // 缓动靠近目标
    n.x += (targetX - n.x) * 0.05;
    n.y += (targetY - n.y) * 0.05;
  });

  draw();
  requestAnimationFrame(animate);
}

// ===== 绘制 =====
function draw() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);

  // 背景轻微网格点（星云感）
  drawStarfield(w, h);

  ctx.save();
  ctx.translate(viewX, viewY);
  ctx.scale(viewScale, viewScale);

  // 1. 距离连线（淡）
  drawProximityEdges();

  // 2. DAG 边（实）
  drawDagEdges();

  // 3. 节点
  nodes.forEach(n => drawNode(n));

  ctx.restore();
}

function drawStarfield(w, h) {
  ctx.save();
  ctx.fillStyle = "rgba(99,102,241,0.04)";
  const step = 40;
  for (let x = 0; x < w; x += step) {
    for (let y = 0; y < h; y += step) {
      const tw = 0.5 + 0.5 * Math.sin(animTime * 0.5 + x * 0.01 + y * 0.01);
      ctx.globalAlpha = 0.06 * tw;
      ctx.beginPath();
      ctx.arc(x, y, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawProximityEdges() {
  const threshold = 220;
  ctx.save();
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = a.x - b.x, dy = a.y - b.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < threshold) {
        // 跳过已是 DAG 边的
        const key = a.slug + "|" + b.slug;
        const key2 = b.slug + "|" + a.slug;
        if (edgeSet.has(key) || edgeSet.has(key2)) continue;
        const alpha = (1 - dist / threshold) * 0.12;
        ctx.strokeStyle = `rgba(99,102,241,${alpha})`;
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }
  }
  ctx.restore();
}

function drawDagEdges() {
  ctx.save();
  edges.forEach(e => {
    const from = nodes.find(n => n.slug === e.from);
    const to = nodes.find(n => n.slug === e.to);
    if (!from || !to) return;

    const isHighlight = selectedNode &&
      (selectedNode.slug === e.from || selectedNode.slug === e.to);

    // 贝塞尔曲线
    const mx = (from.x + to.x) / 2;
    const my = (from.y + to.y) / 2;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const perpX = -dy * 0.15;
    const perpY = dx * 0.15;

    ctx.strokeStyle = isHighlight ? "rgba(79,70,229,0.8)" : "rgba(107,114,128,0.35)";
    ctx.lineWidth = isHighlight ? 2 : 1.2;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.quadraticCurveTo(mx + perpX, my + perpY, to.x, to.y);
    ctx.stroke();

    // 箭头
    const angle = Math.atan2(to.y - (my + perpY), to.x - (mx + perpX));
    const arrowSize = 7;
    ctx.fillStyle = isHighlight ? "rgba(79,70,229,0.8)" : "rgba(107,114,128,0.4)";
    ctx.beginPath();
    ctx.moveTo(to.x, to.y);
    ctx.lineTo(to.x - arrowSize * Math.cos(angle - 0.4), to.y - arrowSize * Math.sin(angle - 0.4));
    ctx.lineTo(to.x - arrowSize * Math.cos(angle + 0.4), to.y - arrowSize * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fill();
  });
  ctx.restore();
}

function drawNode(n) {
  const color = FAMILY_COLORS[n.family] || "#78716c";
  const isSelected = selectedNode && selectedNode.slug === n.slug;
  const isHovered = hoveredNode && hoveredNode.slug === n.slug;
  const isUpstream = selectedNode && selectedNode.inputs.includes(n.slug);
  const isDownstream = selectedNode && selectedNode.outputs.includes(n.slug);

  ctx.save();

  // 光晕
  if (isSelected || isHovered) {
    const glowR = n.radius + 12;
    const grad = ctx.createRadialGradient(n.x, n.y, n.radius, n.x, n.y, glowR);
    grad.addColorStop(0, color + "30");
    grad.addColorStop(1, color + "00");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(n.x, n.y, glowR, 0, Math.PI * 2);
    ctx.fill();
  }

  // 外环
  ctx.strokeStyle = color;
  ctx.lineWidth = isUpstream || isDownstream ? 3 : (isSelected ? 2.5 : 1.5);
  ctx.globalAlpha = (isUpstream || isDownstream) ? 1 : 0.7;
  ctx.beginPath();
  ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
  ctx.stroke();

  // 内圆
  ctx.globalAlpha = 1;
  ctx.fillStyle = n.status === "done" ? "#ffffff" : "#fef2f2";
  ctx.beginPath();
  ctx.arc(n.x, n.y, n.radius - 3, 0, Math.PI * 2);
  ctx.fill();

  // 状态指示
  const statusColor = n.status === "done" ? "#10b981" : "#ef4444";
  ctx.fillStyle = statusColor;
  ctx.beginPath();
  ctx.arc(n.x + n.radius * 0.6, n.y - n.radius * 0.6, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // 文字
  ctx.fillStyle = "#1a1d29";
  ctx.font = "600 11px 'Segoe UI','Microsoft YaHei',sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  // slug
  ctx.fillText(n.slug, n.x, n.y - 5);
  // 名称（截断）
  ctx.font = "400 10px 'Segoe UI','Microsoft YaHei',sans-serif";
  ctx.fillStyle = "#6b7280";
  const shortName = n.name.length > 8 ? n.name.slice(0, 7) + "…" : n.name;
  ctx.fillText(shortName, n.x, n.y + 8);

  ctx.restore();
}

// ===== 侧边栏渲染 =====
function renderSidebar() {
  // 统计
  const modules = auditData.plan.modules;
  const findings = auditData.findings || [];
  const success = modules.filter(m => m.status === "done").length;
  const highCount = findings.filter(f => f.severity === "高").length;

  document.getElementById("stat-modules").textContent = modules.length;
  document.getElementById("stat-success").textContent = success;
  document.getElementById("stat-findings").textContent = findings.length;
  document.getElementById("stat-high").textContent = highCount;
  document.getElementById("stat-duration").textContent = auditData.total_duration || 0;

  // 需求
  document.getElementById("req-text").textContent = auditData.requirement || "--";

  // 发现列表
  renderFindings(findings);

  // 日志
  const logEl = document.getElementById("log-content");
  const logs = auditData.execution_log || [];
  logEl.innerHTML = logs.map(l => `<div class="log-line">${escapeHtml(l)}</div>`).join("");
}

// ===== AI 总结缓存（前端层，避免重复调用 API） =====
const aiSummaryCache = new Map();  // key -> summary text

function renderFindings(findings) {
  const list = document.getElementById("findings-list");
  document.getElementById("findings-count").textContent = findings.length;

  if (findings.length === 0) {
    list.innerHTML = '<div class="finding-empty">无审计发现</div>';
    return;
  }

  // ===== 第一层：按来源模块分组 =====
  const byModule = {};
  findings.forEach(f => {
    const src = f.source || "unknown";
    if (!byModule[src]) byModule[src] = [];
    byModule[src].push(f);
  });

  // 模块排序：按发现数降序
  const moduleSlugs = Object.keys(byModule).sort((a, b) => byModule[b].length - byModule[a].length);

  const SEV_ORDER = { "高": 0, "中": 1, "低": 2 };
  const SEV_LABEL = { "高": "高风险", "中": "中风险", "低": "低风险" };

  let html = "";
  moduleSlugs.forEach((slug, mi) => {
    const modFindings = byModule[slug];
    const modName = getModuleName(slug);
    // 统计严重度分布
    const sevDist = { "高": 0, "中": 0, "低": 0 };
    modFindings.forEach(f => { sevDist[f.severity] = (sevDist[f.severity] || 0) + 1; });

    // 第一层头：模块
    html += `<div class="finding-group-module">`;
    html += `<div class="finding-group-header" onclick="toggleFindGroup(this)">`;
    html += `<span class="toggle-arrow">▶</span>`;
    html += `<span class="module-slug">${slug}</span>`;
    html += `<span class="module-name">${escapeHtml(modName)}</span>`;
    // 严重度迷你标签
    if (sevDist["高"] > 0) html += `<span class="mini-sev mini-high">高${sevDist["高"]}</span>`;
    if (sevDist["中"] > 0) html += `<span class="mini-sev mini-mid">中${sevDist["中"]}</span>`;
    if (sevDist["低"] > 0) html += `<span class="mini-sev mini-low">低${sevDist["低"]}</span>`;
    html += `<span class="module-count">${modFindings.length} 条</span>`;
    html += `</div>`;

    // 第一层体
    html += `<div class="finding-group-body">`;

    // ===== 第二层：按严重等级分组 =====
    const sevs = ["高", "中", "低"].filter(s => sevDist[s] > 0);
    sevs.forEach(sev => {
      const sevFindings = modFindings.filter(f => f.severity === sev)
        .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]);

      html += `<div class="finding-subgroup">`;
      html += `<div class="finding-subgroup-header" onclick="toggleFindGroup(this)">`;
      html += `<span class="toggle-arrow">▶</span>`;
      html += `<span class="sev-label sev-${sev === '高' ? 'high' : (sev === '中' ? 'mid' : 'low')}">● ${SEV_LABEL[sev]}</span>`;
      html += `<span class="sev-count">${sevFindings.length} 条</span>`;
      html += `</div>`;

      // 第二层体
      html += `<div class="finding-subgroup-body">`;

      // ===== 第三层：具体发现条目 =====
      sevFindings.forEach((f, fi) => {
        const sevTagClass = `sev-tag-${sev === '高' ? 'high' : (sev === '中' ? 'mid' : 'low')}`;
        const amount = extractAmount(f.detail);
        // 生成该发现的唯一ID，供AI总结缓存使用
        const findingUid = btoa(unescape(encodeURIComponent(slug + "|" + (f.title || "") + "|" + (f.detail || "")))).slice(0, 24);

        html += `<div class="finding-item">`;
        html += `<div class="finding-item-header" onclick="toggleFindGroup(this)">`;
        html += `<span class="toggle-arrow">▶</span>`;
        html += `<span class="${sevTagClass}">${sev}</span>`;
        html += `<span class="finding-title">${escapeHtml(f.title)}</span>`;
        if (amount) html += `<span class="finding-amount">${amount}</span>`;
        html += `</div>`;

        // 第三层详情
        html += `<div class="finding-item-detail">`;
        html += `<div class="detail-field"><span class="detail-field-label">来源</span><span class="detail-field-value">${f.source}</span></div>`;
        html += `<div class="detail-field"><span class="detail-field-label">等级</span><span class="detail-field-value">${sev}</span></div>`;
        html += `<div class="detail-field"><span class="detail-field-label">标题</span><span class="detail-field-value">${escapeHtml(f.title)}</span></div>`;
        html += `<div class="detail-field"><span class="detail-field-label">详情</span><span class="detail-field-value">${escapeHtml(f.detail || "（无详情）")}</span></div>`;
        html += `<div class="detail-field"><span class="detail-field-label">操作</span><span class="detail-field-value"><a href="#" onclick="focusNode('${f.source}');return false;" style="color:#4f46e5;text-decoration:none;">定位到模块节点 →</a></span></div>`;

        // ===== 第四层：数据集分组 =====
        const sourceRecords = f.source_records || {};
        const datasets = f.datasets || Object.keys(sourceRecords);

        if (datasets.length === 0 || Object.keys(sourceRecords).length === 0) {
          html += `<div class="dataset-empty">📁 未匹配到具体原始数据条目（该发现暂无溯源数据可用）</div>`;
        } else {
          datasets.forEach((dsName, di) => {
            const records = sourceRecords[dsName] || [];
            // 数据格式颜色：jsonl=青色
            const ext = (dsName.split(".").pop() || "jsonl").toLowerCase();
            const fmtClass = ext === "jsonl" ? "fmt-jsonl" : (ext === "parquet" ? "fmt-parquet" : "fmt-json");

            html += `<div class="dataset-group">`;
            html += `<div class="dataset-group-header" onclick="toggleFindGroup(this)">`;
            html += `<span class="toggle-arrow">▶</span>`;
            html += `<span class="dataset-icon"><span class="fmt-dot ${fmtClass}"></span></span>`;
            html += `<span class="dataset-name">${escapeHtml(dsName)}</span>`;
            html += `<span class="dataset-count">${records.length} 条</span>`;
            html += `</div>`;

            // 第四层体
            html += `<div class="dataset-group-body">`;

            if (records.length === 0) {
              html += `<div class="dataset-empty">该数据集暂无匹配记录</div>`;
            } else {
              // ===== 第五层：原始数据记录 + AI 总结 =====
              // AI总结放在数据集顶部（所有记录的综合分析）
              html += `<div id="ai-block-${findingUid}-${di}" class="ai-summary-block" style="margin-bottom:6px;">`;
              html += `<div class="ai-summary-header">`;
              html += `<div class="ai-icon">AI</div>`;
              html += `<div class="ai-label">智能审计分析</div>`;
              html += `<div class="ai-status" id="ai-status-${findingUid}-${di}">点击展开记录</div>`;
              html += `</div>`;
              html += `<div id="ai-body-${findingUid}-${di}" style="display:none;"></div>`;
              html += `</div>`;

              records.forEach((rec, ri) => {
                const ref = rec._ref || {};
                const rowNum = (typeof ref.row === "number" && ref.row >= 0) ? ref.row + 1 : "?";
                const preview = formatRecordPreview(rec);

                html += `<div class="raw-record">`;
                html += `<div class="raw-record-header" onclick="toggleRawRecord(this, '${findingUid}', ${di})">`;
                html += `<span class="record-idx">#${ri + 1}</span>`;
                html += `<span class="record-preview">${escapeHtml(preview)}</span>`;
                html += `<span class="record-row-tag">行 ${rowNum}</span>`;
                html += `</div>`;

                // 第五层体：字段详情
                html += `<div class="raw-record-body">`;
                html += renderRecordFields(rec);
                html += `</div>`;

                html += `</div>`; // raw-record
              });
            }

            html += `</div>`; // dataset-group-body
            html += `</div>`; // dataset-group
          });
        }

        html += `</div>`; // finding-item-detail
        html += `</div>`; // finding-item
      });

      html += `</div>`; // subgroup-body
      html += `</div>`; // subgroup
    });

    html += `</div>`; // group-body
    html += `</div>`; // group-module
  });

  list.innerHTML = html;
}

// ===== 折叠/展开通用函数（支持新的 dataset-group-body / raw-record-body） =====
function toggleFindGroup(headerEl) {
  const arrow = headerEl.querySelector(".toggle-arrow");
  // 找到紧邻的兄弟 body 元素
  let body = headerEl.nextElementSibling;
  let guard = 0;
  while (body && !body.classList.contains("finding-group-body")
         && !body.classList.contains("finding-subgroup-body")
         && !body.classList.contains("finding-item-detail")
         && !body.classList.contains("dataset-group-body")) {
    body = body.nextElementSibling;
    if (guard++ > 20) break;
  }
  if (!body) return;
  const isOpen = body.classList.toggle("open");
  if (arrow) arrow.classList.toggle("open", isOpen);
}

// ===== 原始记录展开：展开字段详情 + 异步触发 AI 总结 =====
function toggleRawRecord(headerEl, findingUid, datasetIdx) {
  const arrow = headerEl.querySelector(".toggle-arrow");
  let body = headerEl.nextElementSibling;
  if (!body || !body.classList.contains("raw-record-body")) return;
  const isOpen = body.classList.toggle("open");
  // 如果打开了任何一条记录，触发该数据集的AI总结（只触发一次）
  if (isOpen) {
    ensureAiSummaryLoaded(findingUid, datasetIdx);
  }
}

// ===== 生成记录预览文本（取前3个非内部字段） =====
function formatRecordPreview(rec) {
  if (!rec || typeof rec !== "object") return "";
  const keys = Object.keys(rec).filter(k => k !== "_ref");
  const parts = [];
  for (let i = 0; i < Math.min(3, keys.length); i++) {
    const k = keys[i];
    let v = rec[k];
    if (v === null || v === undefined) v = "";
    if (typeof v === "object") v = JSON.stringify(v);
    const vs = String(v).length > 20 ? String(v).slice(0, 20) + "…" : String(v);
    parts.push(`${k}=${vs}`);
  }
  return parts.join("  |  ") || "（空记录）";
}

// ===== 渲染记录字段为 key-value 网格 =====
function renderRecordFields(rec) {
  if (!rec || typeof rec !== "object") return "";
  const entries = Object.entries(rec).filter(([k]) => k !== "_ref");
  const ref = rec._ref;
  let html = `<div class="record-fields">`;
  // 如果有_ref信息，先展示溯源引用
  if (ref && typeof ref === "object") {
    if (ref.file) html += `<div class="rf-key">📄 源文件</div><div class="rf-val">${escapeHtml(ref.file)}</div>`;
    if (typeof ref.row === "number" && ref.row >= 0)
      html += `<div class="rf-key">🔢 源行号</div><div class="rf-val">第 ${ref.row + 1} 行</div>`;
    if (ref.dataset) html += `<div class="rf-key">🗂️ 数据集</div><div class="rf-val">${escapeHtml(ref.dataset)}</div>`;
  }
  entries.forEach(([k, v]) => {
    let vs;
    if (v === null || v === undefined) vs = "<i style='color:#9ca3af;'>null</i>";
    else if (typeof v === "object") vs = `<pre style="margin:0;padding:4px;background:#f9fafb;border-radius:3px;overflow:auto;max-width:100%;">${escapeHtml(JSON.stringify(v, null, 2))}</pre>`;
    else vs = escapeHtml(String(v));
    html += `<div class="rf-key">${escapeHtml(k)}</div><div class="rf-val">${vs}</div>`;
  });
  html += `</div>`;
  return html;
}

// ===== AI 总结：确保加载 =====
async function ensureAiSummaryLoaded(findingUid, datasetIdx) {
  const statusEl = document.getElementById(`ai-status-${findingUid}-${datasetIdx}`);
  const bodyEl = document.getElementById(`ai-body-${findingUid}-${datasetIdx}`);
  if (!statusEl || !bodyEl) return;

  const cacheKey = `${findingUid}-${datasetIdx}`;
  // 找到 finding 数据（从 DOM 向上回溯代价大，改为使用全局审计数据中匹配）
  if (bodyEl.dataset.loaded === "1") return;

  // 查找对应的 finding 对象
  const findingData = findFindingDataByUid(findingUid);
  if (!findingData) {
    statusEl.textContent = "无发现数据";
    return;
  }
  const { slug, finding, datasetName } = findingData;
  const sourceRecs = {};
  if (datasetName) sourceRecs[datasetName] = (finding.source_records || {})[datasetName] || [];

  // 检查缓存
  if (aiSummaryCache.has(cacheKey)) {
    renderAiSummaryBody(bodyEl, statusEl, aiSummaryCache.get(cacheKey));
    bodyEl.dataset.loaded = "1";
    return;
  }

  // 显示 loading
  statusEl.textContent = "AI 分析中…";
  bodyEl.style.display = "block";
  bodyEl.innerHTML = `<div class="ai-loading"><div class="ai-spinner"></div><div class="ai-loading-text">DeepSeek 正在生成专业审计分析，请稍候…</div></div>`;

  try {
    const resp = await fetch("/api/ai_summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, finding, source_records: sourceRecs })
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    const summary = data.summary || "（无返回内容）";
    aiSummaryCache.set(cacheKey, summary);
    renderAiSummaryBody(bodyEl, statusEl, summary);
    bodyEl.dataset.loaded = "1";
  } catch (e) {
    // 失败兜底：直接显示静态提示
    const fallback = renderFallbackSummary(finding, datasetName, sourceRecs);
    renderAiSummaryBody(bodyEl, statusEl, fallback, true);
    bodyEl.dataset.loaded = "1";
  }
}

// ===== 兜底AI总结（纯前端规则生成，无需API） =====
function renderFallbackSummary(finding, datasetName, sourceRecs) {
  const sev = finding.severity || "中";
  const risks = {
    "高": "该发现为高风险，可能涉及合规披露缺陷或财务错报，建议优先处理并核查相关底稿。",
    "中": "该发现为中风险，需结合业务背景进一步核实影响范围，必要时追加审计程序。",
    "低": "该发现为低风险，可作为后续审计关注项定期跟踪。"
  };
  const recCount = Object.values(sourceRecs).reduce((s, arr) => s + (Array.isArray(arr) ? arr.length : 0), 0);
  const rows = [];
  for (const arr of Object.values(sourceRecs)) {
    for (const r of (arr || [])) {
      const rf = r._ref;
      if (rf && typeof rf.row === "number") rows.push(rf.row + 1);
    }
  }
  const rowsTxt = rows.length ? rows.slice(0, 5).join("、") : "未定位";
  return [
    "【数据异常点】",
    `· 发现「${finding.title || "未命名"}」匹配 ${recCount} 条原始记录`,
    `· 来源数据集：${datasetName || "未知"}，关联行：${rowsTxt}`,
    "【潜在风险】",
    `· ${risks[sev] || risks["中"]}`,
    "【建议措施】",
    "· 请人工核对原始数据真实性与完整性",
    "· 检查相关内控流程是否存在缺陷"
  ].join("\n");
}

// ===== 渲染 AI 总结文本为结构化内容 =====
function renderAiSummaryBody(bodyEl, statusEl, text, isFallback) {
  statusEl.textContent = isFallback ? "规则总结（离线）" : "分析完成";
  // 把结构化文本拆分为三段
  const sections = [];
  let curTitle = "";
  let curLines = [];
  text.split("\n").forEach(line => {
    const m = line.match(/^【(.+?)】/);
    if (m) {
      if (curTitle) sections.push({ title: curTitle, lines: curLines });
      curTitle = m[1];
      curLines = [];
      const rest = line.slice(m[0].length).trim();
      if (rest) curLines.push(rest);
    } else if (line.trim()) {
      curLines.push(line.trim());
    }
  });
  if (curTitle) sections.push({ title: curTitle, lines: curLines });

  if (sections.length === 0) {
    bodyEl.innerHTML = `<div class="ai-summary-body"><div class="ai-section-content">${escapeHtml(text)}</div></div>`;
    return;
  }

  let html = `<div class="ai-summary-body">`;
  sections.forEach(sec => {
    html += `<div class="ai-section">`;
    html += `<div class="ai-section-title">【${escapeHtml(sec.title)}】</div>`;
    html += `<div class="ai-section-content">`;
    sec.lines.forEach(l => {
      // 去掉 "· " 前缀，用自定义 bullet
      const clean = l.replace(/^[·•\-\*]\s*/, "");
      html += `<div><span class="ai-bullet">·</span>${escapeHtml(clean)}</div>`;
    });
    html += `</div></div>`;
  });
  html += `</div>`;
  bodyEl.innerHTML = html;
}

// ===== 通过 findingUid 反查 finding 数据 =====
function findFindingDataByUid(uid) {
  if (!auditData || !Array.isArray(auditData.findings)) return null;
  for (const f of auditData.findings) {
    const slug = f.source || "";
    const keySrc = slug + "|" + (f.title || "") + "|" + (f.detail || "");
    const computedUid = btoa(unescape(encodeURIComponent(keySrc))).slice(0, 24);
    if (computedUid === uid) {
      // 确定数据集名：遍历finding的datasets
      const datasets = f.datasets || Object.keys(f.source_records || {});
      return { slug, finding: f, datasetName: datasets[0] || "" };
    }
  }
  return null;
}

// 从 detail 文本中提取金额
function extractAmount(detail) {
  if (!detail) return "";
  const m = detail.match(/金额\s*([\d,.]+)/);
  if (m) {
    const num = parseFloat(m[1].replace(/,/g, ""));
    if (num >= 100000000) return (num / 100000000).toFixed(2) + " 亿";
    if (num >= 10000) return (num / 10000).toFixed(2) + " 万";
    return m[1];
  }
  return "";
}

// 获取模块中文名
function getModuleName(slug) {
  const n = nodes.find(n => n.slug === slug);
  if (n) return n.name;
  const mr = (auditData.module_results || {})[slug];
  return mr ? mr.name : slug;
}

function renderModuleDetail(n) {
  const panel = document.getElementById("panel-detail");
  const content = document.getElementById("detail-content");
  panel.style.display = "block";
  document.getElementById("detail-title").textContent = n.slug + " - " + n.name;

  const mr = (auditData.module_results || {})[n.slug] || {};
  const summary = mr.summary || {};
  const statusClass = n.status === "done" ? "detail-status-ok" : "detail-status-fail";
  const statusText = n.status === "done" ? "✓ 成功" : "✗ 失败";

  let html = "";
  html += `<div class="detail-row"><span class="detail-label">状态</span><span class="${statusClass}">${statusText}</span></div>`;
  html += `<div class="detail-row"><span class="detail-label">家族</span><span class="detail-value">${n.family}</span></div>`;
  html += `<div class="detail-row"><span class="detail-label">耗时</span><span class="detail-value">${n.duration}s</span></div>`;

  if (n.inputs.length > 0) {
    html += `<div class="detail-row"><span class="detail-label">上游</span><span class="detail-value">${n.inputs.join(", ")}</span></div>`;
  }
  if (n.outputs.length > 0) {
    html += `<div class="detail-row"><span class="detail-label">下游</span><span class="detail-value">${n.outputs.join(", ")}</span></div>`;
  }
  if (n.error) {
    html += `<div class="detail-row"><span class="detail-label">错误</span><span class="detail-value" style="color:#ef4444">${escapeHtml(n.error)}</span></div>`;
  }

  // 摘要
  if (summary.stats) {
    html += `<div class="detail-row"><span class="detail-label">统计</span></div>`;
    html += '<div style="margin-left:78px;margin-top:-4px;">';
    for (const [k, v] of Object.entries(summary.stats)) {
      html += `<div style="font-size:12px;color:#6b7280;">${k}: <span style="color:#1a1d29;font-weight:600">${v}</span></div>`;
    }
    html += '</div>';
  } else if (summary.keys) {
    html += `<div class="detail-row"><span class="detail-label">输出字段</span></div>`;
    html += `<div style="margin-left:78px;margin-top:-4px;font-size:12px;color:#6b7280;">${summary.keys.join(", ")}</div>`;
  }

  content.innerHTML = html;

  // 滚动到详情面板
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderLegend() {
  const legend = document.getElementById("legend");
  const families = [...new Set(nodes.map(n => n.family))];
  let html = '<div class="legend-title">模块家族</div>';
  families.forEach(f => {
    const color = FAMILY_COLORS[f] || "#78716c";
    html += `<div class="legend-item"><span class="legend-dot" style="background:${color}"></span>${f}</div>`;
  });
  html += '<div style="margin-top:6px;border-top:1px solid #e5e7eb;padding-top:6px;">';
  html += '<div class="legend-item"><span class="legend-dot" style="background:#10b981"></span>成功</div>';
  html += '<div class="legend-item"><span class="legend-dot" style="background:#ef4444"></span>失败</div>';
  html += '</div>';
  legend.innerHTML = html;
}

// ===== 工具函数 =====
function focusNode(slug) {
  const node = nodes.find(n => n.slug === slug);
  if (!node) return;
  selectedNode = node;
  renderModuleDetail(node);
  // 缩放到该节点
  const w = canvas.clientWidth, h = canvas.clientHeight;
  viewScale = 1.5;
  viewX = w / 2 - node.x * viewScale;
  viewY = h / 2 - node.y * viewScale;
}

function toggleLog() {
  const content = document.getElementById("log-content");
  const toggle = document.getElementById("log-toggle");
  if (content.style.display === "none") {
    content.style.display = "block";
    toggle.textContent = "▾ 执行日志";
  } else {
    content.style.display = "none";
    toggle.textContent = "▸ 执行日志";
  }
}

function escapeHtml(text) {
  if (text == null) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ===== 启动（含兼容性错误捕获，避免老内核浏览器白屏） =====
try {
  // 检测关键 ES6+ 特性是否可用
  if (typeof Promise === "undefined" || typeof fetch === "undefined" || typeof Symbol === "undefined") {
    showCompatError("您的浏览器内核版本过低，请切换到极速模式或使用 Chrome/Edge 浏览器访问。");
  } else {
    init().catch(function(err) {
      showCompatError("页面初始化失败：" + (err && err.message ? err.message : err));
    });
  }
} catch (e) {
  showCompatError("脚本执行错误：" + (e && e.message ? e.message : e));
}

function showCompatError(msg) {
  var hint = document.getElementById("canvas-hint");
  if (hint) {
    hint.style.cssText = "color:#ef4444;font-size:16px;padding:40px;text-align:center;line-height:1.8;";
    hint.innerHTML = msg + "<br><br>推荐使用 Chrome / Edge 浏览器，或在360浏览器地址栏点击「闪电/e」图标切换为极速模式。";
  }
}
