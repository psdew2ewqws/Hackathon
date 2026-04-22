# Open-Source Components Inventory

Phase 3 is built almost entirely on open-source libraries. The single
license item that needs attention before any commercial deployment is
**Ultralytics YOLO (AGPL-3.0)** — see the callout at the bottom.

## License table

| Component                 | License                     | Role in the stack                              |
|---------------------------|-----------------------------|------------------------------------------------|
| ultralytics               | AGPL-3.0                    | YOLO + ByteTrack tracker backbone              |
| supervision               | MIT                         | Helper utilities around detection/tracking     |
| opencv-python-headless    | Apache-2.0                  | RTSP capture, drawing, JPEG encoding           |
| FastAPI                   | MIT                         | HTTP + WebSocket server framework              |
| Starlette                 | MIT                         | ASGI primitives used by FastAPI                |
| uvicorn                   | BSD-3-Clause                | ASGI server running the app                    |
| websockets                | BSD-3-Clause                | WebSocket support (via uvicorn)                |
| numpy                     | BSD-3-Clause                | Array math, zone polygons                      |
| pandas                    | BSD-3-Clause                | Feature frames, parquet IO                     |
| pyarrow                   | Apache-2.0                  | Parquet reader for detector counts             |
| LightGBM                  | MIT                         | Demand forecasting (4 horizons)                |
| PyJWT                     | MIT                         | HS256 token mint/verify                        |
| bcrypt                    | Apache-2.0                  | Password hashing                               |
| MediaMTX                  | MIT                         | RTSP server (single binary)                    |
| ffmpeg                    | LGPL-2.1+ (some GPL parts)  | Loops archived mp4 into MediaMTX               |
| React + React-DOM         | MIT                         | SPA runtime                                    |
| react-router-dom          | MIT                         | Client-side routing (7 dashboard pages)        |
| Vite                      | MIT                         | Dev server + build bundler                     |
| TypeScript                | Apache-2.0                  | Typed frontend sources                         |

Dev-only tooling (pytest, ruff, eslint, typescript-eslint) is additionally
MIT/BSD and does not ship with the deployed bundle.

## Ultralytics AGPL — commercial deployment notice

`ultralytics` (and the YOLO model weights distributed with it) are licensed
under **AGPL-3.0**. The AGPL's §13 network clause means that operating the
dashboard over a network for third parties counts as "conveying" the
combined work, which triggers the source-availability obligation for the
entire dashboard — not just the tracker shim.

Operators have two compliant options before shipping commercially:

1. **Open-source the entire dashboard** (frontend, backend, configs,
   deployment glue) under AGPL-3.0 and make the source reachable from the
   running UI.
2. **Purchase an Ultralytics Enterprise License** which removes the AGPL
   constraint for that specific deployment. Contact Ultralytics directly;
   the license is per-deployment.

A third escape hatch is to **swap out the detector** for an
Apache/MIT-licensed alternative (e.g. a BSD-licensed YOLOv5 fork, Detectron2,
or a custom ONNX model). The tracker interface in `tracker.py` only needs
`model.track(frame, ..., classes=list(VEHICLE_CLASSES))` to return a
results object with `boxes.xyxy` and `boxes.id`, so the integration point
is narrow.

All other components in the table above are permissively licensed
(MIT/BSD/Apache) and impose only attribution requirements. FFmpeg ships
with both LGPL and GPL components; the stack only uses the libavformat /
libavcodec bits for RTSP publishing and copy-codec remuxing, which is
LGPL-covered usage — but redistributors should still audit the specific
FFmpeg build they ship alongside the binaries.
