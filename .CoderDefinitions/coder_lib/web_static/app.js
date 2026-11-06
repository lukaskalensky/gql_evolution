"use strict";

const TOKEN_KEY = "coder-token";
const CLOSE_UNAUTHORIZED = 4401;
const TOOL_LABELS = {
  read_file: "Čtení",
  write_file: "Zápis",
  edit_file: "Úprava",
  list_files: "Složka",
  grep: "Hledání",
  shell: "Příkaz",
  delegate_task: "Podúkol",
};

const $ = (id) => document.getElementById(id);
const log = $("log");
const input = $("input");

let socket = null;
let reconnectDelay = 1000;
let running = false;
let canContinue = false;
let gitEnabled = false;
let startedAt = 0;
let toolCount = 0;
let pendingUndoCommit = null;
let confirmAction = null;
let textBlocks = new Map();
let toolBlocks = new Map();
let confirmBlocks = new Map();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function isNearBottom() {
  return log.scrollHeight - log.scrollTop - log.clientHeight < 80;
}

function append(node) {
  const stick = isNearBottom();
  log.append(node);
  $("empty").hidden = true;
  if (stick) log.scrollTop = log.scrollHeight;
}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

/* --- Vykreslení událostí ------------------------------------------------ */

function diffLines(parent, oldText, newText) {
  const pre = element("pre");
  for (const [text, sign, cls] of [[oldText, "-", "del"], [newText, "+", "add"]]) {
    if (!text) continue;
    for (const line of text.split("\n")) pre.append(element("span", `line ${cls}`, `${sign} ${line}`));
  }
  parent.append(pre);
}

function renderToolCall(event) {
  const details = element("details", "tool");
  const summary = element("summary");
  summary.append(
    element("span", "label", TOOL_LABELS[event.name] || event.name),
    element("span", "target truncate", event.target),
    element("span", "state", event.valid ? "běží…" : "neplatné argumenty"),
  );
  const body = element("div", "body");
  if (event.command) body.append(element("pre", "", event.command));
  if (event.content) body.append(element("pre", "", event.content));
  for (const edit of event.edits || []) diffLines(body, edit.old, edit.new);
  details.append(summary, body);
  details.open = Boolean(event.edits && event.edits.length);
  if (!event.valid) details.classList.add("failed");
  if (event.id) toolBlocks.set(event.id, details);
  append(details);
}

function renderToolResult(event) {
  const details = toolBlocks.get(event.id);
  if (!details) return;
  const problem = event.failed || event.denied;
  let state = "hotovo";
  if (event.denied) state = "zablokováno";
  else if (event.failed) state = event.exit_code ? `selhalo (kód ${event.exit_code})` : "selhalo";
  details.querySelector(".state").textContent = state;
  details.classList.toggle("failed", problem);
  if (event.text) details.querySelector(".body").append(element("pre", "", event.text));
  if (problem) details.open = true;
}

function renderText(event) {
  const stick = isNearBottom();
  let block = textBlocks.get(event.id);
  if (!block) {
    block = element("div", "assistant");
    textBlocks.set(event.id, block);
    log.append(block);
    $("empty").hidden = true;
  }
  block.innerHTML = event.html; // Markdown vykreslený serverem: HTML z modelu je escapované
  if (stick) log.scrollTop = log.scrollHeight;
}

function renderConfirm(event) {
  if (confirmBlocks.has(event.id)) return;
  const card = element("section", "confirm");
  card.append(
    element("h3", "", `Nebezpečný příkaz: ${event.reason}`),
    element("pre", "", event.command),
  );
  const actions = element("div", "dialog-actions");
  const allow = element("button", "danger", "Povolit");
  const deny = element("button", "", "Zamítnout");
  allow.type = deny.type = "button";
  allow.addEventListener("click", () => send({ type: "confirm", id: event.id, ok: true }));
  deny.addEventListener("click", () => send({ type: "confirm", id: event.id, ok: false }));
  actions.append(deny, allow);
  card.append(actions);
  confirmBlocks.set(event.id, card);
  append(card);
  updateStatus();
  deny.focus();
}

function renderEvent(event) {
  switch (event.type) {
    case "user": append(element("div", "user", event.text)); break;
    case "text": renderText(event); break;
    case "tool_call": toolCount += 1; renderToolCall(event); break;
    case "tool_result": renderToolResult(event); break;
    case "notice": append(element("div", `notice ${event.level}`, event.text)); break;
    case "usage":
      append(element("div", "usage",
        `${event.requests} požadavků · ${event.input} / ${event.output} tokenů · ${event.seconds} s`));
      break;
    default: break;
  }
}

function resetLog() {
  textBlocks = new Map();
  toolBlocks = new Map();
  confirmBlocks = new Map();
  const empty = $("empty");
  log.replaceChildren(empty);
}

/* --- Stav ---------------------------------------------------------------- */

function updateControls() {
  const connected = socket && socket.readyState === WebSocket.OPEN;
  $("btn-stop").hidden = !running;
  $("btn-send").hidden = running;
  $("btn-send").disabled = !connected;
  $("btn-send").textContent = canContinue && !input.value.trim() ? "Pokračovat" : "Odeslat";
  $("btn-undo").disabled = !connected || running || !gitEnabled;
  $("btn-undo").title = gitEnabled ? "" : "Vyžaduje git repozitář";
  $("btn-clear").disabled = !connected || running;
  $("btn-diff").disabled = !connected;
  $("btn-plan").disabled = !connected;
}

function updateStatus() {
  const status = $("status");
  status.hidden = !running;
  if (running) {
    const seconds = Math.round((performance.now() - startedAt) / 1000);
    const tools = toolCount ? ` · nástrojů: ${toolCount}` : "";
    const activity = confirmBlocks.size ? "Čeká na vaše potvrzení" : "Model pracuje";
    status.textContent = `${activity}… ${seconds} s${tools}`;
  }
}

function applyState(state) {
  const wasRunning = running;
  running = state.running;
  canContinue = state.can_continue;
  gitEnabled = state.git;
  if (running) startedAt = performance.now() - state.elapsed * 1000;
  if (running && !wasRunning) toolCount = 0;
  updateControls();
  updateStatus();
  if (wasRunning && !running) input.focus();
}

function handleInit(message) {
  resetLog();
  $("workspace").textContent = message.workspace;
  $("workspace").title = message.workspace;
  $("model").textContent = message.model;
  $("model").title = message.model;
  $("empty").hidden = message.events.length > 0;
  if (message.warning) append(element("div", "notice warning", message.warning));
  message.events.forEach(renderEvent);
  message.confirms.forEach(renderConfirm);
  running = false;
  toolCount = 0;
  applyState(message.state);
  log.scrollTop = log.scrollHeight;
}

function openPanel(title, text, isDiff) {
  $("panel-title").textContent = title;
  const body = $("panel-body");
  body.replaceChildren();
  if (isDiff) {
    for (const line of text.split("\n")) {
      let cls = "";
      if (line.startsWith("+") && !line.startsWith("+++")) cls = "add";
      else if (line.startsWith("-") && !line.startsWith("---")) cls = "del";
      body.append(element("span", `line ${cls}`, line || " "));
    }
  } else {
    body.textContent = text;
  }
  if (!$("panel").open) $("panel").showModal();
}

function askConfirm({ title, text, items, okLabel, onConfirm }) {
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = text;
  const list = $("confirm-list");
  list.replaceChildren(...(items || []).map((item) => element("li", "", item)));
  list.hidden = !(items && items.length);
  $("confirm-ok").textContent = okLabel;
  confirmAction = onConfirm;
  $("confirm-dialog").showModal();
  $("confirm-cancel").focus();
}

function handleMessage(message) {
  switch (message.type) {
    case "init": handleInit(message); break;
    case "state": applyState(message); break;
    case "tick": toolCount = message.tools; updateStatus(); break;
    case "confirm": renderConfirm(message); break;
    case "confirm_done": {
      const card = confirmBlocks.get(message.id);
      if (card) card.remove();
      confirmBlocks.delete(message.id);
      updateStatus();
      break;
    }
    case "panel": openPanel(message.title, message.text, message.diff); break;
    case "undo_preview":
      pendingUndoCommit = message.commit;
      askConfirm({
        title: `Vrátit krok #${message.step}?`,
        text: message.changes.length
          ? "Soubory i konverzace se vrátí do stavu před tímto krokem. Tyto změny budou ztraceny:"
          : "Soubory se od tohoto kroku nezměnily, vrátí se jen konverzace.",
        items: message.changes.map(([action, path]) => `${action}: ${path}`),
        okLabel: "Vrátit",
        onConfirm: () => send({ type: "undo_confirm", commit: pendingUndoCommit }),
      });
      break;
    default: renderEvent(message);
  }
}

/* --- Spojení -------------------------------------------------------------- */

function readToken() {
  const match = location.hash.match(/token=([^&]+)/);
  if (match) {
    sessionStorage.setItem(TOKEN_KEY, decodeURIComponent(match[1]));
    history.replaceState(null, "", location.pathname); // token nemá zůstat v adresním řádku
  }
  return sessionStorage.getItem(TOKEN_KEY);
}

function setConnection(text, offline) {
  $("connection").textContent = text;
  $("connection").classList.toggle("offline", offline);
}

function connect() {
  const token = readToken();
  if (!token) {
    setConnection("Nepřipojeno", true);
    if (!$("token-dialog").open) $("token-dialog").showModal();
    return;
  }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ type: "auth", token }));
    reconnectDelay = 1000;
    setConnection("Připojeno", false);
    updateControls();
  });
  socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
  socket.addEventListener("close", (event) => {
    updateControls();
    if (event.code === CLOSE_UNAUTHORIZED) {
      sessionStorage.removeItem(TOKEN_KEY);
      connect();
      return;
    }
    setConnection("Odpojeno, připojuji znovu…", true);
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 8000);
  });
}

/* --- Ovládání ------------------------------------------------------------- */

function autosize() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight + 2}px`;
}

function submit() {
  const text = input.value.trim();
  if (running || !socket || socket.readyState !== WebSocket.OPEN) return;
  if (!text && !canContinue) return;
  send({ type: "send", text });
  input.value = "";
  autosize();
  updateControls();
  log.scrollTop = log.scrollHeight;
}

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  submit();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
});
input.addEventListener("input", () => {
  autosize();
  updateControls();
});

$("btn-stop").addEventListener("click", () => send({ type: "stop" }));
$("btn-diff").addEventListener("click", () => send({ type: "diff" }));
$("btn-plan").addEventListener("click", () => send({ type: "plan" }));
$("btn-undo").addEventListener("click", () => send({ type: "undo_preview" }));
$("btn-clear").addEventListener("click", () => askConfirm({
  title: "Začít novou konverzaci?",
  text: "Smaže se historie konverzace, PROGRESS.md a plán. Soubory projektu se nemění. Tuto akci nejde vrátit.",
  okLabel: "Smazat a začít znovu",
  onConfirm: () => send({ type: "clear" }),
}));

$("panel-close").addEventListener("click", () => $("panel").close());
$("confirm-cancel").addEventListener("click", () => $("confirm-dialog").close());
$("confirm-ok").addEventListener("click", () => {
  $("confirm-dialog").close();
  if (confirmAction) confirmAction();
  confirmAction = null;
});
$("token-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = $("token-input").value.trim();
  if (!value) return;
  sessionStorage.setItem(TOKEN_KEY, value);
  $("token-input").value = "";
  $("token-dialog").close();
  connect();
});

// Odkazy z odpovědí modelu se otevírají mimo tuto stránku a bez přístupu k ní
log.addEventListener("click", (event) => {
  const link = event.target.closest(".assistant a");
  if (link) {
    event.preventDefault();
    window.open(link.href, "_blank", "noopener,noreferrer");
  }
});

setInterval(updateStatus, 1000);
updateControls();
connect();
input.focus();
