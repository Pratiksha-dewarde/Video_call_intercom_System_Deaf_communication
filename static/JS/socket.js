/* ═══════════════════════════════════════════════════
   socket.js  — Fixed Version

   Fixes vs original:
   1. Buttons wired via onclick in HTML  (original never attached listeners)
   2. Role sent to server via  set_role  event
   3. Mic toggle is stateful (start / stop in one button)
   4. peer_left event handled  (remote video cleared)
   5. Chat empty-state cleared on first message
   6. setupPanel ↔ session transitions work correctly
═══════════════════════════════════════════════════ */

// ─── Socket ───────────────────────────────────────
const socket = io({ transports: ["websocket"] });

// ─── Global state ─────────────────────────────────
let userRole   = null;   // "deaf" | "normal"
let userLang   = "en";
let micActive  = false;

// ─── Setup panel ──────────────────────────────────

function selectRole(role) {
  userRole = role;

  document.getElementById("deafBtn").classList.toggle("selected",   role === "deaf");
  document.getElementById("normalBtn").classList.toggle("selected", role === "normal");
  document.getElementById("enterBtn").disabled = false;

  // update chat mode tag
  document.getElementById("chatMode").textContent =
    role === "deaf" ? "Sign → Text" : "Speech → Text";
}

function selectLang(lang) {
  userLang = lang;
  document.getElementById("langEn").classList.toggle("active", lang === "en");
  document.getElementById("langHi").classList.toggle("active", lang === "hi");
}

function enterSession() {
  if (!userRole) return;

  // tell server our role
  socket.emit("set_role", { role: userRole });
  socket.emit("set_language", { lang: userLang });

  // switch panels
  document.getElementById("setupPanel").style.display = "none";
  document.getElementById("session").style.display    = "flex";

  // show the right controls
  if (userRole === "deaf") {
    document.getElementById("signControls").style.display   = "flex";
    document.getElementById("localLabel").textContent       = "You (Deaf)";
    document.getElementById("signBadge").style.display      = "block";
    // hand_tracking.js will call initHandTracking() once camera is ready
  } else {
    document.getElementById("speechControls").style.display = "flex";
    document.getElementById("localLabel").textContent       = "You (Normal)";
  }

  // start camera (webrtc.js)
  initCamera();
}

// ─── Speech mic toggle ─────────────────────────────

function toggleSpeech() {
  const btn = document.getElementById("micBtn");

  if (!micActive) {
    socket.emit("start_speech");
    micActive = true;
    btn.classList.add("recording");
    btn.querySelector("span").textContent = "Stop Mic";
  } else {
    socket.emit("stop_speech");
    micActive = false;
    btn.classList.remove("recording");
    btn.querySelector("span").textContent = "Start Mic";
  }
}

// ─── Chat helpers ──────────────────────────────────

let lastText = "";

function appendMessage(text, type) {
  const chatBox = document.getElementById("chatBox");

  // remove placeholder
  const empty = chatBox.querySelector(".chat-empty");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = "message " + (type === "sign" ? "msg-deaf" : "msg-normal");
  div.textContent = text;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChat() {
  const chatBox = document.getElementById("chatBox");
  chatBox.innerHTML = '<div class="chat-empty">Messages will appear here once the call starts…</div>';
  lastText = "";
}

// ─── Socket events ─────────────────────────────────

socket.on("connect", () => {
  console.log("✅ Connected:", socket.id);
  const dot  = document.querySelector(".pulse-dot");
  const text = document.getElementById("statusText");
  dot.classList.add("connected");
  text.textContent = "Online";
});

socket.on("disconnect", () => {
  const dot  = document.querySelector(".pulse-dot");
  const text = document.getElementById("statusText");
  dot.classList.remove("connected");
  text.textContent = "Disconnected";
});

socket.on("server_info", (data) => {
  console.log("Server:", data.msg);
});

socket.on("peer_left", () => {
  console.log("Peer disconnected");
  const remVideo = document.getElementById("remoteVideo");
  if (remVideo) remVideo.srcObject = null;

  document.getElementById("noRemote").style.display    = "flex";
  document.getElementById("startCallBtn").style.display = "flex";
  document.getElementById("endCallBtn").style.display   = "none";

  document.getElementById("statusText").textContent = "Peer left";
});

// receive sign or speech result
socket.on("result", (data) => {
  const { text, type } = data;
  if (!text || text === lastText) return;
  lastText = text;
  appendMessage(text, type);
});
