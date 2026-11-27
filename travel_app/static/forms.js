import {append, el, errorBox, fields, fmt, input, labeled, labels, line, selectControl, setup} from "./ui.js";

export function fieldEditor(draft, fixed, personal, persist) {
  const list = el("div", "field-list");
  draft.fields ||= {};
  for (const item of setup.fields) {
    const key = item.key;
    if (key in fixed) {
      const locked = el("section", "locked-field");
      const badge = el("span", "lock-badge"); badge.append(el("i", "lock-icon"), document.createTextNode("방장이 확정함"));
      locked.append(append(el("div", "decision-head"), el("h3", "", item.label), badge), el("p", "", fmt(fixed[key])));
      list.append(locked); continue;
    }
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
        end.min = start.value;
        end.max = start.value && Number.isFinite(start.valueAsNumber) ? new Date(start.valueAsNumber + 365 * 86400000).toISOString().slice(0, 10) : "";
        end.setCustomValidity(start.value && end.value && end.value < start.value ? "종료일은 시작일 이후로 골라 주세요." : "");
      };
      if (saved.value) changed();
      controls.append(append(el("div", "pair"), labeled("시작일", watch(start, changed)), labeled("종료일", watch(end, changed))));
    } else if (item.kind === "money") {
      saved.value ||= {amount:500000, currency:"KRW"};
      const money = input("number", saved.value?.amount, "예: 500000");
      money.min = "1"; money.max = "10000000000"; money.step = "1"; money.inputMode = "numeric";
      const currency = selectControl(setup.currencies, saved.value?.currency || "KRW");
      const slider = input("range"), displayAmount = el("output", "range-value");
      slider.min = "1"; slider.step = "1";
      const syncBudget = () => {
        const common = {KRW:2000000,JPY:200000,USD:2000,EUR:2000,CNY:15000,GBP:2000,THB:70000,VND:50000000}[currency.value];
        const value = Number(money.value) || 1;
        slider.max = String(Math.min(1e10, Math.max(common, Math.ceil(value / common) * common)));
        slider.value = String(value); displayAmount.textContent = money.value ? "1인당 최대 " + fmt({amount:value,currency:currency.value}) : "정확한 금액을 입력해 주세요.";
        slider.setAttribute("aria-valuetext",displayAmount.textContent);
      };
      const changed = () => {saved.value = {amount: money.value === "" ? null : Number(money.value), currency: currency.value}; syncBudget();};
      slider.addEventListener("input", () => {money.value = slider.value; changed(); persist();});
      syncBudget();
      controls.append(labeled("1인당 최대 예산 슬라이더", slider), displayAmount);
      controls.append(append(el("div", "pair budget"), labeled("1인 총액 상한", watch(money, changed)), labeled("통화", watch(currency, changed))));
    } else if (item.kind === "select") {
      const ctrl = selectControl([["", "선택해 주세요"], ...item.options], saved.value || "");
      controls.append(labeled(item.label + " 선택", watch(ctrl, () => {saved.value = ctrl.value;})));
    } else if (item.kind === "schedule") {
      const ctrl = el("textarea"); ctrl.value = saved.value || ""; ctrl.rows = 3; ctrl.maxLength = 400;
      ctrl.placeholder = item.hint;
      controls.append(labeled("가는 편과 오는 편의 일정 또는 희망 시간대", watch(ctrl, () => {saved.value = ctrl.value.trim();})));
      controls.append(el("p","hint","예약했다면 편명, 출발·도착 공항과 현지 일시를 적어 주세요. 오는 편은 선택이에요."));
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
      controls.querySelectorAll("input,select,textarea").forEach(n => {n.disabled = !saved.direct;});
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
export function normalizedPersona(value, presets) {
  const base = {preset:presets[0],aggression:5,politeness:5,mz:5,instruction:""};
  return typeof value === "string" ? {...base,preset:value} : {...base,...value};
}
export function personaEditor(title, value, presets, persist, description = "내 에이전트가 첫 제안과 토론 발언을 작성할 때 여기에 적은 성격과 말투를 사용해요.") {
  const box = formSection(title, description);
  const preset = selectControl(presets,value.preset);
  preset.addEventListener("change",() => {value.preset=preset.value;persist();});
  box.append(labeled("기본 성향",preset));
  for (const [key,label] of [["aggression","공격성"],["politeness","예의"],["mz","MZ 감성"]]) {
    const slider = input("range",value[key]); slider.min = "0"; slider.max = "10"; slider.step = "1"; slider.value = String(value[key]);
    const row = el("div","persona-range"), out = el("span","range-value",value[key] + " / 10");
    out.setAttribute("aria-hidden", "true");
    slider.addEventListener("input",() => {value[key]=Number(slider.value);out.textContent=value[key] + " / 10";persist();});
    const lab = el("label"); lab.append(append(el("span","range-caption"),el("span","input-label",label),out),slider);
    row.append(lab,append(el("div","range-ends"),el("span","","0"),el("span","","10")));box.append(row);
  }
  const custom = el("textarea"); custom.rows = 2; custom.maxLength = 180; custom.value = value.instruction;
  custom.placeholder = "예: 심야 라디오 DJ처럼 차분하게 이야기하고 짧은 질문으로 마쳐 줘.";
  custom.addEventListener("input",() => {value.instruction=custom.value;persist();});
  box.append(labeled("원하는 성격과 말투 · 선택",custom)); return box;
}
export function profileBody(draft) {
  return {preferences: collect(draft, true), persona: normalizedPersona(draft.persona,setup.agentStyles), extra: draft.extra || ""};
}
export function profileSummary(body) {
  const box = el("section", "panel");
  box.append(el("h3", "", "내 에이전트에게 맡긴 내용"));
  const detail = el("dl", "rows");
  for (const [key, entry] of Object.entries(body.preferences)) detail.append(line(fields[key].label, fmt(entry.value) + " · " + labels[entry.priority]));
  if (!Object.keys(body.preferences).length) box.append(el("p", "muted", "여행 조건을 모두 에이전트에게 맡겼어요."));
  const character = normalizedPersona(body.persona,setup.agentStyles);
  detail.append(line("내 에이전트 성향", character.preset + " · 공격성 " + character.aggression + " · 예의 " + character.politeness + " · MZ 감성 " + character.mz));
  if (character.instruction) detail.append(line("원하는 성격과 말투",character.instruction));
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
