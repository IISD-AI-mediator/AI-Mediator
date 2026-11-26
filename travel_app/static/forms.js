import {append, btn, el, errorBox, fields, fixedList, fmt, input, labeled, labels, line, selectControl, setup} from "./ui.js";

export function fieldEditor(draft, fixed, personal, persist) {
  const list = el("div", "field-list");
  draft.fields ||= {};
  for (const item of setup.fields) {
    const key = item.key;
    if (key in fixed) continue;
    const saved = draft.fields[key] ||= {direct: false, value: null, priority: "prefer"};
    const set = el("fieldset", "field-card"); set.dataset.field = key;
    set.append(el("legend", "", item.label));
    const toggles = el("div", "segmented");
    const controls = el("div", "field-values");
    const radios = [false, true].map(direct => {
      const radio = input("radio"); radio.name = "mode-" + key; radio.checked = saved.direct === direct;
      const lab = el("label", "segment");
      lab.append(radio, el("span", "", direct ? "직접 입력" : "맡기기"));
      radio.setAttribute("aria-label", item.label + (direct ? " 직접 입력" : " 에이전트에게 맡기기"));
      radio.addEventListener("change", () => {saved.direct = direct; sync(); persist();});
      toggles.append(lab); return radio;
    });
    function watch(control, callback) {
      control.required = true;
      const update = () => {callback(); control.removeAttribute("aria-invalid"); persist();};
      control.addEventListener("input", update); control.addEventListener("change", update);
      return control;
    }
    if (item.kind === "dates") {
      const start = input("date", saved.value?.start), end = input("date", saved.value?.end);
      const changed = () => {
        saved.value = {start: start.value, end: end.value};
        end.min = start.value; end.setCustomValidity(start.value && end.value && end.value < start.value ? "종료일은 시작일 이후로 골라 주세요." : "");
      };
      end.min = start.value;
      controls.append(append(el("div", "pair"), labeled("시작일", watch(start, changed)), labeled("종료일", watch(end, changed))));
    } else if (item.kind === "money") {
      const money = input("number", saved.value?.amount, "예: 500000");
      money.min = "1"; money.max = "10000000000"; money.step = "1"; money.inputMode = "numeric";
      const currency = selectControl(setup.currencies, saved.value?.currency || "KRW");
      const changed = () => {saved.value = {amount: money.value === "" ? null : Number(money.value), currency: currency.value};};
      controls.append(append(el("div", "pair budget"), labeled("1인 총액 상한", watch(money, changed)), labeled("통화", watch(currency, changed))));
    } else if (item.kind === "select") {
      const ctrl = selectControl([["", "선택해 주세요"], ...item.options], saved.value || "");
      controls.append(labeled(item.label + " 선택", watch(ctrl, () => {saved.value = ctrl.value;})));
    } else {
      const ctrl = input("text", saved.value || "", item.hint); ctrl.maxLength = 160;
      controls.append(labeled(item.label + " 입력", watch(ctrl, () => {saved.value = ctrl.value.trim();})));
    }
    if (personal) {
      const importance = selectControl(Object.entries(labels).reverse(), saved.priority);
      controls.append(labeled("이 조건의 중요도", watch(importance, () => {saved.priority = importance.value;})));
    }
    set.append(toggles, controls, errorBox());
    function sync() {
      controls.hidden = !saved.direct;
      controls.querySelectorAll("input,select").forEach(n => {n.disabled = !saved.direct;});
      radios.forEach((node, index) => {node.checked = Boolean(index) === saved.direct;});
    }
    sync(); list.append(set);
  }
  return list;
}
export function collect(draft, personal) {
  const result = {};
  for (const [key, item] of Object.entries(draft.fields || {})) {
    if (item.direct) result[key] = personal ? {value: item.value, priority: item.priority} : item.value;
  }
  return result;
}
export function profileBody(draft) {
  return {preferences: collect(draft, true), persona: draft.persona || setup.agentStyles[0], extra: draft.extra || ""};
}
export function profileSummary(body) {
  const box = el("section", "panel");
  box.append(el("h3", "", "내 에이전트에게 맡긴 내용"));
  const detail = el("dl", "rows");
  for (const [key, entry] of Object.entries(body.preferences)) detail.append(line(fields[key].label, fmt(entry.value) + " · " + labels[entry.priority]));
  if (!Object.keys(body.preferences).length) box.append(el("p", "muted", "여행 조건을 모두 에이전트에게 맡겼어요."));
  detail.append(line("내 에이전트 성향", body.persona));
  if (body.extra) detail.append(line("나만의 추가 요청", body.extra));
  box.append(detail); return box;
}
export function submitButton(text) {
  const node = el("button", "button primary", text); node.type = "submit"; return node;
}
export function nameInput(value) {
  const n = input("text", value || "", "여행방에서 사용할 이름"); n.maxLength = 24; n.required = true; n.autocomplete = "nickname"; return n;
}
export function formSection(title, description) {
  const group = el("section", "form-section");
  group.append(el("h2", "", title));
  if (description) group.append(el("p", "muted", description));
  return group;
}
