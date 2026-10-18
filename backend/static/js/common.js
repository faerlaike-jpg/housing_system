/* =============================================================================
   潍坊市二手房房价预测系统 · 全局公共 JS
   提供：Fetch 封装、CSRF、Toast 提示、骨架屏、空状态、格式化工具、ECharts 主题
   ============================================================================= */

/* ----------------------------- CSRF 处理 ----------------------------- */
function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : "";
}

/* ----------------------------- 统一响应体 ----------------------------- */
/**
 * 后端统一返回：{ code: 0, msg: "success", data: {...} }
 * code === 0 表示成功，非 0 抛出业务异常。
 */
async function apiFetch(url, options = {}) {
    const { method = "GET", body = null, params = null, isForm = false } = options;

    let fullUrl = url;
    if (params && typeof params === "object") {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== "") qs.append(k, v);
        });
        const query = qs.toString();
        if (query) fullUrl += (url.includes("?") ? "&" : "?") + query;
    }

    const headers = { "X-Requested-With": "XMLHttpRequest" };
    const config = { method, headers, credentials: "same-origin" };

    if (method !== "GET" && method !== "HEAD") {
        headers["X-CSRFToken"] = getCookie("csrftoken");
        if (isForm) {
            config.body = body;
        } else {
            headers["Content-Type"] = "application/json";
            config.body = JSON.stringify(body || {});
        }
    }

    let response;
    try {
        response = await fetch(fullUrl, config);
    } catch (err) {
        throw new Error("网络请求失败，请检查后端服务是否已启动");
    }

    // 即便 HTTP 状态码不是 2xx（如 400 / 401），后端也会返回统一结构
    // {code, msg}。这里统一把 msg 取出来，否则页面只能看到
    // 「请求异常（HTTP 400）」这种没有信息量的提示，无法定位真正原因。
    let result = null;
    try {
        result = await response.json();
    } catch (err) {
        result = null;
    }

    if (result && typeof result.code !== "undefined") {
        if (result.code !== 0) {
            throw new Error(result.msg || `请求异常（HTTP ${response.status}）`);
        }
        return result.data;
    }

    // 响应体不是标准 JSON（例如方法不允许时返回的纯文本）
    throw new Error(`请求异常（HTTP ${response.status}）`);
}

/* ----------------------------- Toast 提示 ----------------------------- */
function showToast(message, type = "info", duration = 2600) {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container position-fixed top-0 end-0 p-3";
        document.body.appendChild(container);
    }
    const icons = { info: "bi-info-circle-fill", success: "bi-check-circle-fill",
                    error: "bi-x-circle-fill", warning: "bi-exclamation-triangle-fill" };
    const colors = { info: "var(--primary)", success: "var(--success)",
                     error: "var(--danger)", warning: "var(--warning)" };

    const el = document.createElement("div");
    el.className = `app-toast toast-${type} mb-2`;
    el.innerHTML = `<i class="bi ${icons[type] || icons.info}" style="color:${colors[type] || colors.info}"></i>
                    <span>${escapeHtml(message)}</span>`;
    container.appendChild(el);
    setTimeout(() => {
        el.style.transition = "opacity .3s ease, transform .3s ease";
        el.style.opacity = "0";
        el.style.transform = "translateX(24px)";
        setTimeout(() => el.remove(), 300);
    }, duration);
}

/* ----------------------------- 骨架屏 ----------------------------- */
function renderSkeleton(selector, rows = 5, cols = 4) {
    const box = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!box) return;
    let html = "";
    for (let r = 0; r < rows; r++) {
        html += "<tr>";
        for (let c = 0; c < cols; c++) {
            html += `<td><div class="skeleton skeleton-line" style="width:${70 - c * 8}%;"></div></td>`;
        }
        html += "</tr>";
    }
    box.innerHTML = html;
}

function renderChartSkeleton(selector) {
    const box = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!box) return;
    box.innerHTML = `<div class="d-flex flex-column justify-content-center h-100 px-4">
        <div class="skeleton skeleton-line" style="width:40%;"></div>
        <div class="skeleton" style="height:220px;border-radius:10px;"></div>
    </div>`;
}

/* ----------------------------- 空状态 ----------------------------- */
function renderEmpty(selector, text = "暂无数据", icon = "bi-inbox") {
    const box = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (!box) return;
    box.innerHTML = `<div class="empty-state">
        <i class="bi ${icon} empty-icon"></i>
        <div class="empty-text">${escapeHtml(text)}</div>
    </div>`;
}

/* ----------------------------- 工具函数 ----------------------------- */
function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str).replace(/[&<>"']/g, (s) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[s]
    ));
}

function fmtNumber(value, digits = 0) {
    if (value === null || value === undefined || value === "" || isNaN(value)) return "--";
    return Number(value).toLocaleString("zh-CN", {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
}

function fmtPrice(value) { return fmtNumber(value, 1) + " 万"; }
function fmtUnitPrice(value) { return fmtNumber(value, 0) + " 元/㎡"; }
function fmtArea(value) { return fmtNumber(value, 1) + " ㎡"; }

/** 数字淡入计数动画 */
function countUp(el, target, digits = 0, duration = 900) {
    const node = typeof el === "string" ? document.querySelector(el) : el;
    if (!node) return;
    const end = Number(target) || 0;
    const start = performance.now();
    function step(now) {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        node.textContent = fmtNumber(end * eased, digits);
        if (progress < 1) requestAnimationFrame(step);
        else node.textContent = fmtNumber(end, digits);
    }
    requestAnimationFrame(step);
}

/** 简易防抖 */
function debounce(fn, delay = 300) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

/* ----------------------------- ECharts 通用配置 ----------------------------- */
const CHART_COLORS = ["#165DFF", "#36CFC9", "#4E86FF", "#6DD6D1", "#8FC7FF",
                      "#B7A6FF", "#FFB84D", "#FF8A8A", "#94BFFF", "#A9E5E1"];

/** 生成低饱和、圆角 tooltip 的统一 ECharts 基础配置 */
function baseChartOption(extra = {}) {
    return Object.assign({
        color: CHART_COLORS,
        textStyle: { fontFamily: "Inter, PingFang SC, Microsoft YaHei, sans-serif", color: "#4E5969" },
        tooltip: {
            trigger: "axis",
            backgroundColor: "rgba(255,255,255,0.96)",
            borderColor: "#E5E6EB",
            borderWidth: 1,
            padding: [10, 14],
            textStyle: { color: "#1D2129", fontSize: 13 },
            extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(29,33,41,0.12);",
            axisPointer: { type: "shadow", shadowStyle: { color: "rgba(22,93,255,0.06)" } },
        },
        grid: { left: 48, right: 28, top: 48, bottom: 40, containLabel: true },
        xAxis: {
            axisLine: { lineStyle: { color: "#E5E6EB" } },
            axisTick: { show: false },
            axisLabel: { color: "#86909C", fontSize: 12 },
            splitLine: { show: false },
        },
        yAxis: {
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: "#86909C", fontSize: 12 },
            splitLine: { lineStyle: { color: "#F2F3F5", type: "dashed" } },
        },
    }, extra);
}

/** 统一处理图表为空的情况 */
function showChartEmpty(chart, text = "暂无数据") {
    chart.setOption({
        title: {
            text, left: "center", top: "middle",
            textStyle: { color: "#86909C", fontSize: 14, fontWeight: "normal" },
        },
        xAxis: { show: false }, yAxis: { show: false }, series: [],
    }, true);
}
