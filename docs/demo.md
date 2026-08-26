# TrafficMind AI demo

1. Start FastAPI and Streamlit with the commands in the README.
2. Open Command Center and point out the operational status, active vehicles, density, speed, incident, and predicted congestion.
3. Open Incidents to show the stalled vehicle evidence and recommendation.
4. Open AI Predictions to show the structured features behind the 87% prediction.
5. Open Signal Optimization to show the recommended 45/20 second plan and its simulation-only boundary.
6. Open Simulation Lab, choose `accident`, and run it. The baseline and AI-optimized wait values are calculated, with the resulting improvement shown beside them.
7. Open AI Traffic Agent and ask `Why is Junction 3 congested?` or `Which route should an emergency vehicle use?`. The response displays the tool selected before the grounded answer.

The stream is synthetic and is labelled accordingly. Video upload accepts a local file for inspection; model-backed bounding boxes require the future OpenCV/YOLO adapter.