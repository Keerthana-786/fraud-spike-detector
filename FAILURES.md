# SentinelPay Engineering Postmortem: Cold-Start Baseline & Zero-Variance Anomaly State

**Incident / Defect Classification**: Algorithmic Edge Case & Cold-Start Failure  
**Component Affected**: Statistical Risk Density Spike Detector (`src/live_pipeline.py`, `src/spike_detector.py`)  
**Impact**: Silent suppression of critical fraud alerts during early merchant lifecycle or initial zero-variance baseline periods.

---

## 1. What Broke

SentinelPay detects merchant fraud attacks by computing a rolling trailing Z-score on fraud risk density:

$$Z = \frac{\text{Current Fraud Density} - \mu_{\text{baseline}}}{\sigma_{\text{baseline}}}$$

During the system's development, when a new merchant account was provisioned or when monitoring a newly active payment segment (e.g. UPI transactions on Android), fewer than the required 12 hourly trailing buckets existed. 

In this cold-start state:
1. **Undefined Standard Deviation ($\sigma = \text{NaN}$ or $0$)**: When all preceding historical buckets had exactly 0 fraud transactions, $\sigma_{\text{baseline}} = 0$.
2. **Division-by-Zero / Zero-Score Suppression**: Computing $(rate - 0) / 0$ produced either Python `ZeroDivisionError` or was coerced to $Z = 0.0$.
3. **Suppressed Detection**: When a real coordinated fraud wave hit a brand-new merchant account, the spike detector saw $Z = 0.0 < 3.0\sigma$ and completely failed to trigger an alert, allowing high-risk attack traffic to pass unmitigated.

---

## 2. How I Noticed

While executing controlled fraud injection tests against a newly instantiated SQLite store with no prior traffic history:
- The ML classifier correctly scored the injected transactions as **HIGH** ($p > 0.90$).
- The hourly bucket correctly registered a surge in suspicious transaction count ($>30$) and fraud density ($>85\%$).
- However, **no incident was created** in the Incident Operations Center (`spike_alerts` remained empty), and the dashboard displayed `Historical Baseline: Insufficient history`.
- The system remained in a state of false security because the statistical test required historical variance before it was willing to declare an anomaly.

---

## 3. What I Changed

We engineered a robust **Dual-Guard Cold-Start & Zero-Variance Anomaly Architecture**:

1. **Zero-Variance Anomaly Jump Override (`src/live_pipeline.py` & `src/spike_detector.py`)**:
   When trailing variance is zero ($\sigma \le 10^{-9}$) but the current bucket exhibits a significant volume jump with suspicious transactions ($\text{suspicious} \ge 3$ and $\text{rate} \ge 5\%$), the engine automatically assigns a statistically significant anomaly score ($Z = Z_{\text{threshold}} + 2.0 = 5.0\sigma$) rather than defaulting to zero.

   ```python
   if baseline is None:
       z_score = 0.0
   elif stddev is not None and stddev > 1e-9:
       z_score = (rate - baseline) / stddev
   elif rate > baseline and suspicious >= 3:
       # Zero-variance jump with confirmed suspicious volume triggers immediate anomaly
       z_score = zscore_threshold + 2.0
   else:
       z_score = 0.0
   ```

2. **Explicit Cold-Start Telemetry in UI (`web/src/pages/Dashboard.tsx`)**:
   Instead of masking errors with empty numbers or `0.00%`, the UI now explicitly indicates `Insufficient history (rolling window building)` when buckets $< 12$, alerting merchant analysts that baseline calibration is in progress.

3. **Fallback Density Guard**:
   Added a deterministic minimum absolute fraud count requirement ($\text{suspicious} \ge 3$) and volume threshold ($\text{total} \ge 20$) to prevent single-transaction nighttime noise from triggering false alerts.

---

## 4. What I'd Do Differently

If building this from scratch again for high-scale merchant rails:

1. **Bayesian Empirical Priors**:
   Instead of requiring a 12-hour cold-start accumulation per merchant, initialize new merchants with an empirical Bayesian prior derived from global merchant category code (MCC) benchmarks (e.g. baseline density $\alpha=1, \beta=120$). This eliminates the cold-start window entirely.
2. **Adaptive Bucket Granularity**:
   Switch dynamically between 15-minute, hourly, and daily bucket resolutions based on real-time transaction velocity, allowing high-throughput merchants to achieve statistical stability within minutes instead of hours.
3. **Automated Shadow Anomaly Testing**:
   Implement automated CI tests that simulate instant zero-baseline attack scenarios on every model build to ensure zero-variance safety guarantees are never regressed.

---
*Documented as part of the Razorpay AI Buildathon (Track 02: AI Risk Manager).*
