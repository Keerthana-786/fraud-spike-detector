# SentinelPay API

All traffic endpoints are served by the FastAPI app at `http://localhost:8000`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | API and database readiness |
| POST | `/api/auth/register` | Create a Risk Analyst account |
| POST | `/api/auth/login` | Start a session |
| GET | `/api/dashboard/overview` | Live overview metrics |
| GET | `/api/transactions` | Scored transaction records |
| GET | `/api/alerts` | Fraud spike alerts |
| POST | `/api/alerts/{alert_id}/investigate` | Record an investigation decision |
| GET | `/api/metrics/financial` | Financial impact metrics |
| GET | `/api/model/health` | Model readiness and offline evaluation |
| POST | `/api/simulator/normal` | Generate controlled normal traffic |
| POST | `/api/simulator/spike` | Generate a controlled fraud spike |
| POST | `/webhooks/razorpay` | Receive signed Razorpay Test Mode events |

The service is defense-only. Razorpay credentials remain server-side, webhook signatures are checked against the raw body, and unavailable model or email services are reported without fabricating success.