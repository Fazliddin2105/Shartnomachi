# apps/

- `web/` — web ilova (HTML/CSS/JS). Dizaynning asl nusxasi muallif kompyuterida alohida papkada tahrirlanadi;
  repodagi nusxani yangilash: `.\scripts\sync-frontend.ps1`.
  Backend uni `FRONTEND_DIR=../../apps/web` bilan http://localhost:8000/ da beradi, API klienti — `/sdk/lexlab-api.js`.
  `web/server.py` — dizayn bosqichidagi alohida prototip-server (8090-port); asosiy backend `services/api`.
- Keyingi bosqich: `admin/` (shablon va qoidalar CMS paneli), `mobile/`.

Backend API: `services/api` (OpenAPI: `http://localhost:8000/docs`).
