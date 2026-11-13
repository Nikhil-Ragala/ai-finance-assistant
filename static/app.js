/* AI Finance Assistant - frontend (plain JS + Chart.js) */
const $ = (id) => document.getElementById(id);
const CATS = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Education", "Other"];
const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// local (not UTC) date, so people east of UTC (e.g. India) don't get yesterday's date after midnight
const todayLocal = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
const state = { user: null, month: "", page: 1, perPage: 15, charts: {}, view: "dashboard" };

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (res.status === 401 && state.user) { showAuth(); }
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

/* ------------------------------------------------------------------ auth */
let authMode = "login";
document.querySelectorAll("[data-auth]").forEach((b) => b.addEventListener("click", () => {
  authMode = b.dataset.auth;
  document.querySelectorAll("[data-auth]").forEach((x) => x.classList.toggle("active", x === b));
  $("name-row").classList.toggle("hidden", authMode !== "register");
  $("auth-submit").textContent = authMode === "register" ? "Create account" : "Log in";
  $("auth-error").textContent = "";
}));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("auth-error").textContent = "";
  try {
    const body = { email: $("auth-email").value, password: $("auth-password").value };
    if (authMode === "register") body.name = $("auth-name").value;
    const data = await api(authMode === "register" ? "/register" : "/login", { method: "POST", body });
    startApp(data.user);
  } catch (err) { $("auth-error").textContent = err.message; }
});

$("logout-btn").addEventListener("click", async () => { await api("/logout", { method: "POST" }); showAuth(); });

function showAuth() {
  state.user = null;
  $("app-view").classList.add("hidden"); $("auth-view").classList.remove("hidden");
  $("auth-password").value = "";
}

function startApp(user) {
  state.user = user;
  $("auth-view").classList.add("hidden"); $("app-view").classList.remove("hidden");
  $("user-name").textContent = user.name;
  $("admin-tab").classList.toggle("hidden", !user.is_admin);
  $("chat-log").innerHTML = "";
  addMsg("bot", "Hi " + user.name.split(" ")[0] + "! Ask me how the app works, or things like 'how much did I spend this month?'");
  if (!state.month) {
    const d = new Date();
    state.month = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }
  $("month-picker").value = state.month;
  $("tx-date").value = todayLocal();
  switchView("dashboard");
}

/* ------------------------------------------------------------------ navigation */
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));
$("month-picker").addEventListener("change", (e) => { if (e.target.value) { state.month = e.target.value; refreshView(); } });

function switchView(v) {
  state.view = v;
  document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => s.classList.add("hidden"));
  $("view-" + v).classList.remove("hidden");
  document.querySelector(".monthbar").classList.toggle("hidden", !["dashboard", "budgets", "insights"].includes(v));
  refreshView();
}

function refreshView() {
  const v = state.view;
  if (v === "dashboard") loadDashboard();
  else if (v === "transactions") loadTransactions();
  else if (v === "budgets") loadBudgets();
  else if (v === "insights") loadInsights();
  else if (v === "admin") loadAdmin();
}

/* ------------------------------------------------------------------ dashboard */
function drawChart(key, canvasId, config) {
  if (state.charts[key]) state.charts[key].destroy();
  state.charts[key] = new Chart($(canvasId), config);
}

async function loadDashboard() {
  try {
    const d = await api("/dashboard?month=" + state.month);
    $("st-income").textContent = inr(d.total_income);
    $("st-expense").textContent = inr(d.total_expenses);
    $("st-month").textContent = inr(d.month_balance);
    $("st-month").className = d.month_balance >= 0 ? "pos" : "neg";
    $("st-balance").textContent = inr(d.available_balance);
    $("st-balance").className = d.available_balance >= 0 ? "pos" : "neg";

    $("alerts").innerHTML = d.budgets.filter((b) => b.status !== "ok").map((b) =>
      `<div class="alert ${b.status === "exceeded" ? "bad" : ""}">${b.status === "exceeded" ? "⚠ Over budget" : "Heads up"}: ${esc(b.category)} is at ${b.utilization_pct}% of its ${inr(b.limit_amount)} limit.</div>`).join("");

    const cats = Object.keys(d.category_spending);
    $("cat-empty").textContent = cats.length ? "" : "No expenses this month yet.";
    drawChart("cat", "chart-cat", {
      type: "doughnut",
      data: { labels: cats, datasets: [{ data: cats.map((c) => d.category_spending[c]), backgroundColor: ["#4f46e5", "#0ea5e9", "#f59e0b", "#10b981", "#ec4899", "#ef4444", "#8b5cf6", "#94a3b8"] }] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: (c) => `${c.label}: ${inr(c.raw)}` } } } },
    });
    drawChart("trend", "chart-trend", {
      type: "bar",
      data: { labels: d.monthly_trend.map((t) => t.month), datasets: [
        { label: "Expenses", data: d.monthly_trend.map((t) => t.expense), backgroundColor: "#ef4444" },
        { label: "Income", data: d.monthly_trend.map((t) => t.income), backgroundColor: "#10b981" }] },
      options: { maintainAspectRatio: false, scales: { y: { ticks: { callback: (v) => inr(v) } } }, plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${inr(c.raw)}` } } } },
    });

    $("dash-budgets").innerHTML = d.budgets.length ? renderBudgets(d.budgets, false) : '<p class="muted">No budgets set for this month. Add one in the Budgets tab.</p>';
    const f = d.forecast;
    $("forecast").innerHTML = f.estimate === null
      ? `<p class="muted">${esc(f.message)}</p>`
      : `<p style="font-size:1.6rem;margin:.2rem 0"><strong>${inr(f.estimate)}</strong></p><p class="muted">${esc(f.message)}</p>`;
  } catch (err) { toast(err.message); }
}

/* ------------------------------------------------------------------ transactions */
function fillCategorySelects() {
  $("tx-category").innerHTML = '<option value="">Auto (AI suggests)</option>' + CATS.map((c) => `<option>${c}</option>`).join("");
  $("f-category").innerHTML = '<option value="">All categories</option>' + CATS.map((c) => `<option>${c}</option>`).join("") + "<option>Income</option>";
  $("b-category").innerHTML = '<option value="Overall">Overall (all expenses)</option>' + CATS.map((c) => `<option>${c}</option>`).join("");
}
fillCategorySelects();

$("tx-type").addEventListener("change", () => {
  const inc = $("tx-type").value === "income";
  $("tx-category").disabled = inc;
  if (inc) $("tx-category").value = "";
});

// live AI suggestion while typing
let suggestTimer;
$("tx-desc").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  const desc = $("tx-desc").value.trim();
  if (desc.length < 3 || $("tx-type").value === "income") { $("tx-hint").textContent = ""; return; }
  suggestTimer = setTimeout(async () => {
    try {
      const p = await api("/predict-category", { method: "POST", body: { description: desc } });
      $("tx-hint").textContent = `AI suggests: ${p.category} (${Math.round(p.confidence * 100)}% confident)` + (p.low_confidence ? " - low confidence, please double-check" : "");
      if (!$("tx-id").value && !$("tx-category").value) $("tx-hint").dataset.cat = p.category;
    } catch (_) { /* hint is optional */ }
  }, 350);
});

function resetTxForm() {
  $("tx-form").reset(); $("tx-id").value = ""; $("tx-date").value = todayLocal();
  $("tx-form-title").textContent = "Add transaction"; $("tx-submit").textContent = "Add";
  $("tx-cancel").classList.add("hidden"); $("tx-category").disabled = false; $("tx-hint").textContent = ""; $("tx-error").textContent = "";
}
$("tx-cancel").addEventListener("click", resetTxForm);

$("tx-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("tx-error").textContent = "";
  const body = { date: $("tx-date").value, description: $("tx-desc").value, amount: $("tx-amount").value, type: $("tx-type").value };
  if ($("tx-category").value) body.category = $("tx-category").value;
  const id = $("tx-id").value;
  try {
    const res = await api(id ? "/transactions/" + id : "/transactions", { method: id ? "PUT" : "POST", body });
    toast(id ? "Transaction updated." : res.predicted ? `Added. AI categorised it as ${res.category} - edit it if that's wrong.` : "Transaction added.");
    resetTxForm(); loadTransactions();
  } catch (err) { $("tx-error").textContent = err.message; }
});

["f-search", "f-type", "f-category", "f-from", "f-to"].forEach((id) => $(id).addEventListener("input", () => { state.page = 1; loadTransactions(); }));
$("f-clear").addEventListener("click", () => { ["f-search", "f-type", "f-category", "f-from", "f-to"].forEach((i) => ($(i).value = "")); state.page = 1; loadTransactions(); });
$("pg-prev").addEventListener("click", () => { if (state.page > 1) { state.page--; loadTransactions(); } });
$("pg-next").addEventListener("click", () => { state.page++; loadTransactions(); });

async function loadTransactions() {
  const p = new URLSearchParams({ page: state.page, per_page: state.perPage });
  const map = { search: "f-search", type: "f-type", category: "f-category", from: "f-from", to: "f-to" };
  Object.entries(map).forEach(([k, id]) => { if ($(id).value) p.set(k, $(id).value); });
  try {
    const d = await api("/transactions?" + p);
    $("tx-body").innerHTML = d.transactions.length ? d.transactions.map((t) => `
      <tr>
        <td>${esc(t.date)}</td><td>${esc(t.description)}</td>
        <td><span class="badge">${esc(t.category)}</span></td>
        <td class="num ${t.type === "income" ? "pos" : ""}">${t.type === "income" ? "+" : "-"}${inr(t.amount)}</td>
        <td class="num"><button class="btn ghost sm" data-edit="${t.transaction_id}">Edit</button>
            <button class="btn ghost sm danger" data-del="${t.transaction_id}">Delete</button></td>
      </tr>`).join("") : '<tr><td colspan="5" class="muted">No transactions found.</td></tr>';
    const pages = Math.max(1, Math.ceil(d.total / d.per_page));
    if (state.page > pages) { state.page = pages; return loadTransactions(); }
    $("pg-info").textContent = `Page ${d.page} of ${pages} (${d.total} total)`;
    $("pg-prev").disabled = d.page <= 1; $("pg-next").disabled = d.page >= pages;
    state.txCache = Object.fromEntries(d.transactions.map((t) => [t.transaction_id, t]));
  } catch (err) { toast(err.message); }
}

$("tx-body").addEventListener("click", async (e) => {
  const edit = e.target.closest("[data-edit]"), del = e.target.closest("[data-del]");
  if (edit) {
    const t = state.txCache[edit.dataset.edit];
    $("tx-id").value = t.transaction_id; $("tx-date").value = t.date; $("tx-desc").value = t.description;
    $("tx-amount").value = t.amount; $("tx-type").value = t.type;
    $("tx-category").disabled = t.type === "income";
    $("tx-category").value = t.type === "income" ? "" : t.category;
    $("tx-form-title").textContent = "Edit transaction (change the category to correct the AI)";
    $("tx-submit").textContent = "Save"; $("tx-cancel").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (del && confirm("Delete this transaction?")) {
    try { await api("/transactions/" + del.dataset.del, { method: "DELETE" }); toast("Deleted."); loadTransactions(); }
    catch (err) { toast(err.message); }
  }
});

/* ------------------------------------------------------------------ budgets */
function renderBudgets(list, withDelete) {
  return list.map((b) => `
    <div class="budget-item">
      <div class="budget-head"><span><strong>${esc(b.category)}</strong> - ${inr(b.spent)} of ${inr(b.limit_amount)} (${b.utilization_pct}%)</span>
        <span>${b.remaining >= 0 ? inr(b.remaining) + " left" : "<span class='neg'>" + inr(-b.remaining) + " over</span>"}
        ${withDelete ? `<button class="btn ghost sm danger" data-bdel="${b.budget_id}">Remove</button>` : ""}</span></div>
      <div class="bar ${b.status}"><i style="width:${Math.min(b.utilization_pct, 100)}%"></i></div>
    </div>`).join("");
}

async function loadBudgets() {
  try {
    const d = await api("/budgets?month=" + state.month);
    $("budget-list").innerHTML = d.budgets.length ? renderBudgets(d.budgets, true) : '<p class="muted">No budgets for this month yet.</p>';
  } catch (err) { toast(err.message); }
}

$("budget-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("b-error").textContent = "";
  try {
    await api("/budgets", { method: "POST", body: { month: state.month, category: $("b-category").value, limit_amount: $("b-limit").value } });
    $("b-limit").value = ""; toast("Budget saved."); loadBudgets();
  } catch (err) { $("b-error").textContent = err.message; }
});
$("budget-list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-bdel]");
  if (!b) return;
  try { await api("/budgets/" + b.dataset.bdel, { method: "DELETE" }); loadBudgets(); } catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------------ insights */
async function loadInsights() {
  try {
    const d = await api("/insights?month=" + state.month);
    $("insight-list").innerHTML = d.insights.map((t) => `<li>${esc(t)}</li>`).join("");
    $("insight-note").textContent = d.disclaimer;
  } catch (err) { toast(err.message); }
}

/* ------------------------------------------------------------------ chatbot */
function addMsg(who, text) {
  const div = document.createElement("div");
  div.className = "msg " + who; div.textContent = text;
  $("chat-log").appendChild(div); $("chat-log").scrollTop = $("chat-log").scrollHeight;
}
$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const m = $("chat-input").value.trim();
  if (!m) return;
  addMsg("me", m); $("chat-input").value = "";
  try { addMsg("bot", (await api("/chatbot", { method: "POST", body: { message: m } })).reply); }
  catch (err) { addMsg("bot", err.message); }
});

/* ------------------------------------------------------------------ admin */
async function loadAdmin() {
  try {
    const d = await api("/admin/users");
    $("admin-body").innerHTML = d.users.map((u) => `
      <tr><td>${u.user_id}</td><td>${esc(u.name)}${u.is_admin ? ' <span class="badge">admin</span>' : ""}</td><td>${esc(u.email)}</td>
      <td class="num">${u.transactions}</td>
      <td class="num">${u.is_admin ? "" : `<button class="btn ghost sm danger" data-udel="${u.user_id}">Delete</button>`}</td></tr>`).join("");
  } catch (err) { toast(err.message); }
}
$("admin-body").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-udel]");
  if (!b || !confirm("Delete this user and all their data?")) return;
  try { await api("/admin/users/" + b.dataset.udel, { method: "DELETE" }); loadAdmin(); } catch (err) { toast(err.message); }
});
$("retrain-btn").addEventListener("click", async () => {
  $("retrain-msg").textContent = "Retraining...";
  try {
    const d = await api("/admin/retrain", { method: "POST" });
    $("retrain-msg").textContent = `${d.message} Used ${d.training_rows} rows (${d.user_corrections} user corrections).`;
  } catch (err) { $("retrain-msg").textContent = err.message; }
});

/* ------------------------------------------------------------------ boot */
(async () => {
  try { startApp((await api("/me")).user); } catch (_) { showAuth(); }
})();
