import {announce, api, append, btn, el, errorBox, fields, fmt, labeled, line, read, retryKey, save, shell, showError, swap} from "./ui.js";
import {ring,soundControl} from "./alerts.js";

const statuses = {fixed: "사전 확정", agreed: "합의", suggested: "AI 제안", unresolved: "미해결", verify: "확인 필요"};
function decisionStatus(item) {
  const status = statuses[item.status] || "미정";
  return item.origin === "agent" && item.status !== "suggested" ? status + " · AI 제안" : status;
}
function decisionReason(item) {
  return [item.reason, item.verification_reason && "확인 필요 · " + item.verification_reason].filter(Boolean).join(" ");
}

function details(title, child, open = false) {
  const fold = el("details", "fold"); fold.open = open;
  fold.append(el("summary", "", title), child); return fold;
}
function message(item) {
  const li = el("li", item.kind === "speech" || item.kind === "proposal" ? "chat-line" : "chat-line moderator");
  const head = el("div", "chat-head");
  head.append(el("strong", "", item.speaker));
  if (fields[item.topic]) head.append(el("span", "tag", fields[item.topic].label));
  if (item.at) {
    const time = el("time", "", new Date(item.at * 1000).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"}));
    time.dateTime = new Date(item.at * 1000).toISOString(); head.append(time);
  }
  li.append(head, el("p", "", item.text)); return li;
}
function proposals(history) {
  const container = el("div", "rounds");
  history.forEach((entry, index) => {
    const rows = el("dl", "rows");
    for (const [k, v] of Object.entries(entry.entries)) if (fields[k]) rows.append(line(fields[k].label, fmt(v.value) + " · " + decisionStatus(v) + " · " + decisionReason(v)));
    const mode = index === 0 ? "조율 모드" : "파이터 모드 " + entry.round + "회차";
    container.append(details(mode + " · 판사 에이전트의 판단", rows));
  });
  if (!history.length) container.append(el("p", "hint", "판사 에이전트의 첫 판단을 기다리고 있어요."));
  return container;
}
export function negotiation(initial, endpoint, refresh, showFinal) {
  const page = shell("여행을 조율하고 있어요.", "개인 에이전트가 의견을 제시하면 판사 에이전트가 근거를 검토해 여행안을 결정해요.", "에이전트 협상");
  const phase = el("div", "phase-line"), badge = el("span", "phase"), words = el("p", "muted");
  phase.append(badge, words,soundControl()); page.append(phase);
  const done = btn("최종 여행안 보기  →", showFinal, "button primary"); done.hidden = true; page.append(done);
  const fightBox = el("aside", "fight-banner"); fightBox.hidden = true;
  const fightTitle = el("strong"), fightReason = el("p"), openChat = btn("대화 보기  ↓", () => {
    chat.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
    scroller.focus({preventScroll: true});
  }, "button secondary");
  fightBox.append(fightTitle, fightReason, openChat);
  const issue = el("div", "panel"); issue.hidden = true; const issueText = el("p"), issueError = errorBox();
  const resume = btn("이 단계 다시 시도", async () => {
    resume.disabled = true;
    try {await api(endpoint + "/retry", {}); refresh();}
    catch (error) {showError(issue, issueError, error);}
    finally {resume.disabled = false;}
  });
  issue.append(issueText, resume, issueError); page.append(fightBox, issue);
  const chat = el("section", "panel chat"); chat.append(el("h2", "", "에이전트 단체 대화"));
  const scroller = el("div", "chat-scroller"); scroller.tabIndex = 0; scroller.setAttribute("aria-label", "개인 에이전트와 판사 에이전트의 공개 대화");
  const log = el("ol", "chat-log"); scroller.append(log);
  const newer = btn("새 발언 보기  ↓", () => {scroller.scrollTop = scroller.scrollHeight; newer.hidden = true;}, "button secondary full");
  newer.hidden = true;
  scroller.addEventListener("scroll", () => {if (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 28) newer.hidden = true;});
  chat.append(scroller, newer); page.append(chat);
  const noteSection = el("section", "panel private-panel");
  const disclosure = el("details"), summary = el("summary", "", "내 에이전트에게만 지시"); disclosure.append(summary);
  const recipient = el("p", "muted", "받는 사람 · " + initial.member.name + "의 에이전트");
  const windowInfo = el("p", "hint"), noteForm = el("form"), editor = el("textarea");
  editor.rows = 3; editor.maxLength = 400; editor.required = true; editor.placeholder = "다음 발언에서 고려할 조건을 적어 주세요.";
  const draftKey = "note-draft:" + initial.invite, sendKey = "note:" + initial.invite;
  editor.value = read(draftKey, "");
  editor.addEventListener("input", () => save(draftKey, editor.value));
  const send = el("button", "button primary", "내 에이전트에게 보내기"); send.type = "submit";
  const error = errorBox(), received = el("p", "hint"); received.setAttribute("role", "status");
  const noteHistory = el("ol", "note-history"); noteHistory.setAttribute("aria-label", "내 지시와 반영 상태");
  let sending = false, state = initial, noteDigest = "", shown = 0, historyLength = -1;
  noteForm.append(labeled("비공개 지시", editor, "text"), error, send, received);
  noteForm.addEventListener("submit", async e => {
    e.preventDefault(); if (sending || !state.floor?.open) return;
    sending = true; send.disabled = true;
    const body = {text: editor.value.trim()};
    try {
      await api(endpoint + "/notes", {...body, request_id: retryKey(sendKey, body)});
      editor.value = ""; save(draftKey, ""); save("retry:" + sendKey, {}); error.hidden = true;
      received.textContent = "내 에이전트에게 전달됐어요."; refresh();
    } catch (ex) {showError(noteForm, error, ex);}
    finally {sending = false; send.disabled = !state.floor?.open;}
  });
  disclosure.append(recipient, windowInfo, noteForm, noteHistory); noteSection.append(disclosure); page.append(noteSection);
  const prior = el("section", "form-section"); prior.append(el("h2", "", "판사 에이전트의 판단 이력"));
  const rounds = el("div"); prior.append(rounds); page.append(prior); swap(page, "에이전트 협상");
  return room => {
    state = room;
    const active = room.mode === "fight", floor = room.floor;
    badge.textContent = room.mode === "done" ? "최종 결정" : floor ? "파이터 모드" : "조율 모드";
    const focus = fields[floor?.topic]?.label || "여행 조건";
    if (room.mode === "error") words.textContent = "진행이 멈췄어요. 아래 오류 내용을 확인해 주세요.";
    else if (room.mode === "done") words.textContent = "판사 에이전트의 최종 결정과 근거를 확인해 주세요.";
    else if (active) words.textContent = room.round + "회차 · 개인 에이전트가 " + focus + "에 대해 발언해요.";
    else if (floor) words.textContent = room.round + "회차 토론을 마쳤어요. 판사 에이전트가 전원의 최신 제안과 앞선 판단을 검토해요.";
    else if (room.events.some(event => event.kind === "proposal")) words.textContent = "판사 에이전트가 전원의 제안과 근거를 검토해요.";
    else words.textContent = "개인 에이전트가 각자의 조건을 검토하고 제안을 준비해요.";
    done.hidden = room.mode !== "done";
    const latestFight = room.events.filter(event => event.kind === "fight").at(-1);
    fightBox.hidden = !latestFight || room.mode === "done";
    if (latestFight) {
      fightTitle.textContent = latestFight.round + "회차 파이터 모드 " + (active ? "알림" : "기록");
      fightReason.textContent = latestFight.text;
      const key = "fight-seen:" + room.invite;
      if (read(key, 0) < latestFight.id) {
        save(key, latestFight.id);
        if (active) {announce(latestFight.speaker + ". " + latestFight.text); ring();}
      }
    }
    issue.hidden = !room.error;
    if (room.error) {issueText.textContent = room.error; resume.hidden = !room.can_retry;}
    const follow = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 32;
    const incoming = room.events.filter(item => item.id > shown);
    if (incoming.length) {
      const fragment = document.createDocumentFragment(); incoming.forEach(item => fragment.append(message(item))); log.append(fragment);
      if (follow || shown === 0) scroller.scrollTop = scroller.scrollHeight;
      else newer.hidden = false;
      if (shown && !incoming.some(e => e.kind === "fight")) {
        const latest = incoming.at(-1);
        announce(latest.speaker + ". " + latest.text);
      }
      shown = incoming.at(-1).id;
    }
    noteSection.hidden = !floor && !room.member.notes.length;
    const seconds = floor ? Math.max(0, Math.ceil(floor.deadline - room.server_time)) : 0;
    windowInfo.textContent = floor?.open ? "입력 열림 · 약 " + seconds + "초 남았어요. 수락된 지시는 발언 전에 처리돼요." : "이번 회차의 지시 입력이 마감됐어요.";
    editor.readOnly = !floor?.open; send.disabled = !floor?.open || sending;
    const changed = JSON.stringify(room.member.notes);
    if (changed !== noteDigest) {
      noteDigest = changed; noteHistory.replaceChildren(...room.member.notes.map(n => append(el("li"), el("p", "", n.text),
        el("span", "hint", n.round + "회차 · " + (n.handled ? "발언에 반영됨" : "전달됨 · 반영 대기")))));
    }
    if (room.history.length !== historyLength) {historyLength = room.history.length; rounds.replaceChildren(proposals(room.history));}
  };
}

function evidenceCards(evidence) {
  const box = el("div", "sources");
  if (!evidence.length) box.append(el("p", "muted", "이번 협상에서 조회한 외부 근거가 없어요."));
  for (const item of evidence) {
    const card = el("article", "source-card");
    card.append(el("h3", "", fields[item.field]?.label || "여행 정보"), el("p", "hint",
      (item.status === "observed" ? "출처 확인" : "확인 필요") + " · 조회 " + new Date(item.checked_at).toLocaleString("ko-KR")), el("p", "", item.reason));
    const mixed = item.sources.some(source => source.matched === true) && item.sources.some(source => source.matched !== true);
    for (const source of item.sources) {
      const status = mixed ? (source.matched === true ? " · 조건 확인" : " · 확인 필요") : "";
      const a = el("a", "source-link", source.title + status + " ↗"); a.href = source.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      card.append(a);
      if (source.excerpt) card.append(el("p", "source-excerpt", source.excerpt));
      if (source.quote) {
        const q = source.quote;
        card.append(el("p", "source-excerpt", "출처에서 관찰한 1인 왕복 운임 " + fmt(q) + " · " + q.origin + " → " + q.destination +
          " · " + fmt(q.dates) + " · 현지 " + q.time + " · " + q.terms));
      }
    }
    if (item.entry) {
      const entry = el("iframe", "search-entry");
      entry.title = "Google 검색 제안"; entry.loading = "lazy"; entry.referrerPolicy = "no-referrer";
      entry.setAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox"); entry.srcdoc = item.entry;
      card.append(entry);
    }
    box.append(card);
  }
  return box;
}

export function resultScreen(room) {
  const result = room.result, entries = result.entries;
  const page = shell("최종 여행안", "판사 에이전트가 전원의 의견을 검토해 내린 최종 결정이에요.", "조율 완료");
  const summary = el("section", "result-ticket");
  const dest = entries.destination;
  summary.append(el("p", "eyebrow", "우리의 여행지"), el("h2", "", fmt(dest.value)), el("p", "hint", decisionStatus(dest)));
  const quick = el("dl", "rows");
  for (const key of ["dates", "budget"]) quick.append(line(fields[key].label, fmt(entries[key].value) + " · " + decisionStatus(entries[key])));
  summary.append(quick); page.append(summary);
  const schedule = el("section", "form-section");
  schedule.append(el("h2", "", "날짜별 일정"));
  if (!result.itinerary.length) schedule.append(el("p", "muted", "확정할 수 있는 날짜별 세부 일정은 아직 미정이에요."));
  else for (const day of result.itinerary) {
    const place = (day.place || "미정") + (day.place_status === "verify" ? " · 세부 장소 확인 필요" : "");
    const activityLabel = {planned: "일정 반영", candidate: "후보 · 확인 필요"}[day.activity_status];
    const activity = [day.activity || "미정", activityLabel, day.activity_reason].filter(Boolean).join(" · ");
    const rows = el("dl", "rows"); rows.append(line("장소", place), line("이동", day.transport || "미정"), line("활동", activity));
    schedule.append(details(day.date + (day.place ? " · " + day.place : ""), rows));
  }
  page.append(schedule);
  const decisions = el("section", "form-section"); decisions.append(el("h2", "", "항목별 결정과 이유"));
  for (const [key, item] of Object.entries(entries)) {
    if (!fields[key]) continue;
    const row = el("article", "decision-row");
    row.append(append(el("div", "decision-head"), el("h3", "", fields[key].label), el("span", "tag", decisionStatus(item))),
      el("p", "decision-value", fmt(item.value)), el("p", "muted", decisionReason(item))); decisions.append(row);
  }
  page.append(decisions, details("검색 근거와 조회 시각", evidenceCards(result.evidence), result.evidence.some(e => e.status === "verify")),
    details("판사 에이전트의 판단 이력", proposals(room.history)));
  const history = el("ol", "chat-log"); room.events.forEach(e => history.append(message(e)));
  page.append(details("전체 공개 대화", history));
  if (room.member.notes.length) {
    const own = el("ol", "note-history");
    room.member.notes.forEach(n => own.append(append(el("li"), el("p", "", n.text), el("span", "hint", n.round + "회차 · " + (n.handled ? "반영됨" : "전달됨")))));
    page.append(details("내 에이전트에게 보낸 지시", own));
  }
  swap(page, "최종 여행안"); announce("판사 에이전트의 최종 여행안이 준비됐어요.");
}
