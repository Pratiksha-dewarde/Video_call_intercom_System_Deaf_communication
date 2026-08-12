/* ═══════════════════════════════════════════════════════════
   hand_tracking.js  —  MediaPipe HOLISTIC (matches realtime.py)

   Sends every frame:
   socket.emit("holistic_landmarks", {
     pose:       [{x,y,z}, ...]   33 points
     left_hand:  [{x,y,z}, ...]   21 points  ([] if absent)
     right_hand: [{x,y,z}, ...]   21 points  ([] if absent)
   })

   Also draws the hand skeleton overlay on the canvas so the
   deaf user can see the MediaPipe tracking in real time.
═══════════════════════════════════════════════════════════ */

let holisticModel = null;
let mpCamera      = null;
let trackingActive = false;

const handCanvas = document.getElementById("handCanvas");
const handCtx    = handCanvas.getContext("2d");

// ── Called from webrtc.js after getUserMedia resolves ─────────
function initHandTracking() {
    if (userRole !== "deaf") return;
    if (trackingActive)      return;

    const videoEl = document.getElementById("localVideo");

    holisticModel = new Holistic({
        locateFile: (file) =>
            `https://cdn.jsdelivr.net/npm/@mediapipe/holistic@0.5/${file}`
    });

    holisticModel.setOptions({
        modelComplexity:        1,
        smoothLandmarks:        true,
        minDetectionConfidence: 0.5,
        minTrackingConfidence:  0.5
    });

    holisticModel.onResults(onHolisticResults);

    mpCamera = new Camera(videoEl, {
        onFrame: async () => {
            if (holisticModel) {
                await holisticModel.send({ image: videoEl });
            }
        },
        width:  640,
        height: 480
    });

    mpCamera.start();
    trackingActive = true;
    console.log("Holistic tracking started");
}

// ── Results callback ──────────────────────────────────────────
function onHolisticResults(results) {
    // Size canvas to match the video element's display size
    handCanvas.width  = handCanvas.offsetWidth  || 640;
    handCanvas.height = handCanvas.offsetHeight || 480;

    handCtx.clearRect(0, 0, handCanvas.width, handCanvas.height);

    const signBadge = document.getElementById("signBadge");
    const hasHands  = results.leftHandLandmarks || results.rightHandLandmarks;

    if (!hasHands) {
        signBadge.style.display = "none";
    } else {
        signBadge.style.display = "block";
    }

    // ── Draw hand skeleton on canvas overlay ────────────────
    if (results.leftHandLandmarks && typeof drawConnectors === "function") {
        drawConnectors(handCtx, results.leftHandLandmarks, HAND_CONNECTIONS, {
            color: "#00d4aa", lineWidth: 2
        });
        drawLandmarks(handCtx, results.leftHandLandmarks, {
            color: "#ff4f6d", lineWidth: 1, radius: 3
        });
    }

    if (results.rightHandLandmarks && typeof drawConnectors === "function") {
        drawConnectors(handCtx, results.rightHandLandmarks, HAND_CONNECTIONS, {
            color: "#00d4aa", lineWidth: 2
        });
        drawLandmarks(handCtx, results.rightHandLandmarks, {
            color: "#ff4f6d", lineWidth: 1, radius: 3
        });
    }

    // ── Build plain serialisable landmark object ─────────────
    // Exactly mirrors how realtime.py builds its 225-feature vector.

    const toLmArray = (lmList) => {
        if (!lmList) return [];
        return lmList.map(lm => ({ x: lm.x, y: lm.y, z: lm.z }));
    };

    const payload = {
        pose:       toLmArray(results.poseLandmarks),
        left_hand:  toLmArray(results.leftHandLandmarks),
        right_hand: toLmArray(results.rightHandLandmarks)
    };

    // Only send if at least pose was detected
    if (payload.pose.length > 0) {
        socket.emit("holistic_landmarks", payload);
    }
}

// ── Cleanup ───────────────────────────────────────────────────
function stopHandTracking() {
    if (mpCamera) {
        mpCamera.stop();
        mpCamera = null;
    }
    trackingActive = false;
    handCtx.clearRect(0, 0, handCanvas.width, handCanvas.height);
    document.getElementById("signBadge").style.display = "none";
    console.log("Holistic tracking stopped");
}
