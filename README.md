# 🏠 Shared Apartment Hub

Private shared apartment application for **Tamir & Mikush**, expanding from the mobile plant watering tracker into a full apartment hub featuring live real-time grocery shopping, weekly meal planning, and automated ingredient aggregation.

---

## ✨ Features

- **🔒 Passcode Protection & Profile Switcher**:
  - Secure 30-day persistent HTTP-only session cookie via `APP_PASSCODE`.
  - Header profile switcher (`👤 Tamir` | `🌸 Mikush`) attributing all shopping, cooking, and watering activities.
  - Lightweight unauthenticated `/health` endpoint for uptime monitoring.
- **🌿 Plant Tracker (Preserved 100%)**:
  - Soil moisture dry-down progress bars, drinking velocity analysis, and push notification reminders.
- **🛒 Live Shared Grocery List**:
  - 4-second polling synchronization while shopping together (`document.visibilityState === 'visible'`).
  - Supermarket walk-through layout (Produce, Bakery, Meat/Fish, Dairy/Eggs, Pantry/Dry, Frozen, Household).
  - Pinned "Staples / Running Low" quick-bar for one-tap additions.
  - Offline `localStorage` caching so the list opens instantly even during Render cold starts.
  - Autocomplete from past items and 5-second toast "Undo" for accidental deletions or clears.
- **🍽️ Weekly Meal Planner & One-Tap Grocery Export**:
  - Weekly 7-day dinner planner with saved recipes library.
  - "Leftovers / 2x Batch" toggle to prevent redundant ingredient purchases.
  - **One-Tap Grocery Export**: Normalizes ingredient names and sums matching units (`onion 2 pcs + onion 1 pcs = onion 3 pcs`), preserving differing units (`g` vs `pcs`) without overwriting.
- **📲 Installable PWA**:
  - Standalone mobile app experience on Android and iOS with service worker caching.

---

## 🛠️ Environment Variables

Configure these in Render or your local `.env`:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | Supabase PostgreSQL URI (falls back to local SQLite if unset) | `sqlite:///plants_tracker.db` |
| `APP_PASSCODE` | Shared passcode required to unlock the apartment hub | `apartment123` |
| `SECRET_KEY` | HMAC cryptographic salt for session cookie tokens | *Random salt* |
| `PORT` | Web server listening port | `8000` |

---

## 🚀 Cloud Deployment (Render)

Render detects `render.yaml` automatically:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn plants_app:app --host 0.0.0.0 --port $PORT`
- In Render Dashboard under **Environment Variables**, add `APP_PASSCODE` with your chosen secret code.
