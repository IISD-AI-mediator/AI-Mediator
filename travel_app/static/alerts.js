import {btn, read, save} from "./ui.js";

let audio;
function prime() {
  if (!read("fight-sound",true)) return;
  const Audio = window.AudioContext || window.webkitAudioContext;
  if (!Audio) return;
  try {
    audio ||= new Audio();
    if (audio.state === "suspended") audio.resume().catch(() => {});
  } catch {}
}
document.addEventListener("pointerdown",prime,{capture:true,passive:true});
document.addEventListener("keydown",prime,true);

export function ring() {
  if (!read("fight-sound",true) || audio?.state !== "running") return;
  [660,880].forEach((frequency,index) => {
    const oscillator = audio.createOscillator(), volume = audio.createGain();
    const start = audio.currentTime + index * .17;
    oscillator.frequency.value = frequency;
    volume.gain.setValueAtTime(.001,start); volume.gain.exponentialRampToValueAtTime(.075,start+.018);
    volume.gain.exponentialRampToValueAtTime(.001,start+.14);
    oscillator.connect(volume); volume.connect(audio.destination); oscillator.start(start); oscillator.stop(start+.15);
  });
}
export function soundControl() {
  const button = btn("",() => {
    const enabled = !read("fight-sound",true);
    save("fight-sound",enabled); update();
    if (enabled) {prime(); if (audio) audio.resume().then(ring).catch(() => {});}
  },"quiet sound-toggle");
  function update() {
    const enabled = read("fight-sound",true);
    button.textContent = enabled ? "파이트 알림음 켜짐" : "파이트 알림음 꺼짐";
    button.setAttribute("aria-pressed",String(enabled));
  }
  update(); return button;
}
