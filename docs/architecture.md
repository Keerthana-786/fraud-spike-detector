# TrafficMind AI architecture

TrafficMind has four replaceable layers:

1. `src/traffic_service.py` is the deterministic domain layer for the local demo. It owns traffic snapshots, lane analytics, incident evidence, predictions, recommendations, simulation results, and agent tool routing.
2. `api/main.py` exposes the domain through FastAPI while retaining the existing Razorpay webhook API.
3. `app/traffic_dashboard.py` is the Streamlit command center. It consumes the same domain contracts and labels synthetic state clearly.
4. Future adapters can provide camera detections, weather, and SUMO results without changing the API response shape.

The intended production flow is:

```text
camera/video -> OpenCV/YOLO adapter -> tracker -> traffic analytics
-> incident and congestion models -> evidence-backed recommendations
-> browser/SUMO simulation -> measured baseline comparison
```

The current implementation completes the analytics-to-simulation slice with deterministic demo inputs. It does not claim to control physical signals.