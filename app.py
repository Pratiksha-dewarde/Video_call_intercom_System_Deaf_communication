import eventlet
eventlet.monkey_patch()

# ═══════════════════════════════════════════════════════════════
#  app.py  —  SignBridge Intercom Server
#
#  Sign pipeline matches realtime.py exactly:
#    • MediaPipe Holistic  (browser)  →  pose(33) + left_hand(21) + right_hand(21) = 225 landmarks
#    • normalize()  →  shoulder-width normalisation
#    • 60-frame resampled sequence  →  best_model.h5
#    • Labels from labels_dynamic.txt
#
#  Speech pipeline:
#    • Vosk offline  →  EN / HI
# ═══════════════════════════════════════════════════════════════

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import numpy as np
import json
from collections import deque, Counter

# ───────────────────────────────────────────────────────────────
#  DYNAMIC SIGN MODEL  (best_model.h5  +  labels_dynamic.txt)
# ───────────────────────────────────────────────────────────────
sign_model  = None
sign_labels = []

try:
    import tensorflow as tf
    print("Loading sign model (best_model.h5) ...")
    sign_model = tf.keras.models.load_model("models/best_model.h5")
    print("Sign model loaded")
except Exception as e:
    print(f"Sign model not loaded: {e}")

try:
    with open("models/labels_dynamic.txt", "r") as f:
        for line in f:
            parts = line.strip().split(maxsplit=1)
            if len(parts) > 1:
                sign_labels.append(parts[1])
    print(f"Labels loaded: {sign_labels}")
except Exception as e:
    print(f"Labels not loaded: {e}")

# ───────────────────────────────────────────────────────────────
#  NORMALISATION  —  identical to realtime.py / extract.py
# ───────────────────────────────────────────────────────────────
SEQUENCE_LENGTH   = 60
BUFFER_SIZE       = 90
CONFIDENCE_THRESH = 0.75
VOTE_WINDOW       = 5
PREDICT_EVERY     = 10

def normalize(landmarks):
    lm      = landmarks.copy()
    ref_idx = 15 * 3
    ref     = lm[ref_idx: ref_idx + 3].copy()
    if np.all(ref == 0):
        ref = lm[0:3].copy()
    for i in range(0, len(lm), 3):
        lm[i]   -= ref[0]
        lm[i+1] -= ref[1]
        lm[i+2] -= ref[2]
    ls    = np.array([lm[11*3], lm[11*3+1], lm[11*3+2]])
    rs    = np.array([lm[12*3], lm[12*3+1], lm[12*3+2]])
    scale = np.linalg.norm(ls - rs)
    if scale > 1e-5:
        lm = lm / scale
    return lm

# ───────────────────────────────────────────────────────────────
#  PER-SESSION STATE  (each socket = own buffer)
# ───────────────────────────────────────────────────────────────
class SessionState:
    def __init__(self):
        self.frame_buffer = deque(maxlen=BUFFER_SIZE)
        self.vote_buffer  = deque(maxlen=VOTE_WINDOW)
        self.frame_count  = 0
        self.last_output  = ""

session_states = {}

# ───────────────────────────────────────────────────────────────
#  FLASK + SOCKET.IO
# ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "intercom-secret-2024"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

ROOM = "intercom_room"

@app.route("/")
def index():
    return render_template("index.html")

# ───────────────────────────────────────────────────────────────
#  CONNECTION LIFECYCLE
# ───────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    sid = request.sid
    session_states[sid] = SessionState()
    join_room(ROOM, sid=sid)
    print(f"Connected  {sid}")
    emit("server_info", {"msg": "Connected", "sid": sid})

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    session_states.pop(sid, None)
    leave_room(ROOM, sid=sid)
    print(f"Disconnected  {sid}")
    emit("peer_left", {}, room=ROOM, include_self=False)

@socketio.on("set_role")
def on_set_role(data):
    print(f"Role set: {request.sid} -> {data.get('role')}")
    emit("role_confirmed", {"role": data.get("role", "normal")})

# ───────────────────────────────────────────────────────────────
#  WEBRTC SIGNALING
# ───────────────────────────────────────────────────────────────
@socketio.on("offer")
def on_offer(data):
    emit("offer", data, room=ROOM, include_self=False)

@socketio.on("answer")
def on_answer(data):
    emit("answer", data, room=ROOM, include_self=False)

@socketio.on("candidate")
def on_candidate(data):
    emit("candidate", data, room=ROOM, include_self=False)

@socketio.on("end_call")
def on_end_call():
    emit("peer_left", {}, room=ROOM, include_self=False)
    print(f"Call ended by {request.sid}")

# ───────────────────────────────────────────────────────────────
#  SIGN LANGUAGE — holistic landmarks from browser
#
#  Browser sends every frame:
#  {
#    "pose":       [{x,y,z}, ...]   33 items
#    "left_hand":  [{x,y,z}, ...]   21 items (empty [] if not detected)
#    "right_hand": [{x,y,z}, ...]   21 items (empty [] if not detected)
#  }
# ───────────────────────────────────────────────────────────────
@socketio.on("holistic_landmarks")
def on_holistic_landmarks(data):
    if sign_model is None or not sign_labels:
        return

    sid   = request.sid
    state = session_states.get(sid)
    if state is None:
        return

    try:
        vec = np.zeros(225, dtype=np.float32)

        for i, lm in enumerate(data.get("pose", [])):
            if i >= 33: break
            vec[i*3]     = lm["x"]
            vec[i*3 + 1] = lm["y"]
            vec[i*3 + 2] = lm["z"]

        for i, lm in enumerate(data.get("left_hand", [])):
            if i >= 21: break
            vec[99 + i*3]     = lm["x"]
            vec[99 + i*3 + 1] = lm["y"]
            vec[99 + i*3 + 2] = lm["z"]

        for i, lm in enumerate(data.get("right_hand", [])):
            if i >= 21: break
            vec[162 + i*3]     = lm["x"]
            vec[162 + i*3 + 1] = lm["y"]
            vec[162 + i*3 + 2] = lm["z"]

        vec = normalize(vec)
        state.frame_buffer.append(vec)
        state.frame_count += 1

        if (len(state.frame_buffer) >= SEQUENCE_LENGTH and
                state.frame_count % PREDICT_EVERY == 0):

            buf     = np.array(state.frame_buffer)
            indices = np.linspace(0, len(buf) - 1, SEQUENCE_LENGTH).astype(int)
            seq     = buf[indices]

            input_data    = np.expand_dims(seq, axis=0).astype(np.float32)
            probs         = sign_model(input_data, training=False).numpy()[0]
            predicted_idx = int(np.argmax(probs))
            confidence    = float(probs[predicted_idx])

            if confidence >= CONFIDENCE_THRESH:
                state.vote_buffer.append(predicted_idx)

                if len(state.vote_buffer) == VOTE_WINDOW:
                    best_idx = Counter(state.vote_buffer).most_common(1)[0][0]
                    word     = sign_labels[best_idx]
                    state.vote_buffer.clear()

                    if word != state.last_output:
                        state.last_output = word
                        print(f"Sign detected: {word}  ({confidence*100:.0f}%)")
                        emit("result", {"text": word, "type": "sign"}, room=ROOM)

    except Exception as e:
        print(f"Landmark error: {e}")

# ───────────────────────────────────────────────────────────────
#  SPEECH (Vosk)
# ───────────────────────────────────────────────────────────────
try:
    from ai_modules.speech import start_speech, stop_speech, set_language
    SPEECH_OK = True
except Exception as e:
    SPEECH_OK = False
    print(f"Speech module unavailable: {e}")
    def start_speech(s): pass
    def stop_speech():   pass
    def set_language(l): pass

@socketio.on("start_speech")
def on_start_speech():
    print("Start speech")
    start_speech(socketio)

@socketio.on("stop_speech")
def on_stop_speech():
    print("Stop speech")
    stop_speech()

@socketio.on("set_language")
def on_set_language(data):
    lang = data.get("lang", "en")
    print(f"Language: {lang}")
    set_language(lang)

# ───────────────────────────────────────────────────────────────
#  RUN
# ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Intercom server  ->  http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
