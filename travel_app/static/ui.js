export const setup = JSON.parse(document.getElementById("setup").textContent);
export const main = document.getElementById("main");
export const fields = Object.fromEntries(setup.fields.map(f => [f.key, f]));
export const labels = {must: "꼭 필요해요", important: "중요해요", prefer: "선호해요"};
const memory = new Map();
let announced = 0;

export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
export function append(parent, ...children) {
  parent.append(...children.filter(child => child !== null && child !== undefined));
  return parent;
}
export function btn(text, fn, cls = "button secondary") {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
export function announce(text) {
  const target = document.getElementById("announcer");
  clearTimeout(announced);
  target.textContent = "";
  announced = setTimeout(() => {target.textContent = text;}, 45);
}
export function swap(view, title, focus = true) {
  main.replaceChildren(view);
  document.title = title + " · 동행";
  if (focus) main.focus({preventScroll: true});
}
export function shell(title, description, eyebrow = "") {
  const wrap = el("section", "page");
  if (eyebrow) wrap.append(el("p", "eyebrow", eyebrow));
  wrap.append(el("h1", "", title));
  if (description) wrap.append(el("p", "lead", description));
  return wrap;
}
export function line(label, value) {
  return append(el("div", "definition"), el("dt", "", label), el("dd", "", value));
}
export function fmt(value) {
  if (value == null || value === "") return "미정";
  if (typeof value === "object" && "amount" in value) {
    if (value.currency === "KRW") return value.amount % 10000 === 0 ? Number(value.amount / 10000).toLocaleString("ko-KR") + "만 원" : Number(value.amount).toLocaleString("ko-KR") + "원";
    return Number(value.amount).toLocaleString("ko-KR") + " " + value.currency;
  }
  if (typeof value === "object" && "start" in value) return value.start + " ~ " + value.end;
  return String(value);
}
export function read(key, fallback = null) {
  try {const raw = sessionStorage.getItem("trip:" + key); if (raw !== null) return JSON.parse(raw);} catch {}
  return memory.has(key) ? memory.get(key) : fallback;
}
export function save(key, value) {
  memory.set(key, value);
  try {sessionStorage.setItem("trip:" + key, JSON.stringify(value));} catch {}
}
export function retryKey(kind, data) {
  const identity = JSON.stringify(data);
  const previous = read("retry:" + kind, {});
  if (previous.identity === identity) return previous.key;
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  const key = Array.from(bytes, v => v.toString(16).padStart(2, "0")).join("");
  save("retry:" + kind, {identity, key});
  return key;
}
export async function api(path, data) {
  let response, result;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 18000);
  try {
    response = await fetch(path, {method: data === undefined ? "GET" : "POST", credentials: "same-origin",
      cache: "no-store", signal: controller.signal, headers: data === undefined ? {} : {"Content-Type": "application/json"},
      body: data === undefined ? undefined : JSON.stringify(data)});
    result = await response.json().catch(() => null);
  } catch {throw new Error("연결을 확인해 주세요. 작성한 내용을 보관하고 있어요.");}
  finally {clearTimeout(timer);}
  if (!response.ok) {
    const error = new Error(result?.error || "요청을 마치지 못했어요. 잠시 후 다시 시도해 주세요.");
    error.field = result?.field; error.status = response.status;
    throw error;
  }
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    throw new Error("서버 응답을 읽지 못했어요. 다시 시도해 주세요.");
  }
  return result;
}
export function errorBox() {
  const node = el("p", "form-error"); node.setAttribute("role", "alert"); node.hidden = true; return node;
}
export function showError(container, fallback, error) {
  container.querySelectorAll(".form-error").forEach(n => {n.hidden = true; n.textContent = "";});
  const field = Array.from(container.querySelectorAll("[data-field]")).find(n => n.dataset.field === error.field);
  const box = field?.querySelector(".form-error") || fallback;
  box.textContent = error.message; box.hidden = false;
  if (field) {
    const control = field.querySelector("input:not(:disabled),select:not(:disabled),textarea:not(:disabled)");
    if (control) {control.setAttribute("aria-invalid", "true"); control.focus();}
  }
}
export function selectControl(options, value) {
  const s = el("select");
  for (const item of options) {
    const [v, label] = Array.isArray(item) ? item : [item, item];
    const opt = el("option", "", label); opt.value = v; s.append(opt);
  }
  if (value !== undefined) s.value = value;
  return s;
}
export function labeled(label, control, key = "") {
  const group = el("div", "control");
  if (key) group.dataset.field = key;
  const lab = el("label"); lab.append(el("span", "input-label", label), control);
  group.append(lab, errorBox());
  return group;
}
export function input(type, value = "", placeholder = "") {
  const node = el("input"); node.type = type; node.value = value ?? ""; node.placeholder = placeholder; return node;
}
export function fixedList(fixed) {
  const panel = el("section", "panel fixed-panel");
  panel.append(el("h3", "", "확정된 조건"));
  const keys = Object.keys(fixed);
  if (!keys.length) panel.append(el("p", "muted", "아직 확정한 항목이 없어요."));
  else {
    const list = el("dl", "rows");
    for (const f of setup.fields) if (f.key in fixed) list.append(line(f.label, fmt(fixed[f.key])));
    panel.append(list, el("p", "hint", "방장이 미리 정한 공통 조건이에요."));
  }
  return panel;
}
export function revealGuide() {document.getElementById("guide").showModal();}
