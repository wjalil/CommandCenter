# 🍪 CookieOps — Operations Command Center for Small Business Mastery

**CookieOps** is a lightweight, modular operations platform designed to power small businesses with the same operational precision as top-tier enterprises — without the overhead.

Originally built to streamline the shift and task workflows for a fast-scaling NYC cookie & catering business, CookieOps is now a flexible backend engine that helps local businesses manage:

✅ Shift Scheduling  
✅ Task Checklists with Submissions  
✅ Role-Based Dashboards (Admin & Worker)  
✅ SOP & Recipe Document Repository  
✅ Custom Modules for Inventory, Driver Routing, Fridge Checks, Invoicing & More  

---

### 🧠 Why CookieOps?

Most small businesses rely on duct-taped systems — group chats, printouts, text reminders, and clunky POS tools. CookieOps replaces the chaos with:

- **Clarity** — Workers see exactly what’s expected each shift  
- **Accountability** — Task submissions include timestamps, photos, and text input  
- **Control** — Admins can assign shifts, auto-attach task templates, and view summaries  
- **Customization** — Add custom workflows that plug into your operations (e.g. driver logs, daily fridge photo checks, vending refunds, inventory reorder triggers)

---

### 🧱 Modular Architecture

CookieOps is built to scale **with** your business. The backend is modular — meaning you can build and plug in new custom modules without rewriting core logic.

Some modules currently in use:

- 🧊 **Fridge Check Module** — Workers submit daily fridge photo + notes  
- 🛒 **Inventory Module** — Auto-generates shopping list from checklist task  
- 🚗 **Driver Route Log** — Assigns delivery task to drivers and logs order drops  
- 🧾 **Invoice Generator** — Integrates with catering output to generate invoices and assign print tasks  

---

### 🔐 Tech Stack

- **FastAPI** — Lightning-fast modern API framework
- **SQLite** (local dev) — Easy prototyping, can upgrade to Postgres
- **SQLAlchemy** — Full ORM for complex relational logic
- **Jinja2 Templates** — Lightweight HTML rendering for both Admin & Worker dashboards

---

### 👥 Who Is It For?

- Small business owners who want better visibility & control  
- Storefront/catering teams with high operational complexity  
- Anyone tired of yelling tasks across the kitchen and wondering if it got done

---

### 📈 Roadmap Highlights

- ✅ Role-based pin login (no full auth setup needed)
- ✅ Weekly shift view + task completion summaries
- ✅ Mobile-friendly layouts for on-the-go workers
- 🔜 Multi-tenant support for franchising/deployment
- 🔜 Finance email webhook module (auto-import Square/UberEats/Nayax reports)
- 🔜 Frontend landing page + user-configurable module builder

---

### ❤️ Built by Operators, For Operators

CookieOps was built out of necessity — not theory. It's the backend engine that helped one small NYC cookie shop grow from chaos to command.

Whether you're a café, catering kitchen, vending operator, or a multi-location food business — CookieOps is your **command center.**

---
