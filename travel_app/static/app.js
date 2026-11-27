import {announce, api, append, btn, el, errorBox, fixedList, input, labeled, main, read, retryKey, revealGuide, save, selectControl, setup, shell, showError, swap} from "./ui.js";
import {collect, fieldEditor, formSection, nameInput, normalizedPersona, personaEditor, profileBody, profileSummary, submitButton} from "./forms.js";
import {negotiation, resultScreen} from "./room.js";
import {soundControl} from "./alerts.js";

const guide = document.getElementById("guide");
document.getElementById("help").addEventListener("click", revealGuide);
document.getElementById("guide-done").addEventListener("click", () => guide.close());
document.getElementById("close-guide").addEventListener("click", () => guide.close());
guide.addEventListener("click", e => {if (e.target === guide) guide.close();});
const invite = setup.invite, endpoint = "/api/rooms/" + encodeURIComponent(invite || "");
const roomKey = key => key + ":" + invite;
let lastRoom, screen = "", mounted = null, refreshing = false, queued = false, handle = 0;

function welcome() {
  const wrap = el("div", "welcome"), hero = el("section", "hero"), intro = el("div", "intro");
  intro.append(el("p", "greeting", "반가워요, 여행자님."), append(el("h1"), el("span", "", "우리의 여행,"), el("span", "", "함께 정해요.")),
    el("p", "hero-copy", "내 에이전트에게 여행 조건을 맡겨요. 판사 에이전트가 모두의 의견을 듣고 여행안을 결정해요."),
    append(el("div", "actions"), btn("여행방 만들기  →", createScreen, "button primary"), btn("사용법 보기", revealGuide)));
  const art = el("div", "travel-art"); art.setAttribute("aria-hidden", "true");
  for (const name of ["grid-map", "contour contour-one", "contour contour-two", "contour contour-three", "route", "pin pin-a", "pin pin-b", "plane"]) art.append(el("i", name));
  hero.append(intro, art); wrap.append(hero);
  const process = el("section", "process"); process.setAttribute("aria-label", "함께 정하는 과정");
  for (const [title, copy, icon] of [["조건 모으기", "확정한 정보와 각자 지키고 싶은 조건을 모아요.", "pin-icon"],
      ["의견 조율하기", "개인 에이전트들이 근거를 찾고 서로 의견을 나눠요.", "speech-icon"],
      ["여행안 확인", "최종 일정, 예산과 확인할 항목을 함께 살펴봐요.", "check-icon"]]) {
    const symbol = el("span", icon); symbol.setAttribute("aria-hidden", "true");
    process.append(append(el("article"), symbol, el("h2", "", title), el("p", "", copy)));
  }
  wrap.append(process); swap(wrap, "함께 정하는 여행", false);
}

function createScreen() {
  const draft = read("create-draft", {name: "", capacity: 2, mediator: setup.mediatorStyles[0], fields: {}});
  const persist = () => save("create-draft", draft);
  const page = shell("여행방 만들기", "함께 갈 인원과 이미 확정한 조건을 정해요.", "방장 설정");
  const form = el("form"), basic = formSection("여행방 설정", "");
  const name = nameInput(draft.name), capacity = selectControl(Array.from({length: 7}, (_, i) => [i + 2, (i + 2) + "명"]), draft.capacity);
  draft.mediator = normalizedPersona(draft.mediator,setup.mediatorStyles);
  const judgePresets = setup.mediatorStyles.map(value => [value, value.replace("진행자", "판사")]);
  const mediator = personaEditor("판사 에이전트의 성격과 말투", draft.mediator, judgePresets, persist,
    "판사는 전원의 제안을 검토한 뒤, 여기에 적은 성격과 말투로 판단을 알리고 토론을 진행해요.");
  name.addEventListener("input", () => {draft.name = name.value; persist();});
  capacity.addEventListener("change", () => {draft.capacity = Number(capacity.value); persist();});
  const code = input("password", "", "팀에서 공유한 코드"); code.autocomplete = "off"; code.required = setup.needsCode;
  basic.append(append(el("div", "pair"), labeled("내 닉네임", name, "name"), labeled("총인원 · 방장 포함", capacity, "capacity")));
  if (setup.needsCode) basic.append(labeled("팀 방 개설 코드", code, "team_code"));
  const conditional = formSection("미리 확정할 조건", "여기서 직접 입력한 항목은 방에 있는 모두에게 고정돼요. 아직 정해지지 않았다면 맡겨 주세요.");
  conditional.append(fieldEditor(draft, {}, false, persist));
  const error = errorBox(), submit = submitButton("여행방 만들기  →");
  form.append(basic, conditional, mediator, error, append(el("div", "actions"), btn("이전", welcome), submit));
  form.addEventListener("submit", async e => {
    e.preventDefault(); if (submit.disabled) return;
    const body = {name: name.value.trim(), capacity: Number(capacity.value), mediator: draft.mediator, fixed: collect(draft, false)};
    const key = retryKey("create", body);
    submit.disabled = true;
    try {
      const result = await api("/api/rooms", {...body, request_id: key, team_code: code.value});
      save("create-draft", {name: draft.name, capacity: 2, mediator: setup.mediatorStyles[0], fields: {}});
      save("retry:create", {});
      location.assign("/r/" + encodeURIComponent(result.invite));
    } catch (ex) {showError(form, error, ex); submit.disabled = false;}
  });
  page.append(form); swap(page, "여행방 만들기");
}

function invitePanel() {
  const box = el("section", "panel invite"), row = el("div", "invite-line");
  box.append(el("h3", "", "함께 갈 사람 초대"));
  const url = input("url", location.origin + "/r/" + invite); url.readOnly = true; url.setAttribute("aria-label", "여행방 초대 링크");
  const status = el("p", "hint"); status.setAttribute("role", "status");
  const button = btn("링크 복사", async () => {
    try {await navigator.clipboard.writeText(url.value); status.textContent = "초대 링크를 복사했어요.";}
    catch {url.focus(); url.select(); status.textContent = "링크 전체를 선택했어요. 복사해서 공유해 주세요.";}
  });
  row.append(url, button); box.append(row, status); return box;
}

function joinScreen(room) {
  const page = shell("여행방에 초대됐어요.", "닉네임을 정하고 여행 조건을 함께 맞춰 봐요.", "초대받은 여행방");
  const joined = el("p", "count"), form = el("form", "form-section"), name = nameInput(read(roomKey("join-name"), ""));
  name.addEventListener("input", () => save(roomKey("join-name"), name.value));
  const error = errorBox(), submit = submitButton("입장하기  →");
  form.append(labeled("내 닉네임", name, "name"), error, submit);
  form.addEventListener("submit", async e => {
    e.preventDefault(); if (submit.disabled) return;
    submit.disabled = true;
    const body = {name: name.value.trim()};
    try {await api(endpoint + "/join", {...body, request_id: retryKey(roomKey("join"), body)}); refresh();}
    catch (ex) {showError(form, error, ex); submit.disabled = false;}
  });
  page.append(joined, fixedList(room.fixed), form); swap(page, "여행방 초대");
  return r => {
    joined.textContent = "입장 " + r.joined + "/" + r.capacity + "명";
    if (!r.can_join) {submit.disabled = true; submit.textContent = "입장이 마감됐어요";}
  };
}

function profileScreen(room) {
  const draft = read(roomKey("profile"), {fields: {}, persona: setup.agentStyles[0], extra: ""});
  const persist = () => save(roomKey("profile"), draft);
  const page = shell("내 여행 조건", "직접 정하고 싶은 것만 선택해요. 나머지는 내 에이전트가 함께 조율해요.", "준비 1 / 2");
  const form = el("form");
  if (room.member.seat === 1) page.append(invitePanel());
  if (room.member.agent) page.append(append(el("section","panel"),el("h3","","내 에이전트의 임무"),el("p","muted",room.member.agent.mission)));
  const section = formSection("내가 원하는 조건", "직접 입력한 항목은 중요도도 정할 수 있어요.");
  section.append(fieldEditor(draft, room.fixed, true, persist));
  if (Object.keys(room.fixed).length === setup.fields.length) section.append(el("p", "muted", "모든 여행 항목이 확정됐어요. 내 에이전트의 성향과 추가 요청을 정해 주세요."));
  draft.persona = normalizedPersona(draft.persona,setup.agentStyles);
  const personal = personaEditor("내 에이전트의 성격과 말투",draft.persona,setup.agentStyles,persist);
  const extra = el("textarea"); extra.value = draft.extra; extra.maxLength = 600; extra.rows = 3; extra.placeholder = "조율할 때 고려할 점을 적어 주세요.";
  extra.addEventListener("input", () => {draft.extra = extra.value; persist();});
  personal.append(labeled("내 에이전트만 읽는 추가 요청 · 선택", extra, "extra"));
  form.append(section, personal, submitButton("제출 내용 확인  →"));
  form.addEventListener("submit", e => {e.preventDefault(); save(roomKey("review"), true); route(lastRoom);});
  page.append(form); swap(page, "내 여행 조건");
}

function reviewScreen(room) {
  const body = profileBody(read(roomKey("profile"), {}));
  const page = shell("준비를 마칠까요?", "아래 조건을 내 에이전트에게 전달해요. 전원이 준비되면 조율이 시작돼요.", "준비 2 / 2");
  const error = errorBox(), go = btn("준비 완료", async () => {
    if (go.disabled) return;
    go.disabled = true;
    try {await api(endpoint + "/ready", body); announce("준비를 마쳤어요."); refresh();}
    catch (ex) {showError(page, error, ex); go.disabled = false;}
  }, "button primary");
  page.append(fixedList(room.fixed), profileSummary(body), error, append(el("div", "actions"),
    btn("수정하기", () => {save(roomKey("review"), false); route(lastRoom);}), go));
  swap(page, "제출 내용 확인");
}

function waitingScreen(room) {
  const page = shell("친구들을 기다려요.", "모두 준비를 마치면 각자의 에이전트가 조율을 시작해요.", "준비 완료");
  const counts = el("p", "counts"), roster = el("ul", "roster"), section = el("section", "panel");
  section.append(el("h2", "", "참여자"), counts, roster); page.append(soundControl(), section, invitePanel(), profileSummary(room.member.profile));
  swap(page, "참여자 기다리기");
  let prior = "";
  return r => {
    counts.textContent = "입장 " + r.joined + "/" + r.capacity + "명  ·  준비 " + r.ready + "/" + r.capacity + "명";
    const digest = JSON.stringify(r.members);
    if (digest === prior) return; prior = digest;
    roster.replaceChildren(...r.members.map(m => append(el("li"), el("span", "avatar", m.name.slice(0, 1)), el("strong", "", m.name + (m.seat === 1 ? " · 방장" : "")), el("span", "tag", m.ready ? "준비 완료" : "작성 중"))));
  };
}

function route(room) {
  lastRoom = room;
  const next = !room.member ? "join" : !room.member.ready ? (read(roomKey("review")) ? "review" : "profile")
    : room.mode === "waiting" ? "waiting" : room.mode === "done" ? "result" : "negotiation";
  if (next === "result" && screen === "negotiation" &&
      (main.contains(document.activeElement) && document.activeElement !== main || !main.querySelector(".chat .full")?.hidden)) {
    mounted(room); return;
  }
  if (next !== screen) {
    screen = next; mounted = null;
    if (next === "join") mounted = joinScreen(room);
    if (next === "profile") profileScreen(room);
    if (next === "review") reviewScreen(room);
    if (next === "waiting") mounted = waitingScreen(room);
    if (next === "negotiation") mounted = negotiation(room, endpoint, refresh, () => {
      screen = "result"; mounted = null; resultScreen(lastRoom);
    });
    if (next === "result") resultScreen(room);
  }
  if (mounted) mounted(room);
}

async function refresh() {
  if (!invite) return;
  if (refreshing) {queued = true; return;}
  clearTimeout(handle); refreshing = true;
  const connection = document.getElementById("connection");
  try {
    const room = await api(endpoint);
    if (!connection.hidden) announce("여행방 연결을 복원했어요.");
    connection.hidden = true; route(room);
  } catch (ex) {
    connection.hidden = false; connection.textContent = ex.status === 404 ? ex.message : "연결을 확인하고 있어요. 다시 연결되면 여행방을 복원해요.";
    if (!lastRoom && ex.status === 404) {
      const page = shell("여행방을 찾지 못했어요.", "받은 초대 링크를 다시 확인해 주세요.");
      page.append(btn("처음으로", () => location.assign("/"))); swap(page, "초대 링크 확인");
    }
  } finally {
    refreshing = false;
    if (queued) {queued = false; handle = setTimeout(refresh, 0);}
    else if (lastRoom?.mode !== "done") handle = setTimeout(refresh, document.hidden ? 4500 : 1400);
  }
}
if (invite) {
  swap(shell("여행방을 열고 있어요.", "참여 상태와 여행 조건을 확인해요."), "여행방 열기", false);
  refresh(); document.addEventListener("visibilitychange", () => {if (!document.hidden) refresh();});
  window.addEventListener("online", refresh);
} else welcome();
